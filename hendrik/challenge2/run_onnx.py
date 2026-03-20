"""
ONNX-based competition submission entry point.
For models that don't match sandbox ultralytics version (e.g. YOLO11x, YOLO26x).

Usage (by competition sandbox):
    python run.py --input /data/images --output /output/predictions.json
"""

import argparse
import json
import numpy as np
from pathlib import Path
from PIL import Image
import onnxruntime as ort


def letterbox(img: np.ndarray, new_shape: int = 640) -> tuple[np.ndarray, float, tuple[int, int]]:
    """Resize image with letterboxing (maintain aspect ratio, pad with gray)."""
    h, w = img.shape[:2]
    scale = min(new_shape / h, new_shape / w)
    nh, nw = int(h * scale), int(w * scale)

    resized = np.array(Image.fromarray(img).resize((nw, nh), Image.BILINEAR))

    # Pad to square
    padded = np.full((new_shape, new_shape, 3), 114, dtype=np.uint8)
    pad_h = (new_shape - nh) // 2
    pad_w = (new_shape - nw) // 2
    padded[pad_h:pad_h + nh, pad_w:pad_w + nw] = resized

    return padded, scale, (pad_w, pad_h)


def nms(boxes, scores, iou_threshold=0.5):
    """Non-Maximum Suppression."""
    if len(boxes) == 0:
        return []

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)

    order = scores.argsort()[::-1]
    keep = []

    while order.size > 0:
        i = order[0]
        keep.append(i)

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)

        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]

    return keep


def postprocess(output: np.ndarray, scale: float, pad: tuple[int, int],
                conf_threshold: float = 0.01, iou_threshold: float = 0.5) -> list[dict]:
    """Process YOLO ONNX output to predictions."""
    # output shape: [1, num_classes+4, num_detections] for YOLOv8/11 format
    # or [1, num_detections, num_classes+4]
    output = output[0]

    # Detect format: if shape is [N, 4+C] vs [4+C, N]
    if output.shape[0] < output.shape[1]:
        output = output.T  # Now [num_detections, 4+num_classes]

    # Split boxes and class scores
    boxes_xywh = output[:, :4]
    class_scores = output[:, 4:]

    # Get best class per detection
    class_ids = class_scores.argmax(axis=1)
    confidences = class_scores.max(axis=1)

    # Filter by confidence
    mask = confidences >= conf_threshold
    boxes_xywh = boxes_xywh[mask]
    class_ids = class_ids[mask]
    confidences = confidences[mask]

    if len(boxes_xywh) == 0:
        return []

    # Convert xywh to xyxy
    boxes_xyxy = np.zeros_like(boxes_xywh)
    boxes_xyxy[:, 0] = boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2
    boxes_xyxy[:, 1] = boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2
    boxes_xyxy[:, 2] = boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2
    boxes_xyxy[:, 3] = boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2

    # Remove padding and rescale to original image coords
    pad_w, pad_h = pad
    boxes_xyxy[:, [0, 2]] = (boxes_xyxy[:, [0, 2]] - pad_w) / scale
    boxes_xyxy[:, [1, 3]] = (boxes_xyxy[:, [1, 3]] - pad_h) / scale

    # Per-class NMS
    results = []
    unique_classes = np.unique(class_ids)
    for cls_id in unique_classes:
        cls_mask = class_ids == cls_id
        cls_boxes = boxes_xyxy[cls_mask]
        cls_confs = confidences[cls_mask]

        keep = nms(cls_boxes, cls_confs, iou_threshold)
        for k in keep:
            x1, y1, x2, y2 = cls_boxes[k]
            results.append({
                "category_id": int(cls_id),
                "bbox": [round(float(x1), 1), round(float(y1), 1),
                         round(float(x2 - x1), 1), round(float(y2 - y1), 1)],
                "score": round(float(cls_confs[k]), 4),
            })

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    session = ort.InferenceSession(
        "model.onnx",
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    input_name = session.get_inputs()[0].name
    input_shape = session.get_inputs()[0].shape
    imgsz = input_shape[2] if len(input_shape) == 4 else 640

    predictions = []

    for img_path in sorted(Path(args.input).iterdir()):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        image_id = int(img_path.stem.split("_")[-1])

        img = np.array(Image.open(img_path).convert("RGB"))
        padded, scale, pad = letterbox(img, imgsz)

        # Preprocess: HWC -> NCHW, 0-255 -> 0-1, float32
        blob = padded.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]

        outputs = session.run(None, {input_name: blob})
        dets = postprocess(outputs[0], scale, pad)

        for det in dets:
            det["image_id"] = image_id
            predictions.append(det)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(predictions, f)

    print(f"Wrote {len(predictions)} predictions to {args.output}")


if __name__ == "__main__":
    main()
