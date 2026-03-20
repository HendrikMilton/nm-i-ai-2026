"""
Two-stage submission: YOLO11x-1280 for detection + EfficientNet-V2-S for classification.
YOLO finds boxes, classifier re-classifies each crop.

Usage (by competition sandbox):
    python run.py --input /data/images --output /output/predictions.json
"""

import argparse
import json
import numpy as np
from pathlib import Path
from PIL import Image
import onnxruntime as ort
import torch
import torch.nn as nn
from torchvision import transforms, models


def letterbox(img: np.ndarray, new_shape: int = 1280) -> tuple[np.ndarray, float, tuple[int, int]]:
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


def postprocess_yolo(output: np.ndarray, scale: float, pad: tuple[int, int],
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


def load_classifier(device):
    """Load EfficientNet-V2-S classifier."""
    checkpoint = torch.load("classifier.pt", map_location=device, weights_only=False)
    num_classes = checkpoint["num_classes"]
    class_to_idx = checkpoint["class_to_idx"]

    # Invert: idx -> category_id
    idx_to_cat = {v: int(k) for k, v in class_to_idx.items()}

    model = models.efficientnet_v2_s()
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, num_classes)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    model.eval()

    transform = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    return model, transform, idx_to_cat


def classify_crop(img_pil: Image.Image, crop_box: list, classifier, transform, device) -> tuple[int, float]:
    """Crop and classify a detection."""
    w, h = img_pil.size
    x1 = max(0, int(crop_box[0]))
    y1 = max(0, int(crop_box[1]))
    x2 = min(w, int(crop_box[2]))
    y2 = min(h, int(crop_box[3]))

    if x2 - x1 < 5 or y2 - y1 < 5:
        return -1, 0.0

    crop = img_pil.crop((x1, y1, x2, y2))
    inp = transform(crop).unsqueeze(0).to(device)

    with torch.no_grad():
        logits = classifier(inp)
        probs = torch.softmax(logits, dim=1)
        conf, idx = probs.max(1)

    return idx.item(), conf.item()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Load YOLO
    yolo_session = ort.InferenceSession(
        "model.onnx",
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    yolo_input_name = yolo_session.get_inputs()[0].name
    yolo_imgsz = yolo_session.get_inputs()[0].shape[2]

    # Load classifier
    classifier, cls_transform, idx_to_cat = load_classifier(device)

    predictions = []

    for img_path in sorted(Path(args.input).iterdir()):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        image_id = int(img_path.stem.split("_")[-1])

        img_pil = Image.open(img_path).convert("RGB")
        img_np = np.array(img_pil)

        # YOLO detection
        padded, scale, pad = letterbox(img_np, yolo_imgsz)
        blob = padded.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
        outputs = yolo_session.run(None, {yolo_input_name: blob})
        boxes, scores, yolo_labels = postprocess_yolo(outputs[0], scale, pad)

        # Classify each detection
        for box, score, yolo_label in zip(boxes, scores, yolo_labels):
            x1, y1, x2, y2 = box

            # Run classifier on crop
            cls_idx, cls_conf = classify_crop(img_pil, [x1, y1, x2, y2], classifier, cls_transform, device)

            # Decide: use classifier if confident, else keep YOLO
            if cls_idx >= 0 and cls_conf > 0.5:
                category_id = idx_to_cat.get(cls_idx, yolo_label)
            else:
                category_id = yolo_label

            predictions.append({
                "image_id": image_id,
                "category_id": category_id,
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
