"""
3-model ensemble detection + ONNX classifier. Fully ONNX — no PyTorch needed.
YOLO11x at 1600+1280+960 with WBF, then ONNX classifier re-classifies each crop.

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


def run_yolo(session, img: np.ndarray, imgsz: int):
    padded, scale, pad = letterbox(img, imgsz)
    blob = padded.astype(np.float32) / 255.0
    blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: blob})
    return postprocess(outputs[0], scale, pad)


def preprocess_crop(img_pil: Image.Image, box: list, w: int, h: int, imgsz: int = 160) -> np.ndarray | None:
    """Crop, resize, normalize for classifier."""
    x1 = max(0, int(box[0] * w))
    y1 = max(0, int(box[1] * h))
    x2 = min(w, int(box[2] * w))
    y2 = min(h, int(box[3] * h))
    if x2 - x1 < 5 or y2 - y1 < 5:
        return None
    crop = img_pil.crop((x1, y1, x2, y2)).resize((imgsz, imgsz), Image.BILINEAR)
    arr = np.array(crop).astype(np.float32) / 255.0
    # Normalize with ImageNet stats
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    arr = (arr - mean) / std
    return np.transpose(arr, (2, 0, 1))  # CHW


def softmax(x):
    e = np.exp(x - np.max(x, axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]

    yolo_models = [
        (ort.InferenceSession("model_1600.onnx", providers=providers), 1600),
        (ort.InferenceSession("model_1280.onnx", providers=providers), 1280),
        (ort.InferenceSession("model_960.onnx", providers=providers), 960),
    ]
    cls_session = ort.InferenceSession("classifier.onnx", providers=providers)
    cls_input_name = cls_session.get_inputs()[0].name

    # Load class mapping
    class_mapping = json.load(open("class_mapping.json"))
    idx_to_cat = {int(k): int(v) for k, v in class_mapping.items()}

    predictions = []

    for img_path in sorted(Path(args.input).iterdir()):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        image_id = int(img_path.stem.split("_")[-1])
        img_pil = Image.open(img_path).convert("RGB")
        img_np = np.array(img_pil)
        h, w = img_np.shape[:2]

        # Run 3 YOLO models
        boxes_list, scores_list, labels_list = [], [], []
        for session, imgsz in yolo_models:
            boxes, scores, labels = run_yolo(session, img_np, imgsz)
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
            weights=[1, 1, 1], iou_thr=0.5, skip_box_thr=0.001)

        # Prepare crops for classifier (skip high-conf detections)
        det_data = []
        crop_batch = []
        crop_indices = []

        for i, (box, score, yolo_label) in enumerate(zip(fused_boxes, fused_scores, fused_labels)):
            det_data.append((box, float(score), int(yolo_label)))

            if float(score) < 0.9:
                crop = preprocess_crop(img_pil, box, w, h, 160)
                if crop is not None:
                    crop_batch.append(crop)
                    crop_indices.append(i)

        # Batch classify
        cls_results = {}
        if crop_batch:
            batch = np.stack(crop_batch).astype(np.float32)
            # Process in chunks
            for start in range(0, len(batch), 64):
                chunk = batch[start:start + 64]
                logits = cls_session.run(None, {cls_input_name: chunk})[0]
                probs = softmax(logits)
                confs = probs.max(axis=1)
                idxs = probs.argmax(axis=1)
                for j in range(len(chunk)):
                    det_idx = crop_indices[start + j]
                    if confs[j] > 0.5:
                        cls_results[det_idx] = idx_to_cat.get(int(idxs[j]), det_data[det_idx][2])

        # Build predictions
        for i, (box, score, yolo_label) in enumerate(det_data):
            x1_n, y1_n, x2_n, y2_n = box
            x1, y1, x2, y2 = x1_n * w, y1_n * h, x2_n * w, y2_n * h
            cat_id = cls_results.get(i, yolo_label)
            predictions.append({
                "image_id": image_id,
                "category_id": cat_id,
                "bbox": [round(float(x1), 1), round(float(y1), 1),
                         round(float(x2 - x1), 1), round(float(y2 - y1), 1)],
                "score": round(float(score), 4),
            })

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(predictions, f)
    print(f"Wrote {len(predictions)} predictions to {args.output}")


if __name__ == "__main__":
    main()
