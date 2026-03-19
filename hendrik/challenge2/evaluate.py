"""
Local evaluation using the competition's exact scoring formula.

Score = 0.7 * detection_mAP@0.5 + 0.3 * classification_mAP@0.5

Usage:
    python evaluate.py --predictions predictions.json --ground-truth data/val_annotations.json
"""

import argparse
import json
import numpy as np
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval
import io
import contextlib


def evaluate(predictions_path: str, ground_truth_path: str) -> dict:
    """Evaluate predictions against ground truth using competition scoring."""

    # Load ground truth
    with open(ground_truth_path) as f:
        gt_data = json.load(f)

    # Load predictions
    with open(predictions_path) as f:
        predictions = json.load(f)

    if len(predictions) == 0:
        print("No predictions found!")
        return {"score": 0.0, "detection_mAP": 0.0, "classification_mAP": 0.0}

    # --- Detection mAP (category-agnostic) ---
    # Treat all predictions and GT as single class
    gt_detection = {
        "images": gt_data["images"],
        "categories": [{"id": 1, "name": "product"}],
        "annotations": [
            {**ann, "category_id": 1, "id": i + 1}
            for i, ann in enumerate(gt_data["annotations"])
        ],
    }

    det_predictions = [
        {**p, "category_id": 1}
        for p in predictions
    ]

    # Suppress pycocotools print output
    with contextlib.redirect_stdout(io.StringIO()):
        coco_gt_det = COCO()
        coco_gt_det.dataset = gt_detection
        coco_gt_det.createIndex()

        coco_dt_det = coco_gt_det.loadRes(det_predictions)
        eval_det = COCOeval(coco_gt_det, coco_dt_det, "bbox")
        eval_det.params.iouThrs = [0.5]  # Only IoU=0.5
        eval_det.evaluate()
        eval_det.accumulate()
        eval_det.summarize()

    # mAP@0.5 is the first value
    detection_mAP = float(eval_det.stats[0])

    # --- Classification mAP (category-aware) ---
    with contextlib.redirect_stdout(io.StringIO()):
        coco_gt_cls = COCO()
        coco_gt_cls.dataset = gt_data
        coco_gt_cls.createIndex()

        coco_dt_cls = coco_gt_cls.loadRes(predictions)
        eval_cls = COCOeval(coco_gt_cls, coco_dt_cls, "bbox")
        eval_cls.params.iouThrs = [0.5]
        eval_cls.evaluate()
        eval_cls.accumulate()
        eval_cls.summarize()

    classification_mAP = float(eval_cls.stats[0])

    # Combined score
    score = 0.7 * detection_mAP + 0.3 * classification_mAP

    return {
        "score": round(score, 4),
        "detection_mAP": round(detection_mAP, 4),
        "classification_mAP": round(classification_mAP, 4),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=str, required=True)
    parser.add_argument("--ground-truth", type=str, required=True)
    args = parser.parse_args()

    results = evaluate(args.predictions, args.ground_truth)

    print(f"\nDetection mAP@0.5:       {results['detection_mAP']:.4f}")
    print(f"Classification mAP@0.5:  {results['classification_mAP']:.4f}")
    print(f"Combined score:          {results['score']:.4f}")
    print(f"\nscore: {results['score']:.4f}")  # parseable line for autoresearch


if __name__ == "__main__":
    main()
