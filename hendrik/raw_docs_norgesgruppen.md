================================================================================================ OVERVIEW ================================================================================================

NorgesGruppen Data: Object Detection
Detect grocery products on store shelves. Upload your model code as a .zip file — it runs in a sandboxed Docker container on our servers.
How It Works

Download the training data from the competition website (requires login)
Train your object detection model locally
Write a run.py that takes shelf images as input and outputs predictions
Zip your code + model weights
Upload at the submit page
Our server runs your code in a sandbox with GPU (NVIDIA L4, 24 GB VRAM) — no network access
Your predictions are scored: 70% detection (did you find products?) + 30% classification (did you identify the right product?)
Score appears on the leaderboard

Downloads
Download training data and product reference images from the Submit page on the competition website (login required).
Training Data
Two files are available for download:
COCO Dataset (NM_NGD_coco_dataset.zip, ~864 MB)

248 shelf images from Norwegian grocery stores
~22,700 COCO-format bounding box annotations
356 product categories (category_id 0-355) — detect and identify grocery products
Images from 4 store sections: Egg, Frokost, Knekkebrod, Varmedrikker

Product Reference Images (NM_NGD_product_images.zip, ~60 MB)

327 individual products with multi-angle photos (main, front, back, left, right, top, bottom)
Organized by barcode: {product_code}/main.jpg, {product_code}/front.jpg, etc.
Includes metadata.json with product names and annotation counts

Annotation Format
The COCO annotations file (annotations.json) contains:
{
"images": [
{"id": 1, "file_name": "img_00001.jpg", "width": 2000, "height": 1500}
],
"categories": [
{"id": 0, "name": "VESTLANDSLEFSA TØRRE 10STK 360G", "supercategory": "product"},
{"id": 1, "name": "COFFEE MATE 180G NESTLE", "supercategory": "product"},
...
{"id": 356, "name": "unknown_product", "supercategory": "product"}
],
"annotations": [
{
"id": 1,
"image_id": 1,
"category_id": 42,
"bbox": [141, 49, 169, 152],
"area": 25688,
"iscrowd": 0,
"product_code": "8445291513365",
"product_name": "NESCAFE VANILLA LATTE 136G NESTLE",
"corrected": true
}
]
}
Key fields: bbox is [x, y, width, height] in pixels (COCO format). product_code is the barcode. corrected indicates manually verified annotations.
What Annotations Look Like
A training image with all ground truth boxes (green = correctly detected product):

Compare with a ~50% mAP result — half the products are missed entirely, and some detected boxes (red) are imprecise:

Submit
Upload your .zip at the submission page on the competition website.
MCP Setup
Connect this docs server to your AI coding tool:
claude mcp add --transport http nmiai https://mcp-docs.ainm.no/mcp


================================================================================================ SUBMISSION ================================================================================================

NorgesGruppen Data: Submission Format
Zip Structure
Your .zip must contain run.py at the root. You may include model weights and Python helper files.
submission.zip
├── run.py          # Required: entry point
├── model.onnx      # Optional: model weights (.pt, .onnx, .safetensors, .npy)
└── utils.py        # Optional: helper code

Limits:



Limit
Value




Max zip size (uncompressed)
420 MB


Max files
1000


Max Python files
10


Max weight files (.pt, .pth, .onnx, .safetensors, .npy)
3


Max weight size total
420 MB


Allowed file types
.py, .json, .yaml, .yml, .cfg, .pt, .pth, .onnx, .safetensors, .npy



run.py Contract
Your script is executed as:
python run.py --input /data/images --output /output/predictions.json
Input
/data/images/ contains JPEG shelf images. File names use the format img_XXXXX.jpg (e.g., img_00042.jpg).
Output
Write a JSON array to the --output path:
[
{
"image_id": 42,
"category_id": 0,
"bbox": [120.5, 45.0, 80.0, 110.0],
"score": 0.923
}
]



Field
Type
Description




image_id
int
Numeric ID from filename (img_00042.jpg → 42)


category_id
int
Product category ID (0-355). See categories list in annotations.json


bbox
[x, y, w, h]
Bounding box in COCO format


score
float
Confidence score (0-1)



Scoring
Your score combines detection and classification:

70% detection mAP — did you find the products? (bounding box IoU ≥ 0.5, category ignored)
30% classification mAP — did you identify the right product? (IoU ≥ 0.5 AND correct category_id)

Detection-only submissions (category_id: 0 for all predictions) score up to 70%. Product identification adds the remaining 30%.
Product Categories
The training data annotations.json contains a categories list mapping integer IDs to product names:
"categories": [
{"id": 0, "name": "VESTLANDSLEFSA TØRRE 10STK 360G", "supercategory": "product"},
{"id": 1, "name": "COFFEE MATE 180G NESTLE", "supercategory": "product"},
...
{"id": 356, "name": "unknown_product", "supercategory": "product"}
]
Your predictions must use the same category_id values. When training YOLOv8 on this COCO data (with nc=357), the model learns the mapping and outputs the correct category_id during inference.
Sandbox Environment
Your code runs in a Docker container with these constraints:



Resource
Limit




Python
3.11


CPU
4 vCPU


Memory
8 GB


GPU
NVIDIA L4 (24 GB VRAM)


CUDA
12.4


Network
None (fully offline)


Timeout
300 seconds



GPU
An NVIDIA L4 GPU is always available in the sandbox. Your code auto-detects it:

torch.cuda.is_available() returns True
No opt-in flag needed — GPU is always on
For ONNX models, use ["CUDAExecutionProvider", "CPUExecutionProvider"] as the provider list

Pre-installed Packages
PyTorch 2.6.0+cu124, torchvision 0.21.0+cu124, ultralytics 8.1.0, onnxruntime-gpu 1.20.0, opencv-python-headless 4.9.0.80, albumentations 1.3.1, Pillow 10.2.0, numpy 1.26.4, scipy 1.12.0, scikit-learn 1.4.0, pycocotools 2.0.7, ensemble-boxes 1.0.9, timm 0.9.12, supervision 0.18.0, safetensors 0.4.2.
You cannot pip install at runtime.
Training Environment
You can use any computer vision architecture — the sandbox supports all models via ONNX, custom PyTorch code, or the pre-installed frameworks. You don't need all sandbox packages for training — only match the versions of packages you actually use.
Models available in the sandbox
These frameworks are pre-installed. If you train with the exact same version, you can submit .pt weights directly:



Framework
Models
Pin this version




ultralytics 8.1.0
YOLOv8n/s/m/l/x, YOLOv5u, RT-DETR-l/x
ultralytics==8.1.0


torchvision 0.21.0
Faster R-CNN, RetinaNet, SSD, FCOS, Mask R-CNN
torchvision==0.21.0


timm 0.9.12
ResNet, EfficientNet, ViT, Swin, ConvNeXt, etc. (as backbones)
timm==0.9.12



Models not in the sandbox
YOLOv9, YOLOv10, YOLO11, RF-DETR, Detectron2, MMDetection, HuggingFace Transformers — these packages are not installed. Two options:

Export to ONNX: Export from any framework, load with onnxruntime in your run.py. Use opset version ≤ 20. Use CUDAExecutionProvider for GPU acceleration.
Include model code: Put your model class in your .py files + .pt state_dict weights. Works if the model only uses standard PyTorch ops.

HuggingFace .bin files: The .bin extension is not allowed, but the format is identical to .pt (PyTorch pickle). Rename .bin → .pt, or convert with safetensors.torch.save_file(state_dict, "model.safetensors").
Models larger than 420 MB: Quantize to FP16 or INT8 to fit within the 420 MB weight limit. FP16 is the recommended precision for L4 GPU inference — it's both smaller and faster.
Setting up your training environment
Only install the packages you need, with matching versions:
# YOLOv8 training
pip install ultralytics==8.1.0

# torchvision detector
pip install torch==2.6.0 torchvision==0.21.0

# Custom model with timm backbone
pip install torch==2.6.0 timm==0.9.12

# For GPU training, add the CUDA index:
pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
The sandbox has a GPU (NVIDIA L4 with CUDA 12.4), so GPU-trained weights run natively — no map_location="cpu" needed. Your code should auto-detect with torch.cuda.is_available().
Train anywhere: You can train on any hardware — your laptop CPU, a cloud GPU, Google Colab, GCP VMs, etc. Models trained on any platform will run on the sandbox GPU. Use state_dict saves (not full model saves) or ONNX export for maximum compatibility.
Version compatibility



Risk
What happens
Fix




ultralytics 8.2+ weights on 8.1.0
Model class changed, load fails
Pin ultralytics==8.1.0 or export to ONNX


torch 2.7+ full model save on 2.6.0
May reference newer operators
Use torch.save(model.state_dict()), not torch.save(model)


timm 1.0+ weights on 0.9.12
Layer names changed, load fails
Pin timm==0.9.12 or export to ONNX


ONNX opset > 20
onnxruntime 1.20.0 can't load it
Export with opset_version=17



Recommended weight formats



Approach
Format
When to use




ONNX export
.onnx
Universal — any framework, 2-3x faster on CPU


ultralytics .pt (pinned 8.1.0)
.pt
Simple YOLOv8/RT-DETR workflow


state_dict + model class
.pt
Custom architectures with standard PyTorch ops


safetensors
.safetensors
Safe loading, no pickle, fast



Security Restrictions
The following imports are blocked by the security scanner:

os, sys, subprocess, socket, ctypes, builtins, importlib
pickle, marshal, shelve, shutil
yaml (use json for config files instead)
requests, urllib, http.client
multiprocessing, threading, signal, gc
code, codeop, pty

The following calls are blocked:

eval(), exec(), compile(), __import__(), getattr() with dangerous names

Also blocked: ELF/Mach-O/PE binaries, symlinks, path traversal.
Use pathlib instead of os for file operations. Use json instead of yaml for config files.
Creating Your Zip
run.py must be at the root of the zip — not inside a subfolder. This is the most common submission error.
Linux / macOS (Terminal):
cd my_submission/
zip -r ../submission.zip . -x ".*" "__MACOSX/*"
Windows (PowerShell):
cd my_submission
Compress-Archive -Path .\* -DestinationPath ..\submission.zip
Do not right-click a folder and use "Compress" (macOS) or "Send to → Compressed folder" (Windows) — both nest files inside a subfolder.
Verify your zip:
unzip -l submission.zip | head -10
You should see run.py directly — not my_submission/run.py.


================================================================================================ SCORING ================================================================================================

NorgesGruppen Data: Scoring
Hybrid Scoring
Your final score combines detection and classification:
Score = 0.7 × detection_mAP + 0.3 × classification_mAP

Both components use mAP@0.5 (Mean Average Precision at IoU threshold 0.5).
Detection mAP (70% of score)
Measures whether you found the products, ignoring category:

Each prediction is matched to the closest ground truth box
A prediction is a true positive if IoU ≥ 0.5 (category is ignored)
This rewards accurate bounding box localization

Classification mAP (30% of score)
Measures whether you identified the correct product:

A prediction is a true positive if IoU ≥ 0.5 AND the category_id matches the ground truth
356 product categories (IDs 0-355) from the training data annotations.json

Detection-Only Submissions
If you set category_id: 0 for all predictions, you can score up to 0.70 (70%) from the detection component alone. Adding correct product identification unlocks the remaining 30%.

Score range: 0.0 (worst) to 1.0 (perfect)

Submission Limits



Limit
Value




Submissions in-flight
2 per team


Submissions per day
3 per team


Infrastructure failure freebies
2 per day (don't count against your 3)



Limits reset at midnight UTC. If you hit an infrastructure error (our fault), it doesn't count against your daily limit — up to 2 per day. After that, infrastructure failures consume a regular submission slot.
Leaderboard
The public leaderboard shows scores from the public test set. The final ranking uses the private test set which is never revealed to participants.
Select for Final Evaluation
By default, your best-scoring submission is used for the final private evaluation. You can override this by clicking Select for final on any completed submission in your submission history. This lets you choose a submission you trust, even if it's not your highest public score. You can change your selection at any time before the competition ends.

================================================================================================ EXAMPLES ================================================================================================

NorgesGruppen Data: Examples & Tips
Random Baseline
Minimal run.py that generates random predictions (use to verify your setup):
import argparse
import json
import random
from pathlib import Path

def main():
parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

    predictions = []
    for img in sorted(Path(args.input).iterdir()):
        if img.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        image_id = int(img.stem.split("_")[-1])
        for _ in range(random.randint(5, 20)):
            predictions.append({
                "image_id": image_id,
                "category_id": random.randint(0, 356),
                "bbox": [
                    round(random.uniform(0, 1500), 1),
                    round(random.uniform(0, 800), 1),
                    round(random.uniform(20, 200), 1),
                    round(random.uniform(20, 200), 1),
                ],
                "score": round(random.uniform(0.01, 1.0), 3),
            })
 
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(predictions, f)

if __name__ == "__main__":
main()
YOLOv8 Example
Using YOLOv8n with GPU auto-detection. Important: The pretrained COCO model outputs COCO class IDs (0-79), not product IDs (0-355). For correct product classification, fine-tune on the competition training data with nc=357. Detection-only submissions (wrong category_ids) still score up to 70%.
import argparse
import json
from pathlib import Path
import torch
from ultralytics import YOLO

def main():
parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = YOLO("yolov8n.pt")
    predictions = []
 
    for img in sorted(Path(args.input).iterdir()):
        if img.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        image_id = int(img.stem.split("_")[-1])
        results = model(str(img), device=device, verbose=False)
        for r in results:
            if r.boxes is None:
                continue
            for i in range(len(r.boxes)):
                x1, y1, x2, y2 = r.boxes.xyxy[i].tolist()
                predictions.append({
                    "image_id": image_id,
                    "category_id": int(r.boxes.cls[i].item()),
                    "bbox": [round(x1, 1), round(y1, 1), round(x2 - x1, 1), round(y2 - y1, 1)],
                    "score": round(float(r.boxes.conf[i].item()), 3),
                })
 
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(predictions, f)

if __name__ == "__main__":
main()
Include yolov8n.pt in your zip. This pretrained COCO model serves as a baseline — fine-tune on the competition training data for better results. With GPU available, larger models like YOLOv8m/l/x are also feasible within the timeout.
ONNX Inference Example
ONNX works with any model framework. Use CUDAExecutionProvider for GPU acceleration:
Export (on your training machine):
# From ultralytics:
from ultralytics import YOLO
model = YOLO("best.pt")
model.export(format="onnx", imgsz=640, opset=17)

# From any PyTorch model:
import torch
model = ...  # your trained model
dummy = torch.randn(1, 3, 640, 640)
torch.onnx.export(model, dummy, "model.onnx", opset_version=17)
Inference (in your run.py):
import argparse
import json
import numpy as np
from pathlib import Path
from PIL import Image
import onnxruntime as ort

def main():
parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

    session = ort.InferenceSession("model.onnx", providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    predictions = []
 
    for img_path in sorted(Path(args.input).iterdir()):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        image_id = int(img_path.stem.split("_")[-1])
 
        img = Image.open(img_path).convert("RGB").resize((640, 640))
        arr = np.array(img).astype(np.float32) / 255.0
        arr = np.transpose(arr, (2, 0, 1))[np.newaxis, ...]
 
        outputs = session.run(None, {input_name: arr})
        # Process outputs based on your model's output format
        # ...
 
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(predictions, f)

if __name__ == "__main__":
main()
Common Errors



Error
Fix




run.py not found at zip root
Zip the contents, not the folder. See "Creating Your Zip" in submission docs.


Disallowed file type: __MACOSX/...
macOS Finder resource forks. Use terminal: zip -r ../sub.zip . -x ".*" "__MACOSX/*"


Disallowed file type: .bin
Rename .bin → .pt (same format) or convert to .safetensors


Security scan found violations
Remove imports of subprocess, socket, os, etc. Use pathlib instead.


No predictions.json in output
Make sure run.py writes to the --output path


Timed out after 300s
Ensure GPU is used (model.to("cuda")), or use a smaller model


Exit code 137
Out of memory (8 GB limit). Reduce batch size or use FP16


Exit code 139
Segfault — likely model weight version mismatch. Re-export with matching package version or use ONNX.


ModuleNotFoundError
Package not in sandbox. Export model to ONNX or include model code in your .py files.


KeyError / RuntimeError on model load
Version mismatch. Pin exact sandbox versions or export to ONNX.



Tips

Start with the random baseline to verify your setup works
GPU is available — larger models (YOLOv8m/l/x, custom transformers) are feasible within the 300s timeout
Use torch.cuda.is_available() to write code that works both locally (CPU) and on the server (GPU)
FP16 quantization is recommended — smaller weights, faster GPU inference
ONNX with CUDAExecutionProvider gives good GPU performance for any framework
Process images one at a time to stay within memory limits
Use torch.no_grad() during inference
Test your code locally before uploading
You don't need all sandbox packages for training — only match what you use
