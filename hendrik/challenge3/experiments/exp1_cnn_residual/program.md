# Experiment 1: CNN Residual on top of GBM

## Goal
Add a tiny CNN that refines the LightGBM per-cell predictions by learning spatial patterns.
The GBM treats each cell independently. Settlements cluster spatially (lag-1 correlation 0.5-0.7).
A CNN can smooth the GBM's per-cell predictions to be spatially coherent.

## Current baseline
- LightGBM per-cell model: LOO CV ~82 with GT params, ~87 with obs params
- Oracle (GT + 0.01 floor): 93.9
- Error is spread across 500+ dynamic cells, 65% from plains, 31% from forest

## Architecture
- Input: GBM prediction (6ch) + terrain one-hot (8ch) + 3 hidden params = 17 channels
- 40×40 input, 40×40×6 output
- Tiny: 3 conv layers [32, 64, 32] with ReLU, final 1×1 conv to 6
- ~50K params max. DO NOT make it bigger.
- Output: softmax probabilities
- The CNN learns residual corrections to the GBM output

## Training
- Use `../eval_common.py` for data loading and LOO CV evaluation
- Loss: entropy-weighted KL divergence (matches competition scoring)
- Optimizer: Adam, lr=1e-3, cosine schedule
- Epochs: 100-200, early stopping on val loss
- Device: GPU (cuda)

## Eval command
```bash
cd /home/hendrik/agentic-avengers-nm-ai/hendrik/challenge3/experiments/exp1_cnn_residual
python3 train_eval.py
```

## Rules
- Edit ONLY `train_eval.py` in this folder
- Report LOO CV mean score after each experiment
- Current baseline to beat: 82.0 (GBM with default params on R16 holdout)
- Target: 88+
- Keep model under 200K params
- Must train in under 5 minutes on GPU
