"""
Build classification dataset from:
1. Product reference images (327 products, multi-angle photos)
2. Cropped bounding boxes from shelf training images (22,731 annotations)

Output: ImageFolder structure for torchvision
    classifier_data/train/<category_id>/xxx.jpg
    classifier_data/val/<category_id>/xxx.jpg
"""

import json
import random
import shutil
from pathlib import Path
from PIL import Image

COCO_DIR = Path.home() / "NM_NGD_coco_dataset/train"
PRODUCT_DIR = Path.home() / "NM_NGD_product_images"
OUTPUT_DIR = Path(__file__).parent / "classifier_data"
SEED = 42


def crop_annotation(img_path: Path, bbox: list, padding: float = 0.05) -> Image.Image | None:
    """Crop a bounding box from an image with padding."""
    try:
        img = Image.open(img_path).convert("RGB")
    except Exception:
        return None

    w, h = img.size
    x, y, bw, bh = bbox

    # Add padding
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

    # Load annotations
    with open(COCO_DIR / "annotations.json") as f:
        coco = json.load(f)

    categories = {c["id"]: c["name"] for c in coco["categories"]}
    images_map = {img["id"]: img["file_name"] for img in coco["images"]}

    # Load product metadata
    with open(PRODUCT_DIR / "metadata.json") as f:
        meta = json.load(f)

    # Build name -> category_id mapping
    name_to_cat = {c["name"].strip().upper(): c["id"] for c in coco["categories"]}

    print(f"Categories: {len(categories)}")
    print(f"Annotations: {len(coco['annotations'])}")
    print(f"Products: {len(meta['products'])}")

    # Collect all samples: (source, category_id, image_path_or_crop_info)
    all_samples: dict[int, list] = {cat_id: [] for cat_id in categories}

    # Source 1: Product reference images
    product_count = 0
    for product in meta["products"]:
        if not product["has_images"]:
            continue
        name = product["product_name"].strip().upper()
        cat_id = name_to_cat.get(name)
        if cat_id is None:
            continue

        for view in product.get("image_types", []):
            img_path = PRODUCT_DIR / product["product_code"] / f"{view}.jpg"
            if img_path.exists():
                all_samples[cat_id].append(("product", img_path))
                product_count += 1

    print(f"Product reference images: {product_count}")

    # Source 2: Cropped bounding boxes from shelf images
    crop_count = 0
    for ann in coco["annotations"]:
        cat_id = ann["category_id"]
        img_file = images_map.get(ann["image_id"])
        if img_file is None:
            continue
        all_samples[cat_id].append(("crop", ann["image_id"], ann["bbox"], ann["id"]))
        crop_count += 1

    print(f"Shelf crop annotations: {crop_count}")

    # Split and save
    train_dir = OUTPUT_DIR / "train"
    val_dir = OUTPUT_DIR / "val"

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)

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

            for idx, sample in enumerate(split_samples):
                if sample[0] == "product":
                    _, img_path = sample
                    try:
                        img = Image.open(img_path).convert("RGB")
                        img.save(out_dir / f"prod_{idx}.jpg", quality=90)
                        if split == "train":
                            total_train += 1
                        else:
                            total_val += 1
                    except Exception:
                        pass
                elif sample[0] == "crop":
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

    print(f"\nDataset built:")
    print(f"  Categories with data: {cats_with_data}/{len(categories)}")
    print(f"  Train images: {total_train}")
    print(f"  Val images: {total_val}")
    print(f"  Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
