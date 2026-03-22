# Experiment 2: Direct Small U-Net

## Goal
Replace LightGBM entirely with a small U-Net that takes the grid + hidden params as input
and directly predicts the 40×40×6 probability distribution.

## Current baseline
- LightGBM per-cell: LOO ~82 with GT params
- Oracle: 93.9
- Main weakness: no spatial modeling, each cell predicted independently

## Architecture
- Input: terrain one-hot (8ch) + neighbor counts (7ch) + distances (4ch) + densities (6ch) + hidden params (3ch) = ~28 channels
- Small U-Net: encoder [32, 64, 128], decoder [64, 32], 3 levels
- Skip connections, GroupNorm, SiLU
- ~100-200K params. DO NOT go bigger.
- Output: 40×40×6 softmax

## Training
- Use `../eval_common.py` for data loading and LOO CV
- Loss: entropy-weighted KL divergence
- D4 augmentation (8×) — must transform grid + GT consistently
- Optimizer: AdamW, lr=1e-3, weight_decay=1e-2
- Scheduler: CosineAnnealing, 200 epochs
- Early stopping on val KL
- Device: GPU

## Static overrides (apply AFTER CNN output)
- Ocean cells (code 10): force P(empty)=1.0
- Mountain cells (code 5): force P(mountain)=1.0
- Floor at 0.01, renormalize

## Eval command
```bash
cd /home/hendrik/agentic-avengers-nm-ai/hendrik/challenge3/experiments/exp2_direct_cnn
python3 train_eval.py
```

## Rules
- Edit ONLY `train_eval.py` in this folder
- Report LOO CV mean score
- Baseline to beat: 82.0
- Target: 88+
- Must train full LOO CV in under 30 minutes
