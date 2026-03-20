"""
Train product classifier for 356-class classification.
Uses torchvision EfficientNet-V2-S (compatible with sandbox torchvision 0.21.0).

Usage:
    python train_classifier.py --epochs 50 --batch 64 --name classifier-effv2s
"""

import argparse
import json
import time
from pathlib import Path
from datetime import datetime

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import transforms, datasets, models

DATASET_DIR = Path(__file__).parent / "classifier_data"
RUNS_DIR = Path(__file__).parent / "runs"
LOGS_FILE = Path(__file__).parent / "training_logs.jsonl"


def log_event(run_name: str, event: str, data: dict):
    entry = {
        "ts": time.time(),
        "time": datetime.now().isoformat(),
        "run": run_name,
        "event": event,
        **data,
    }
    with open(LOGS_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", type=str, default="classifier-effv2s")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--arch", type=str, default="efficientnet_v2_s", choices=["efficientnet_v2_s", "efficientnet_v2_m"])
    parser.add_argument("--imgsz", type=int, default=224)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Data transforms
    imgsz = args.imgsz
    train_transform = transforms.Compose([
        transforms.RandomResizedCrop(imgsz, scale=(0.6, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(15),
        transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.2),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    val_transform = transforms.Compose([
        transforms.Resize(int(imgsz * 1.14)),
        transforms.CenterCrop(imgsz),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    train_dataset = datasets.ImageFolder(DATASET_DIR / "train", transform=train_transform)
    val_dataset = datasets.ImageFolder(DATASET_DIR / "val", transform=val_transform)

    print(f"Train: {len(train_dataset)} images, {len(train_dataset.classes)} classes")
    print(f"Val: {len(val_dataset)} images")

    train_loader = DataLoader(train_dataset, batch_size=args.batch, shuffle=True, num_workers=4, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=args.batch, shuffle=False, num_workers=4, pin_memory=True)

    # Model: EfficientNet-V2 (pretrained)
    # Available in torchvision 0.21.0 (sandbox compatible)
    model_name = args.arch
    if model_name == "efficientnet_v2_m":
        model = models.efficientnet_v2_m(weights=models.EfficientNet_V2_M_Weights.IMAGENET1K_V1)
    else:
        model = models.efficientnet_v2_s(weights=models.EfficientNet_V2_S_Weights.IMAGENET1K_V1)
    num_classes = len(train_dataset.classes)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, num_classes)
    model = model.to(device)

    print(f"Model: {model_name}, classes: {num_classes}")
    param_count = sum(p.numel() for p in model.parameters())
    print(f"Parameters: {param_count:,}")

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

    log_event(args.name, "start", {
        "model": "efficientnet_v2_s",
        "epochs": args.epochs,
        "batch": args.batch,
        "lr": args.lr,
        "train_images": len(train_dataset),
        "val_images": len(val_dataset),
        "num_classes": num_classes,
    })

    best_val_acc = 0.0
    best_epoch = 0
    patience_counter = 0
    save_dir = RUNS_DIR / args.name
    save_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()

    for epoch in range(args.epochs):
        # Train
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0

        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            train_loss += loss.item() * images.size(0)
            _, predicted = outputs.max(1)
            train_correct += predicted.eq(labels).sum().item()
            train_total += labels.size(0)

        scheduler.step()

        train_loss /= train_total
        train_acc = train_correct / train_total

        # Validate
        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_top5_correct = 0
        val_total = 0

        with torch.no_grad():
            for images, labels in val_loader:
                images, labels = images.to(device), labels.to(device)
                outputs = model(images)
                loss = criterion(outputs, labels)

                val_loss += loss.item() * images.size(0)
                _, predicted = outputs.max(1)
                val_correct += predicted.eq(labels).sum().item()
                val_total += labels.size(0)

                # Top-5
                _, top5_pred = outputs.topk(5, dim=1)
                val_top5_correct += sum(labels[i].item() in top5_pred[i].tolist() for i in range(labels.size(0)))

        val_loss /= val_total
        val_acc = val_correct / val_total
        val_top5 = val_top5_correct / val_total

        print(f"Epoch {epoch+1}/{args.epochs} - train_loss: {train_loss:.4f}, train_acc: {train_acc:.4f}, "
              f"val_loss: {val_loss:.4f}, val_acc: {val_acc:.4f}, val_top5: {val_top5:.4f}, "
              f"lr: {scheduler.get_last_lr()[0]:.6f}")

        log_event(args.name, "epoch", {
            "epoch": epoch + 1,
            "total_epochs": args.epochs,
            "train_loss": round(train_loss, 4),
            "train_acc": round(train_acc, 4),
            "val_loss": round(val_loss, 4),
            "val_acc": round(val_acc, 4),
            "val_top5": round(val_top5, 4),
            "lr": round(scheduler.get_last_lr()[0], 6),
        })

        # Save best
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_epoch = epoch + 1
            patience_counter = 0
            torch.save({
                "model_state_dict": model.state_dict(),
                "class_to_idx": train_dataset.class_to_idx,
                "num_classes": num_classes,
                "arch": args.arch,
                "imgsz": imgsz,
                "val_acc": val_acc,
                "val_top5": val_top5,
                "epoch": epoch + 1,
            }, save_dir / "best_classifier.pt")
            print(f"  -> New best! Saved to {save_dir / 'best_classifier.pt'}")
        else:
            patience_counter += 1
            if patience_counter >= args.patience:
                print(f"Early stopping at epoch {epoch+1} (no improvement for {args.patience} epochs)")
                break

    duration = time.time() - start_time

    log_event(args.name, "complete", {
        "duration_s": round(duration, 1),
        "best_val_acc": round(best_val_acc, 4),
        "best_val_top5": round(val_top5, 4),
        "best_epoch": best_epoch,
    })

    print(f"\nTraining complete in {duration/60:.1f} min")
    print(f"Best val accuracy: {best_val_acc:.4f} (epoch {best_epoch})")
    print(f"Model saved: {save_dir / 'best_classifier.pt'}")

    # Save class mapping
    idx_to_class = {v: int(k) for k, v in train_dataset.class_to_idx.items()}
    with open(save_dir / "class_mapping.json", "w") as f:
        json.dump(idx_to_class, f)


if __name__ == "__main__":
    main()
