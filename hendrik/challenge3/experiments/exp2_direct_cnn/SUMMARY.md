# Experiment 2: Direct Small U-Net — Summary

## Best LOO Score: 85.1 (baseline: 82.0, live system: 79.3)

## Architecture
- Small U-Net: encoder [32, 64, 128], decoder [64, 32], 3 levels
- Residual skip connections in ConvBlocks, GroupNorm, SiLU
- Dropout2d(0.1) for regularization
- ~130K params
- Input: 30 channels (8 terrain one-hot + 7 neighbor counts + 4 distance transforms + 6 densities + 3 hidden params + 2 coord channels)
- Output: 40x40x6 softmax probabilities

## Training Config (best)
- 120 epochs, no val split (all train data used)
- AdamW lr=1e-3, weight_decay=1e-2
- CosineAnnealingLR
- D4 augmentation (8x) at train time
- Mixup augmentation (beta=0.4)
- Gradient clipping (max_norm=1.0)
- TTA (D4) at test time
- Static overrides: ocean -> P(empty)=1, mountain -> P(mountain)=1
- Probability floor at 0.01, renormalize

## Key Results
| Experiment | LOO Score | Time |
|---|---|---|
| Baseline U-Net (no augmentation tricks) | 83.8 | 268s |
| + TTA | 84.1 | 264s |
| + residual/dropout/coords | 84.1 | 365s |
| No val split, 80 epochs, all train data | 84.9 | 530s |
| + 120 epochs + mixup | 84.9 | 530s |
| 2-model ensemble (same score, 3x slower) | 85.1 | 1498s |

## Per-Round Comparison (CNN LOO vs Live System)
Strong rounds: R4 (89.2), R8 (90.4), R9 (90.8), R13 (89.6), R15 (89.8)
Weak rounds: R7 (75.2), R12 (68.0) — these drag the mean down

## CRITICAL LIMITATION
**The hidden params (ss, st, pa) are derived from ground truth during LOO eval.**
At live inference, we do NOT have ground truth. We have:
- `observed_probs` (40x40x6) — from query responses
- `n_observations` (40x40) — observation counts per cell
- `query_grids` — the query grids used
- `settlement_stats` — mean population, food, wealth, defense, factions, etc.

**None of these are used by the current model.** This is the biggest opportunity:
1. Derive hidden params from `observed_probs` + `settlement_stats` instead of GT
2. Feed `observed_probs` directly as additional input channels to the CNN
3. Use `n_observations` as confidence weighting

## What Worked
- D4 augmentation (train + TTA at test) — consistent +0.3-0.5
- Residual connections + dropout — helped weak rounds (R7, R12, R14)
- Using all training data (no val split) — +0.8 vs holding out val round
- Mixup augmentation — slight regularization benefit
- Coordinate channels — small but consistent help

## What Didn't Help
- 2-model ensemble: same score, 3x training time
- Mixed loss (weighted + unweighted KL): no improvement
- Lower learning rate (5e-4): no improvement
- Terrain-type prior blending: testing in progress

## Next Steps
1. **Use observed_probs + settlement_stats at inference** (biggest potential gain)
2. Feed observed_probs as extra CNN input channels
3. Investigate R7 and R12 — what makes them hard?
4. Try deeper bottleneck or attention at bottleneck
5. Deploy to solve.py once inference-time params are handled
