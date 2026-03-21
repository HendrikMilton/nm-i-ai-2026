"""
Build classification dataset from shelf crops ONLY (no product reference images).
This matches test-time distribution better.
"""

import json
import random
import shutil
from pathlib import Path
from PIL import Image

COCO_DIR = Path.home() / "NM_NGD_coco_dataset/train"
OUTPUT_DIR = Path(__file__).parent / "classifier_data_shelf"
SEED = 42


def crop_annotation(img_path: Path, bbox: list, padding: float = 0.05) -> Image.Image | None:
    try:
        img = Image.open(img_path).convert("RGB")
    except Exception:
        return None
    w, h = img.size
    x, y, bw, bh = bbox
    pad_x = bw * padding
    pad_y = bh * padding
    x1 = max(0, int(x - pad_x))
    y1 = max(0, int(y - pad_y))
    x2 = min(w, int(x + bw + pad_x))
    y2 = min(h, int(y + bh + pad_y))
    if x2 - x1 < 10 or y2 - y1 < 10:
        return None
    return img.crop((x1, y1, x2, y2))


def main():
    random.seed(SEED)

    with open(COCO_DIR / "annotations.json") as f:
        coco = json.load(f)

    categories = {c["id"]: c["name"] for c in coco["categories"]}
    images_map = {img["id"]: img["file_name"] for img in coco["images"]}

    all_samples: dict[int, list] = {cat_id: [] for cat_id in categories}

    for ann in coco["annotations"]:
        cat_id = ann["category_id"]
        all_samples[cat_id].append(("crop", ann["image_id"], ann["bbox"], ann["id"]))

    print(f"Categories: {len(categories)}")
    print(f"Total shelf crops: {sum(len(v) for v in all_samples.values())}")

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)

    train_dir = OUTPUT_DIR / "train"
    val_dir = OUTPUT_DIR / "val"
    total_train = 0
    total_val = 0
    cats_with_data = 0

    for cat_id, samples in all_samples.items():
        if len(samples) == 0:
            continue
        cats_with_data += 1
        random.shuffle(samples)
        split_idx = max(1, int(len(samples) * 0.8))
        train_samples = samples[:split_idx]
        val_samples = samples[split_idx:] if len(samples) > 1 else samples[:1]

        for split, split_samples in [("train", train_samples), ("val", val_samples)]:
            out_dir = (train_dir if split == "train" else val_dir) / str(cat_id)
            out_dir.mkdir(parents=True, exist_ok=True)

            for sample in split_samples:
                _, img_id, bbox, ann_id = sample
                img_file = images_map[img_id]
                img_path = COCO_DIR / "images" / img_file
                crop = crop_annotation(img_path, bbox)
                if crop is not None:
                    crop.save(out_dir / f"crop_{ann_id}.jpg", quality=90)
                    if split == "train":
                        total_train += 1
                    else:
                        total_val += 1

    print(f"\nDataset built (shelf crops only):")
    print(f"  Categories: {cats_with_data}/{len(categories)}")
    print(f"  Train: {total_train}")
    print(f"  Val: {total_val}")


if __name__ == "__main__":
    main()
