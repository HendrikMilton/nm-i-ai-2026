# Astar Island — Improvement Plan

## Current Performance (v5 pipeline, 2026-03-20)

| Round | Sim+Prior | Prior-Only | Oracle Dist Prior | Notes |
|-------|-----------|------------|-------------------|-------|
| R1    | **79.9**  | 75.7       | ~84              | |
| R2    | **81.5**  | 80.0       | **84.1**          | |
| R3    | 47.3      | 55.4       | **89.3**          | Sim hurts by -8.1 pts |
| R4    | 89.1      | **91.9**   | 89.3              | Sim hurts by -2.8 pts |
| R5    | **73.7**  | 72.5       | **76.0**          | |
| R6    | **60.9**  | 57.4       | **78.9**          | +21.5 pts possible! |

**Top teams score 85-90 per round. We're at ~72 average. Target: 90+.**

## Done

- [x] Context-aware priors (terrain + n_forest_neighbors + is_coastal)
- [x] Per-class probability floors (mountain/port 0.001 vs 0.01)
- [x] Set cover viewport placement
- [x] Soft blending curve for observations
- [x] Phase 1+2 observation allocation by surprise
- [x] Monte Carlo simulator blended with observations + priors
- [x] Distance-to-settlement priors + observation-based expansion rate estimation

## Core Issues

### 1. Enable observation blending (~+5-10 pts)

`OBS_WEIGHT = 0.0` — we spend 50 queries per round and throw away all the data. Observations are direct samples from the true distribution and should be the highest-value signal we have.

- [ ] Set `OBS_WEIGHT` to a non-zero value (start with 0.5-1.0)
- [ ] Sweep observation weight values in offline backtest across all rounds
- [ ] Verify it helps on high-expansion rounds (R2, R5, R6) without hurting low-expansion (R3)
- [ ] Tune `MIN_OBS_TO_BLEND` — consider lowering from 3 to 2

### 2. Warm/cold round classification (~+10-15 pts on R3/R6)

The oracle gap is huge on cold rounds (R3: prior-only 55.4, oracle 89.3 = 34 pts gap). A single prior table trained on all rounds overestimates expansion on cold rounds by ~9x.

- [ ] Observe settlement stats (population, food) in Phase 1 to classify warm vs cold
- [ ] Train separate contextual prior tables on warm-only vs cold-only ground truth
- [ ] Select the matching prior table before generating predictions
- [ ] Backtest on R3 and R6 to confirm improvement

### 3. Simulator safety net (~+5-8 pts on bad rounds)

The simulator actively hurts on rounds where `DEFAULT_PARAMS` don't match hidden parameters (R3: -8.1 pts, R4: -2.8 pts). When the sim is wrong, it pulls the blend away from the better prior.

- [ ] Compare sim output to observations after Phase 1 (e.g. argmax agreement per observed cell)
- [ ] If sim diverges significantly from observations, drop `SIM_WEIGHT` to 0 for that round
- [ ] Backtest on R3 and R4 to confirm improvement

### 4. More robust expansion rate estimation (~+3-5 pts on R3)

Each API query returns one stochastic sample. With low expansion rounds (R3 ~1%), a single spurious settlement observation can inflate the estimate by 10x.

- [ ] Use Bayesian updating with a prior (e.g. Beta distribution centered on 0.10) instead of raw ratios
- [ ] Weight samples by number of observations per cell
- [ ] Add confidence interval — when uncertain, bias toward moderate expansion rate
- [ ] Backtest specifically on R3 to verify stability

### 5. Per-round simulator calibration (~+3-8 pts)

Use settlement stats from API observations (population, food, wealth, defense) to tune `DEFAULT_PARAMS` before running Monte Carlo.

- [ ] Extract settlement stats from simulate API responses (already logged in `settlements` field)
- [ ] Map observed stats to parameter adjustments (high food → increase `base_food_production`, many collapses → increase `collapse_chance_base`)
- [ ] Backtest calibrated vs uncalibrated sim across all rounds

### 6. Increase observation weight (~+3-5 pts)

Once blending is enabled (#1), the per-observation weight likely needs tuning. Current blend for 1 observation: `obs=1.0, sim=0.5, prior=4.0` — prior is 73% of the blend, drowning out the actual signal.

- [ ] Increase per-observation weight from 1.0 to 3.0-5.0
- [ ] Sweep values in offline backtest across all rounds

### 7. Terrain-aware probability floors (~+1-2 pts)

- [ ] Port floor should be 0.001 for inland cells, 0.01 for coastal cells
- [ ] Mountain floor should be near-zero (0.0001) on non-mountain cells
- [ ] Sweep floor values in offline backtest

### 8. Smarter Phase 2 viewport selection (~+1-3 pts, conditional)

Phase 2 re-queries the same dynamic viewports from Phase 1. Repeat observations help estimate probabilities, but frontier cells at distance 4+ are almost always class 0 with low entropy (low scoring weight). Only explore frontiers when expansion rate appears high.

- [ ] If estimated expansion rate is high, generate frontier viewports for unobserved cells at distance 1-3
- [ ] Otherwise, repeat dynamic viewports for more observation samples
- [ ] Backtest both strategies across warm and cold rounds

### 9. Inconsistent distance metric (low priority)

`simulator.py:129` uses Euclidean distance, `run.py:115` uses Chebyshev distance (BFS 8-connected). Only matters if sim blend is enabled — currently `SIM_WEIGHT = 0.0` so this has zero impact.

- [ ] Determine which distance metric the real game uses (check game rules / API docs)
- [ ] Align simulator to use the same metric
- [ ] Backtest before and after to measure impact

## Scoring Formula Reference

```
weighted_kl = sum(entropy(cell) * KL(gt, pred)) / sum(entropy(cell))
score = max(0, min(100, 100 * exp(-3 * weighted_kl)))
```

- Plains: 65.6% of entropy weight (most cells, moderate uncertainty)
- Forest: 27.8% of entropy weight
- Settlement: 6.6% of entropy weight
- The exponential means reducing weighted_kl from 0.25 → 0.15 = ~20 points

## Key Files

- `astar/run.py` — Core pipeline: observations + simulator + priors → predictions
- `astar/offline/simulator.py` — Monte Carlo simulator
- `astar/offline/run_local.py` — Offline backtesting (shares code with run.py)
- `astar/offline/score.py` — Local scoring
- `astar/contextual_priors.json` — Learned prior lookup table
- `astar/utils.py` — API helpers, floor_and_normalize
