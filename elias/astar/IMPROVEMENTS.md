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

### 1. Enable observation blending (~+1.9 pts avg, done)

Observations are now blended into predictions with sub-linear scaling to avoid drowning the prior.

- [x] Set `OBS_WEIGHT` to a non-zero value — set to 0.5
- [x] Sweep observation weight values in offline backtest across all rounds — 0.5 best tradeoff (1.0 hurts R4 by -5)
- [x] Verify it helps on high-expansion rounds (R2, R5, R6) without hurting low-expansion (R3) — R3 +3.5, R7 +7.2, R4 -1.5
- [x] Tune `MIN_OBS_TO_BLEND` — lowered from 3 to 1 (max 2 obs/cell with 50 budget, so 3 was never triggered)
- [x] Added sub-linear scaling: `obs_weight * sqrt(n_obs)` to prevent noise from dominating
- [x] `PRIOR_WEIGHT` raised from 1.0 to 4.0 to buffer against stochastic observation noise

### 2. Warm/cold round classification (~+2.1 pts avg, done)

Separate prior tables for warm and cold rounds, selected by observed expansion rate.

- [x] Classify round using expansion rate threshold (< 0.05 = cold, >= 0.05 = warm)
- [x] Trained `contextual_priors_warm.json` from R1,R2,R4,R5,R6,R7 GT
- [x] Trained `contextual_priors_cold.json` from R3 GT
- [x] `classify_round_warmth()` selects prior table in `run_observation_phases()`
- [x] Backtest: R3 +3.1 (75.0), R6 +3.8 (81.4), R1 +1.3 (86.0), R7 +2.4 (69.0), R4 -0.1 (90.1)

### 3. Full-coverage query strategy (~+3-10 pts)

**Critical flaw in current approach:** `find_dynamic_viewports()` only targets cells with initial terrain `in (1, 2, 3)` — settlements, ports, ruins. That's ~5-15 cells per map. But **93.4% of the scoring weight** comes from plains (65.6%) and forest (27.8%) cells near settlements that can change during the simulation. These are never directly targeted by the current viewport placement.

The greedy set cover uses only 3-6 viewports per seed, leaving 20-35 queries for Phase 2 repeat observations. But repeat observations have steep diminishing returns (2nd obs worth 1/3 of 1st, 3rd worth 1/6). One new observation on an unseen plains cell is **3× more valuable** than a repeat on a settlement cell.

**Fix:** Replace with fixed 3×3 tiling, viewport corners at `{0, 13, 25} × {0, 13, 25}`:
- 9 viewports per seed × 5 seeds = 45 queries
- Covers **every land cell** on the map (current: ~30-50% incidental coverage)
- 2-cell overlap between viewports = free extra observations
- 5 leftover queries for targeted high-entropy follow-up
- Also improves expansion rate estimation (observes ALL cells at dist 1-3, not just those near settlement-covering viewports)

```python
def build_full_coverage_tiling(map_w=40, map_h=40):
    origins = [0, 13, 25]  # 15-cell viewports: 0-14, 13-27, 25-39
    return [(x, y) for y in origins for x in origins]
```

- [x] Implement full-coverage tiling via `build_tiling()` with evenly-spaced origins `{0, 13, 25}`
- [x] Replace `find_dynamic_viewports()` with `build_tiling()` in `main()` and `backtest_full_pipeline()`
- [x] Update `run_observation_phases()` to use tiling viewports per seed
- [ ] Backtest `--backtest-full` across all rounds to measure improvement
- [ ] Decide Phase 2 strategy for the 5 leftover queries (highest-entropy seed? frontier cells?)

### 4. Simulator safety net (~+5-8 pts on bad rounds)

The simulator actively hurts on rounds where `DEFAULT_PARAMS` don't match hidden parameters (R3: -8.1 pts, R4: -2.8 pts). When the sim is wrong, it pulls the blend away from the better prior.

- [ ] Compare sim output to observations after Phase 1 (e.g. argmax agreement per observed cell)
- [ ] If sim diverges significantly from observations, drop `SIM_WEIGHT` to 0 for that round
- [ ] Backtest on R3 and R4 to confirm improvement

### 5. More robust expansion rate estimation (~+3-5 pts on R3)

Each API query returns one stochastic sample. With low expansion rounds (R3 ~1%), a single spurious settlement observation can inflate the estimate by 10x.

- [ ] Use Bayesian updating with a prior (e.g. Beta distribution centered on 0.10) instead of raw ratios
- [ ] Weight samples by number of observations per cell
- [ ] Add confidence interval — when uncertain, bias toward moderate expansion rate
- [ ] Backtest specifically on R3 to verify stability

### 6. Per-round simulator calibration (~+3-8 pts)

Use settlement stats from API observations (population, food, wealth, defense) to tune `DEFAULT_PARAMS` before running Monte Carlo.

- [ ] Extract settlement stats from simulate API responses (already logged in `settlements` field)
- [ ] Map observed stats to parameter adjustments (high food → increase `base_food_production`, many collapses → increase `collapse_chance_base`)
- [ ] Backtest calibrated vs uncalibrated sim across all rounds

### 7. Increase observation weight (~+3-5 pts)

Once blending is enabled (#1), the per-observation weight likely needs tuning. Current blend for 1 observation: `obs=1.0, sim=0.5, prior=4.0` — prior is 73% of the blend, drowning out the actual signal.

- [ ] Increase per-observation weight from 1.0 to 3.0-5.0
- [ ] Sweep values in offline backtest across all rounds

### 8. Terrain-aware probability floors (~+1-2 pts)

- [ ] Port floor should be 0.001 for inland cells, 0.01 for coastal cells
- [ ] Mountain floor should be near-zero (0.0001) on non-mountain cells
- [ ] Sweep floor values in offline backtest

### 9. Smarter Phase 2 viewport selection (~+1-3 pts, conditional)

Phase 2 re-queries the same dynamic viewports from Phase 1. Repeat observations help estimate probabilities, but frontier cells at distance 4+ are almost always class 0 with low entropy (low scoring weight). Only explore frontiers when expansion rate appears high.

- [ ] If estimated expansion rate is high, generate frontier viewports for unobserved cells at distance 1-3
- [ ] Otherwise, repeat dynamic viewports for more observation samples
- [ ] Backtest both strategies across warm and cold rounds

### 10. Inconsistent distance metric (low priority)

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
