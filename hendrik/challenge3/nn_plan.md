# Challenge 3 — NN Prediction Model Plan

## Task
Build a small neural network that predicts 40x40x6 probability distributions for terrain outcomes after a 50-year Viking civilization simulation. Scored by entropy-weighted KL divergence: `score = max(0, min(100, 100 * exp(-3 * weighted_kl)))`. Higher is better.

## Current Baselines
| Approach | CV Mean Score |
|---|---|
| Uniform (1/6) | 4.8 |
| Empirical lookup table | 35.3 |
| Elias prior+obs engine | 76.2 |
| Actual submitted scores | 51.1 |

## Data
All in `/home/hendrik/Documents/agentic-avengers-nm-ai/hendrik/challenge3/round_data/`

12 rounds × 5 seeds = 60 samples. Each `round_XX.json` contains:
- `initial_grid`: 40x40 int array (terrain codes: 0,1,2,3,4,5,10,11)
- Per seed:
  - `ground_truth`: 40x40x6 float (target probability distribution)
  - `ground_truth_from_queries`: 40x40x6 float (empirical probs from live observations)
  - `n_observations`: 40x40 int (how many times each cell was observed, 0-2)
  - `observed_counts`: 40x40x6 int (raw observation counts per class)
- 9 of 12 rounds have query observations. 3 rounds (1, 2, 4, 6) have none.

### Terrain codes → 6 prediction classes
| Code | Terrain | Class |
|---|---|---|
| 10 | Ocean | 0 (Empty) |
| 11 | Plains | 0 (Empty) |
| 0 | Empty | 0 |
| 1 | Settlement | 1 |
| 2 | Port | 2 |
| 3 | Ruin | 3 |
| 4 | Forest | 4 |
| 5 | Mountain | 5 |

## Key Data Insights

### What the simulation does
Everything trends toward empty (class 0). Settlements survive only ~31% of the time. The simulation is fundamentally about "will settlements survive or die."

### Per-terrain stability (from overlapping query observations)
- Mountain: 100% deterministic
- Ocean: 98.3% static
- Plains: 82.1% stable
- Forest: 75.5% stable
- Settlement: 32.1% volatile
- Port: 16.6% very volatile
- Ruin: 5% almost never the same twice

### Critical seed difference
- **Seed 0**: Mountains are 100% static (P(mountain)=1.0 always)
- **Seeds 1-4**: Mountains dissolve (~80% become empty/forest)
- This holds across ALL rounds. **Must have separate behavior for seed 0 vs seeds 1-4.**

### Spatial autocorrelation
- P(settlement) has strong spatial autocorrelation: lag=1: 0.49-0.70, lag=2: 0.32-0.61
- P(forest) has near-zero spatial autocorrelation
- This means settlement outcomes are spatially clustered — **this is the main signal a conv net can capture that a lookup table misses**

### Feature importance (mutual information with P(settlement))
1. `n_ocean` (coast) — strongest predictor
2. `dist_to_settlement` — important but NN can't learn BFS, must precompute
3. `row/col` position — edge effects exist
4. Terrain code, neighbor counts — weak individually

## Architecture

### Small U-Net (keep under 200K params)
- 40x40 is tiny — 3 levels with channels [32, 64, 128] is plenty
- Receptive field of ~15 covers the spatial autocorrelation range (lag 5)
- No need for transformer/attention — pure convolutions

### Input channels (~17 total)
1. **One-hot initial terrain**: 8 channels (one per terrain code)
2. **Observed probabilities from queries**: 6 channels (ground_truth_from_queries, zeros if no observations)
3. **Observation mask**: 1 channel (n_observations > 0, float)
4. **Distance to nearest settlement**: 1 channel (precomputed BFS, normalized to [0,1])
5. **Coast mask**: 1 channel (binary, has ocean neighbor)

### Output
- 40x40x6 softmax probabilities

### Hardcoded overrides (applied AFTER NN output)
- Ocean cells (code 10): force P(empty)=1.0 — they never change
- Mountain cells for seed 0 only: force P(mountain)=1.0
- Floor all probabilities at 0.01, renormalize

### Loss function
Entropy-weighted KL divergence (matches competition scoring exactly):
```python
# KL(target || pred) weighted by target entropy per cell
target_safe = target.clamp(min=1e-8)
pred_log = F.log_softmax(logits, dim=1)
kl = (target_safe * (target_safe.log() - pred_log)).sum(dim=1)  # per cell
entropy = -(target_safe * target_safe.log()).sum(dim=1)  # per cell
weight = entropy / (entropy.sum() + 1e-8)
loss = (kl * weight).sum()
```

## Training

### Data split
- Leave-one-round-out cross-validation (train on 11 rounds, validate on 1)
- Report score per seed and mean per round

### Augmentation
- D4 symmetry: 8 transforms (4 rotations × 2 flips) → 60 × 8 = 480 training samples
- Must transform both input grid AND target consistently
- Note: distance-to-settlement and coast mask must be recomputed after rotation (or transform the precomputed features too)

### Hyperparameters (start with these)
- Optimizer: AdamW, lr=1e-3, weight_decay=1e-2
- Scheduler: CosineAnnealing, 200 epochs
- Batch size: 8
- Mixup alpha=0.3 (works well here — interpolating probability distributions stays valid)
- Dropout: 0.1 in conv blocks

### What NOT to do
- Don't build a huge model — 60 samples can't support millions of params
- Don't add transformer layers — unnecessary for 40x40
- Don't predict ocean/mountain cells — hardcode them
- Don't use the same prediction for all seeds — at minimum, handle seed 0 vs 1-4 differently for mountains

## Evaluation

Use the eval harness at `eval.py`:
```python
from eval import eval_predict_fn, score_prediction

def my_predict(initial_grid, seed_index, queries):
    # return 40x40x6 numpy array
    ...

results = eval_predict_fn(my_predict)
```

### Comparison targets
Run your model and compare against:
- Lookup table baseline: `python3 baseline_lookup.py` (CV mean: 35.3)
- Elias's engine scores ~76.2 mean
- Our actual submitted scores: 51.1 mean

## Files
- `eval.py` — scoring harness
- `baseline_lookup.py` — lookup table baseline
- `baseline_prior.py` — simple empirical prior baseline
- `analyze_transitions.py` — terrain transition analysis
- `analyze_deep.py` — deep data exploration
- `analyze_correlations.py` — correlation analysis
- `reverse_engineer.py` — simulation reverse engineering from observations
- `round_data/round_XX.json` — all round data with observations and ground truth
- `solve.py` — current CNN solution (overcomplicated, ignore architecture but reuse eval logic)

## Goal
Beat the lookup table (35.3) significantly. Target: 60+ mean score. Stretch: match Elias's 76.2.
