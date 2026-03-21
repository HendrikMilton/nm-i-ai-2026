# A100 Training Instructions

Train YOLO26x at maximum resolution for the NorgesGruppen grocery detection challenge.

## Goal

Train YOLO26x at imgsz=2048 on full dataset (248 images). This model will be exported to ONNX and submitted as a single model or as part of a 3-model ensemble.

## Why YOLO26x at 2048

- YOLO26x has RLE attention — better architecture than YOLO11x
- Images are 2000+ pixels — 2048 means almost no downscaling
- A100 has 40GB VRAM — can train at batch=8-16 at 2048 (vs batch=1-2 on L4)
- Larger batch = better gradient estimates = better model
- ONNX inference on L4 (24GB) at batch=1 is fine regardless of training batch size

## Setup

```bash
# 1. Pull latest code
cd ~/agentic-avengers-nm-ai && git pull && cd hendrik/challenge2

# 2. Install dependencies
pip install ultralytics==8.4.24 pycocotools ensemble-boxes

# 3. Copy training data from gcp-gpu
# Need: ~/NM_NGD_coco_dataset/train/ (248 images + annotations.json)
scp -r gcp-gpu:~/NM_NGD_coco_dataset ~/

# 4. Prepare full dataset (all 248 images for training)
python3 prepare_data.py
python3 -c "
import json, shutil, random
from pathlib import Path
from prepare_data import coco_to_yolo, create_data_yaml

coco_dir = Path.home() / 'NM_NGD_coco_dataset/train'
output_dir = Path('data_full')
with open(coco_dir / 'annotations.json') as f:
    coco = json.load(f)
output_dir.mkdir(parents=True, exist_ok=True)
coco_to_yolo(coco, coco_dir / 'images', output_dir / 'images/train', output_dir / 'labels/train')
(output_dir / 'images/val').mkdir(parents=True, exist_ok=True)
(output_dir / 'labels/val').mkdir(parents=True, exist_ok=True)
random.seed(42)
imgs = list((output_dir / 'images/train').iterdir())
for img in random.sample(imgs, 10):
    shutil.copy2(img, output_dir / 'images/val' / img.name)
    label = output_dir / 'labels/train' / (img.stem + '.txt')
    if label.exists():
        shutil.copy2(label, output_dir / 'labels/val' / label.name)
create_data_yaml(output_dir, coco['categories'])
print('Done')
"
```

## Training Commands

### Primary: YOLO26x at 2048 (full data)
```bash
python3 train.py --data data_full/data.yaml --model yolo26x.pt --name full-yolo26x-2048 \
    --imgsz 2048 --batch 8 --epochs 150 --patience 20 --skip-eval
```

If batch=8 OOMs, try batch=4. A100 40GB should handle batch=4-8 at 2048.

### Also train: YOLO26x at 1280 (full data, for ensemble diversity)
```bash
python3 train.py --data data_full/data.yaml --model yolo26x.pt --name full-yolo26x-1280 \
    --imgsz 1280 --batch 16 --epochs 100 --patience 15 --skip-eval
```

### Also useful: YOLO11x at 2048 (to compare architectures)
```bash
python3 train.py --data data_full/data.yaml --model yolo11x.pt --name full-yolo11x-2048 \
    --imgsz 2048 --batch 8 --epochs 150 --patience 20 --skip-eval
```

## After Training — Export to ONNX

```bash
python3 -c "
from ultralytics import YOLO

# Export each model as FP16 ONNX
for name, imgsz in [('full-yolo26x-2048', 2048), ('full-yolo26x-1280', 1280)]:
    model = YOLO(f'runs/{name}/weights/best.pt')
    model.export(format='onnx', imgsz=imgsz, opset=17, simplify=True, half=True)
    import os
    size = os.path.getsize(f'runs/{name}/weights/best.onnx') / 1024 / 1024
    print(f'{name}: {size:.0f} MB')
"
```

## Submission Constraints (MUST CHECK)

- Max zip uncompressed: 420 MB
- Max weight files (.pt, .onnx, .safetensors, .npy): **3**
- Sandbox: NVIDIA L4, 24GB VRAM, 8GB RAM, 300s timeout
- ONNX with CUDAExecutionProvider for GPU inference
- conf_threshold=0.001, iou_threshold=0.5 in postprocessing

## Submission Options

### Option A: Single YOLO26x-2048 (safest, fastest inference)
- 1 ONNX file (~110MB FP16)
- Use `run_onnx.py` (already exists, update conf to 0.001)
- Est inference: ~120s for 250 images

### Option B: 3-model ensemble (best accuracy)
- YOLO26x-2048 + YOLO11x-1280 + YOLO11x-960 = 3 ONNX files (~330MB)
- Use `run_ensemble3.py` pattern
- Est inference: ~250s for 250 images (tight but should fit)
- Copy YOLO11x models from gcp-gpu: `runs/full-yolo11x-1280/` and `runs/full-yolo11x-960/`

## Copy Results Back

```bash
# Copy trained weights back to gcp-gpu
scp runs/full-yolo26x-2048/weights/best.pt gcp-gpu:~/agentic-avengers-nm-ai/hendrik/challenge2/runs/full-yolo26x-2048/weights/best.pt
scp runs/full-yolo26x-2048/weights/best.onnx gcp-gpu:~/agentic-avengers-nm-ai/hendrik/challenge2/runs/full-yolo26x-2048/weights/best.onnx

# Or just copy the ONNX to build submission on gcp-gpu
scp runs/full-yolo26x-2048/weights/best.onnx gcp-gpu:~/yolo26x-2048.onnx
```

## Current Best Scores

| Submission | Leaderboard |
|-----------|-------------|
| Single YOLO11x-1280 | 0.9017 |
| 2-model ensemble (1280+640) | 0.9134 |
| 3-model ensemble (1600+1280+960) | 0.9183 |
| Rank 1 | 0.9200 |

Target: beat 0.9200.
