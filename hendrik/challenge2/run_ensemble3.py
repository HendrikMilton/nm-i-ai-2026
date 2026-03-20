"""
3-model ensemble: YOLO11x at 1600+1280+960 with Weighted Boxes Fusion.
All models are FP16 ONNX (~110MB each, ~330MB total, under 420MB limit).

Usage (by competition sandbox):
    python run.py --input /data/images --output /output/predictions.json
"""

import argparse
import json
import numpy as np
from pathlib import Path
from PIL import Image
import onnxruntime as ort
from ensemble_boxes import weighted_boxes_fusion


def letterbox(img: np.ndarray, new_shape: int = 640) -> tuple[np.ndarray, float, tuple[int, int]]:
    h, w = img.shape[:2]
    scale = min(new_shape / h, new_shape / w)
    nh, nw = int(h * scale), int(w * scale)
    resized = np.array(Image.fromarray(img).resize((nw, nh), Image.BILINEAR))
    padded = np.full((new_shape, new_shape, 3), 114, dtype=np.uint8)
    pad_h = (new_shape - nh) // 2
    pad_w = (new_shape - nw) // 2
    padded[pad_h:pad_h + nh, pad_w:pad_w + nw] = resized
    return padded, scale, (pad_w, pad_h)


def nms(boxes, scores, iou_threshold=0.5):
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
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
        order = order[np.where(iou <= iou_threshold)[0] + 1]
    return keep


def postprocess(output: np.ndarray, scale: float, pad: tuple[int, int],
                conf_threshold: float = 0.01, iou_threshold: float = 0.5):
    output = output[0]
    if output.shape[0] < output.shape[1]:
        output = output.T

    boxes_xywh = output[:, :4]
    class_scores = output[:, 4:]
    class_ids = class_scores.argmax(axis=1)
    confidences = class_scores.max(axis=1)

    mask = confidences >= conf_threshold
    boxes_xywh = boxes_xywh[mask]
    class_ids = class_ids[mask]
    confidences = confidences[mask]

    if len(boxes_xywh) == 0:
        return [], [], []

    boxes_xyxy = np.zeros_like(boxes_xywh)
    boxes_xyxy[:, 0] = boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2
    boxes_xyxy[:, 1] = boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2
    boxes_xyxy[:, 2] = boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2
    boxes_xyxy[:, 3] = boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2

    pad_w, pad_h = pad
    boxes_xyxy[:, [0, 2]] = (boxes_xyxy[:, [0, 2]] - pad_w) / scale
    boxes_xyxy[:, [1, 3]] = (boxes_xyxy[:, [1, 3]] - pad_h) / scale

    all_boxes, all_scores, all_labels = [], [], []
    for cls_id in np.unique(class_ids):
        cls_mask = class_ids == cls_id
        cls_boxes = boxes_xyxy[cls_mask]
        cls_confs = confidences[cls_mask]
        keep = nms(cls_boxes, cls_confs, iou_threshold)
        for k in keep:
            all_boxes.append(cls_boxes[k])
            all_scores.append(float(cls_confs[k]))
            all_labels.append(int(cls_id))

    return all_boxes, all_scores, all_labels


def run_model(session, img: np.ndarray, imgsz: int):
    padded, scale, pad = letterbox(img, imgsz)
    blob = padded.astype(np.float32) / 255.0
    blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: blob})
    return postprocess(outputs[0], scale, pad)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    models = [
        (ort.InferenceSession("model_1600.onnx", providers=providers), 1600),
        (ort.InferenceSession("model_1280.onnx", providers=providers), 1280),
        (ort.InferenceSession("model_960.onnx", providers=providers), 960),
    ]

    predictions = []

    for img_path in sorted(Path(args.input).iterdir()):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        image_id = int(img_path.stem.split("_")[-1])
        img = np.array(Image.open(img_path).convert("RGB"))
        h, w = img.shape[:2]

        boxes_list, scores_list, labels_list = [], [], []
        for session, imgsz in models:
            boxes, scores, labels = run_model(session, img, imgsz)
            if len(boxes) == 0:
                boxes_list.append(np.zeros((0, 4)))
                scores_list.append([])
                labels_list.append([])
            else:
                norm = np.array(boxes)
                norm[:, [0, 2]] /= w
                norm[:, [1, 3]] /= h
                norm = np.clip(norm, 0, 1)
                boxes_list.append(norm.tolist())
                scores_list.append(scores)
                labels_list.append(labels)

        fused_boxes, fused_scores, fused_labels = weighted_boxes_fusion(
            boxes_list, scores_list, labels_list,
            weights=[1, 1, 1],
            iou_thr=0.5,
            skip_box_thr=0.001,
        )

        for box, score, label in zip(fused_boxes, fused_scores, fused_labels):
            x1, y1, x2, y2 = box
            predictions.append({
                "image_id": image_id,
                "category_id": int(label),
                "bbox": [round(x1 * w, 1), round(y1 * h, 1),
                         round((x2 - x1) * w, 1), round((y2 - y1) * h, 1)],
                "score": round(float(score), 4),
            })

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(predictions, f)

    print(f"Wrote {len(predictions)} predictions to {args.output}")


if __name__ == "__main__":
    main()
