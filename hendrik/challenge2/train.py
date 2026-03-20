"""
Train YOLO model on competition data with logging.

Usage:
    python train.py --data data/data.yaml --model yolov8x.pt --name baseline-yolov8x
    python train.py --data data/data.yaml --model yolo11x.pt --name experiment-yolo11x
"""

import argparse
import json
import time
from pathlib import Path
from datetime import datetime

from ultralytics import YOLO

RUNS_DIR = Path(__file__).parent / "runs"
LOGS_FILE = Path(__file__).parent / "training_logs.jsonl"


def log_event(run_name: str, event: str, data: dict):
    """Append a log event to the JSONL file."""
    entry = {
        "ts": time.time(),
        "time": datetime.now().isoformat(),
        "run": run_name,
        "event": event,
        **data,
    }
    with open(LOGS_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def train(args):
    run_name = args.name
    log_event(run_name, "start", {
        "model": args.model,
        "data": args.data,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "epochs": args.epochs,
        "patience": args.patience,
    })

    print(f"\n{'='*60}")
    print(f"Training run: {run_name}")
    print(f"Model: {args.model}")
    print(f"Image size: {args.imgsz}, Batch: {args.batch}, Epochs: {args.epochs}")
    print(f"{'='*60}\n")

    model = YOLO(args.model)

    # Track epoch metrics
    def on_fit_epoch_end(trainer):
        epoch = trainer.epoch + 1
        loss = float(trainer.loss_items.sum()) if trainer.loss_items is not None else 0.0
        box_loss = float(trainer.loss_items[0]) if trainer.loss_items is not None else 0.0
        cls_loss = float(trainer.loss_items[1]) if trainer.loss_items is not None else 0.0

        mAP50 = 0.0
        mAP50_95 = 0.0
        if hasattr(trainer, 'validator') and trainer.validator and hasattr(trainer.validator, 'metrics'):
            m = trainer.validator.metrics
            if hasattr(m, 'box'):
                mAP50 = float(m.box.map50)
                mAP50_95 = float(m.box.map)

        log_event(run_name, "epoch", {
            "epoch": epoch,
            "total_epochs": args.epochs,
            "loss": round(loss, 4),
            "box_loss": round(box_loss, 4),
            "cls_loss": round(cls_loss, 4),
            "mAP50": round(mAP50, 4),
            "mAP50_95": round(mAP50_95, 4),
        })

    model.add_callback("on_fit_epoch_end", on_fit_epoch_end)

    start_time = time.time()

    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=args.patience,
        save=True,
        project=str(RUNS_DIR),
        name=run_name,
        exist_ok=True,
        verbose=True,
        device=0,
    )

    duration = time.time() - start_time

    # Extract final metrics
    metrics = results.results_dict if hasattr(results, "results_dict") else {}
    mAP50 = metrics.get("metrics/mAP50(B)", 0.0) or 0.0
    mAP50_95 = metrics.get("metrics/mAP50-95(B)", 0.0) or 0.0
    precision = metrics.get("metrics/precision(B)", 0.0) or 0.0
    recall = metrics.get("metrics/recall(B)", 0.0) or 0.0

    # Find best weights
    weights_dir = RUNS_DIR / run_name / "weights"
    best_pt = weights_dir / "best.pt"

    log_event(run_name, "complete", {
        "duration_s": round(duration, 1),
        "mAP50": round(mAP50, 4),
        "mAP50_95": round(mAP50_95, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "best_weights": str(best_pt) if best_pt.exists() else None,
    })

    print(f"\n{'='*60}")
    print(f"Training complete: {run_name}")
    print(f"Duration: {duration/60:.1f} min")
    print(f"mAP@0.5: {mAP50:.4f}")
    print(f"mAP@0.5:0.95: {mAP50_95:.4f}")
    print(f"Precision: {precision:.4f}, Recall: {recall:.4f}")
    print(f"Best weights: {best_pt}")
    print(f"{'='*60}\n")

    return best_pt


def run_eval(best_pt: Path, data_dir: Path, run_name: str):
    """Run evaluation on val set and log results."""
    from evaluate import evaluate

    print(f"\nRunning evaluation with {best_pt}...")

    model = YOLO(str(best_pt))
    val_images = data_dir / "images" / "val"
    predictions = []

    for img_path in sorted(val_images.iterdir()):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        image_id = int(img_path.stem.split("_")[-1])

        results = model(str(img_path), device=0, verbose=False)
        for r in results:
            if r.boxes is None:
                continue
            for i in range(len(r.boxes)):
                x1, y1, x2, y2 = r.boxes.xyxy[i].tolist()
                predictions.append({
                    "image_id": image_id,
                    "category_id": int(r.boxes.cls[i].item()),
                    "bbox": [round(x1, 1), round(y1, 1), round(x2 - x1, 1), round(y2 - y1, 1)],
                    "score": round(float(r.boxes.conf[i].item()), 4),
                })

    # Save predictions
    preds_path = RUNS_DIR / run_name / "predictions.json"
    preds_path.parent.mkdir(parents=True, exist_ok=True)
    with open(preds_path, "w") as f:
        json.dump(predictions, f)

    print(f"Generated {len(predictions)} predictions")

    # Evaluate
    gt_path = data_dir / "val_annotations.json"
    scores = evaluate(str(preds_path), str(gt_path))

    log_event(run_name, "eval", {
        "num_predictions": len(predictions),
        **scores,
    })

    return scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, default="data/data.yaml")
    parser.add_argument("--model", type=str, default="yolov8x.pt")
    parser.add_argument("--name", type=str, required=True)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--skip-eval", action="store_true")
    args = parser.parse_args()

    best_pt = train(args)

    if not args.skip_eval and best_pt and best_pt.exists():
        data_dir = Path(args.data).parent
        run_eval(best_pt, data_dir, args.name)


if __name__ == "__main__":
    main()
