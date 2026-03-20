"""
Split COCO dataset into train/val and convert to YOLO format.

Usage:
    python prepare_data.py --coco-dir ~/NM_NGD_coco_dataset/train --output-dir ./data
"""

import argparse
import json
import shutil
import random
from pathlib import Path
from collections import defaultdict


def split_coco(annotations_path: Path, val_ratio: float = 0.2, seed: int = 42):
    """Split COCO annotations into train/val with stratified sampling by image."""
    with open(annotations_path) as f:
        coco = json.load(f)

    random.seed(seed)
    images = coco["images"]
    random.shuffle(images)

    split_idx = int(len(images) * (1 - val_ratio))
    train_images = images[:split_idx]
    val_images = images[split_idx:]

    train_ids = {img["id"] for img in train_images}
    val_ids = {img["id"] for img in val_images}

    train_anns = [a for a in coco["annotations"] if a["image_id"] in train_ids]
    val_anns = [a for a in coco["annotations"] if a["image_id"] in val_ids]

    train_coco = {"images": train_images, "categories": coco["categories"], "annotations": train_anns}
    val_coco = {"images": val_images, "categories": coco["categories"], "annotations": val_anns}

    print(f"Train: {len(train_images)} images, {len(train_anns)} annotations")
    print(f"Val:   {len(val_images)} images, {len(val_anns)} annotations")

    return train_coco, val_coco


def coco_to_yolo(coco_data: dict, images_src: Path, images_dst: Path, labels_dst: Path):
    """Convert COCO annotations to YOLO format and copy images."""
    images_dst.mkdir(parents=True, exist_ok=True)
    labels_dst.mkdir(parents=True, exist_ok=True)

    # Build image id -> info map
    img_map = {img["id"]: img for img in coco_data["images"]}

    # Group annotations by image
    anns_by_image = defaultdict(list)
    for ann in coco_data["annotations"]:
        anns_by_image[ann["image_id"]].append(ann)

    copied = 0
    for img_id, img_info in img_map.items():
        filename = img_info["file_name"]
        w, h = img_info["width"], img_info["height"]

        # Find source image (could be .jpg or .jpeg)
        src = images_src / filename
        if not src.exists():
            # Try alternate extension
            stem = src.stem
            for ext in [".jpg", ".jpeg", ".png"]:
                alt = images_src / f"{stem}{ext}"
                if alt.exists():
                    src = alt
                    break

        if not src.exists():
            print(f"Warning: {filename} not found, skipping")
            continue

        # Copy image (normalize to .jpg name)
        dst_name = src.stem + src.suffix
        shutil.copy2(src, images_dst / dst_name)

        # Write YOLO labels
        label_path = labels_dst / f"{src.stem}.txt"
        lines = []
        for ann in anns_by_image.get(img_id, []):
            cat_id = ann["category_id"]
            bx, by, bw, bh = ann["bbox"]  # COCO: x, y, w, h in pixels

            # Convert to YOLO: cx, cy, w, h normalized
            cx = (bx + bw / 2) / w
            cy = (by + bh / 2) / h
            nw = bw / w
            nh = bh / h

            # Clamp to [0, 1]
            cx = max(0, min(1, cx))
            cy = max(0, min(1, cy))
            nw = max(0, min(1, nw))
            nh = max(0, min(1, nh))

            lines.append(f"{cat_id} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")

        label_path.write_text("\n".join(lines) + "\n" if lines else "")
        copied += 1

    print(f"Copied {copied} images to {images_dst}")


def create_data_yaml(output_dir: Path, categories: list[dict]):
    """Create YOLO data.yaml."""
    names = {cat["id"]: cat["name"] for cat in categories}
    nc = len(categories)

    yaml_lines = [
        f"path: {output_dir.resolve()}",
        "train: images/train",
        "val: images/val",
        "",
        f"nc: {nc}",
        "names:",
    ]
    for i in range(nc):
        name = names.get(i, f"class_{i}")
        yaml_lines.append(f"  {i}: \"{name}\"")

    (output_dir / "data.yaml").write_text("\n".join(yaml_lines) + "\n")
    print(f"Created data.yaml with {nc} classes")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coco-dir", type=Path, default=Path.home() / "NM_NGD_coco_dataset/train")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "data")
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    annotations_path = args.coco_dir / "annotations.json"
    images_src = args.coco_dir / "images"
    output_dir = args.output_dir

    print(f"COCO dir: {args.coco_dir}")
    print(f"Output dir: {output_dir}")
    print()

    # Split
    train_coco, val_coco = split_coco(annotations_path, args.val_ratio, args.seed)

    # Save COCO splits (for eval script)
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "val_annotations.json", "w") as f:
        json.dump(val_coco, f)
    with open(output_dir / "train_annotations.json", "w") as f:
        json.dump(train_coco, f)

    # Convert to YOLO
    coco_to_yolo(train_coco, images_src, output_dir / "images/train", output_dir / "labels/train")
    coco_to_yolo(val_coco, images_src, output_dir / "images/val", output_dir / "labels/val")

    # Create data.yaml
    create_data_yaml(output_dir, train_coco["categories"])

    print("\nDone! Ready for training.")


if __name__ == "__main__":
    main()
