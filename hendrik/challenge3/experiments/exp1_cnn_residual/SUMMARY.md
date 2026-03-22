# Experiment 1: CNN Residual on GBM — Summary

## Goal
Add a small CNN that refines LightGBM per-cell predictions by learning spatial patterns.
GBM treats cells independently; CNN adds spatial coherence.

## Results

### v1 (baseline CNN): LOO Mean = 82.5
- Architecture: 3 conv layers [32, 64, 32], 42K params
- Input: GBM probs (6ch) + terrain one-hot (8ch) + hidden params (3ch) = 17ch
- No augmentation, no TTA
- Marginal improvement over GBM-only (~82.0)

### v2 (augmentation + TTA): LOO Mean = 84.0 (BEST)
- Architecture: 2 ResidualBlocks(48) + dilated conv(rate=2), 115K params
- Input: GBM probs (6ch) + terrain (8ch) + hidden (3ch) + spatial features (8ch) = 25ch
- 8x data augmentation (rotations + flips)
- 6-transform test-time augmentation
- Dropout2d(0.1), AdamW, cosine LR schedule
- Post-hoc blend: 70% CNN + 30% GBM
- **+2.0 points over GBM-only baseline**

Per-round scores (v2):
```
R1:84.7  R2:86.0  R3:85.6  R4:89.6  R5:81.8  R6:80.9  R7:69.3
R8:89.3  R9:89.1  R10:86.7 R11:87.9 R12:71.7 R13:88.9 R14:76.7
R15:90.2 R16:81.4 R17:88.6 R18:77.7 R19:88.4 R20:83.1 R21:86.5
```

### v3 (U-Net, logit-residual, 44ch): Partial — abandoned
- 285K params (over 200K limit), ~107s/fold (too slow)
- No improvement over v2 in first 4 folds
- Abandoned after R4

### v3b (logit-residual, 32ch): Partial — 9/21 folds
- CNN learns corrections to GBM log-probabilities (head zero-initialized)
- Multi-scale context: dilated conv at rate 2 and 4
- 139K params, 32 input channels
- Partial results (9 folds): tracking similar to v2, slight improvement on some rounds

## Key Findings
1. CNN adds ~2 points over GBM-only (82→84 LOO mean)
2. Augmentation is critical — 8x data expansion was the biggest single improvement
3. TTA (test-time augmentation) helps ~0.5 points
4. Residual logit learning (v3b) didn't clearly beat direct prediction (v2)
5. Weak rounds R7 (69) and R12 (72) dominate error — these seem fundamentally harder

## Gap to Live Scores
LOO CV uses **ground-truth hidden params** — live uses estimated params from queries.
Live scores are ~5-8 points lower than LOO CV scores (e.g. R21: live 84.8 vs LOO 86.5).
The biggest live wins would come from better parameter estimation, not better ML models.

## NOT Deployed
This experiment was NOT integrated into solve.py. To deploy:
1. Add settlement_stats features (solve.py has 35 features, experiment has 28)
2. Train GBM + CNN on ALL rounds (not LOO)
3. Save CNN weights alongside GBM checkpoints
4. Update solve.py predict_grid() to run CNN refinement after GBM

## Files
- `train_eval.py` — full experiment code (GBM + CNN training, LOO CV)
- `program.md` — experiment spec
- `run.log` — v1 full results (not committed)
- `run_v2.log` — v2 full results (not committed)
- `run_v3b.log` — v3b partial results (not committed)
