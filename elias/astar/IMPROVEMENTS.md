# Astar Island — Improvement Plan

## Current Performance Baseline

| Round | Prior-Only | Best Sim Blend | Delta |
|-------|-----------|----------------|-------|
| R1    | 66.4      | 72.5 (sw1_pw4) | +6.1  |
| R2    | 69.5      | 74.7 (sw1_pw4) | +5.2  |
| R3    | 54.9      | 53.1 (sw0.1)   | -1.8  |
| R4    | 85.4      | 85.6 (sw0.1)   | +0.2  |
| R5    | 63.8      | 67.1 (sw0.5)   | +3.3  |

Online submissions: R3=0.26 (v1), R5=25.0 (v2). Both used flawed strategies (v1: too few observations; v2: cross-seed averaging destroyed seeds 2-4).

## Scoring Mechanics (from GAME_RULES.md)

```
weighted_kl = sum(entropy(cell) * KL(ground_truth, prediction)) / sum(entropy(cell))
score = max(0, min(100, 100 * exp(-3 * weighted_kl)))
```

- Only dynamic/uncertain cells contribute (weighted by their entropy)
- Never assign 0 probability to any class (floor at 0.01)
- The exponential makes small KL reductions worth large score gains: reducing weighted_kl from 0.25→0.15 is ~20 points

## Key Problems in Current System

1. **Priors are terrain-global averages** — `TERRAIN_PRIORS` in `run.py` maps one terrain code to one probability vector for ALL cells of that type. Ignores spatial context (neighbor terrain, coastal proximity, faction).
2. **Simulator hurts on some rounds** — R3 consistently gets worse with any sim_weight > 0. The simulator's DEFAULT_PARAMS don't match R3's hidden parameters.
3. **Query planning uses seed 0's grid for all seeds** — Each seed has a different initial map but viewports are computed from seed 0 only.
4. **Budget split is even across seeds** — No prioritization of seeds with higher uncertainty.
5. **Fixed blending weights** — `prior_weight=3.0` in v3 blending regardless of terrain type or observation quality.

---

## Improvement 1: Context-Aware Priors

**Expected gain: +5-15 points across all rounds**

### Problem
A settlement surrounded by 3 forests (high food → survives winter → stays class 1) gets the same prior as one with 0 forests (starves → collapses to ruin/empty). These cells have very different ground truth distributions, but our prior treats them identically. Since scoring weights by entropy, getting dynamic cells right is where nearly all points come from.

### Solution
Build a contextual prior lookup: `(initial_terrain, n_adjacent_forest, is_coastal) → probability_vector`, learned from R1-R5 ground truth.

### Implementation
1. **New file: `astar/offline/learn_priors.py`**
   - Fetch ground truth analysis for all completed rounds (R1-R5) via the API
   - For each cell in each seed: compute `(initial_terrain, n_forest_neighbors, n_ocean_neighbors)` from the initial grid
   - Group cells by these features, average the ground truth class distributions
   - Output a JSON lookup table to `astar/contextual_priors.json`
   - Key features (priority order): initial_terrain, n_adjacent_forest (0-8), is_coastal (bool), n_adjacent_settlements (0-8)

2. **Modify: `astar/run.py`**
   - Replace static `TERRAIN_PRIORS` dict with a function `get_contextual_prior(initial_grid, r, c)` that:
     - Counts neighbor terrain types for the cell
     - Looks up the contextual prior from the JSON table
     - Falls back to the global prior if the feature combination has too few training samples

### Why it works
A settlement with 3+ adjacent forests has ~45% chance of staying a settlement; one with 0 forests has ~15% chance. Currently both get 27%. Fixing this directly reduces KL divergence on the highest-entropy (most-weighted) cells.

### Validation
Backtest contextual priors (prior-only) on all R1-R5 rounds via `offline/score.py`. Must beat current prior-only average. Watch for overfitting if feature buckets have < 20 training samples.

---

## Improvement 2: Simulator Safety Net

**Expected gain: +3-5 points (prevents catastrophic regression on R3-type rounds)**

### Problem
On R3, every sim_weight > 0 makes the score worse. The simulator confidently predicts wrong outcomes, and the exponential scoring harshly penalizes confident wrong predictions. There's no mechanism to detect and avoid this.

### Solution
After running both simulator and API observations, check agreement. If the simulator disagrees with observations, fall back to priors-only.

### Implementation
1. **Modify: `astar/run.py` `counts_to_prediction_v3()`**
   - Add optional `sim_prediction` parameter
   - For each observed cell, compute argmax agreement between sim and observations
   - Per-seed reliability score = fraction of observed cells where sim argmax matches obs argmax
   - If reliability < 0.6: discard simulator entirely for that seed, use (obs + prior) only
   - If reliability >= 0.6: blend all three (sim + obs + prior)

2. **Modify: `astar/offline/run_local.py` `generate_prediction()`**
   - Add per-cell KL divergence check: if `KL(sim[r][c], obs[r][c]) > 0.5`, discard sim for that cell
   - This is the finer-grained version for offline backtesting

### Why it works
Acts as a safety net. On rounds where the sim is calibrated well (R1, R2, R5), reliability will be high and the sim gets used. On R3-type rounds, reliability drops below threshold and the system falls back to the safe prior-only baseline (54.9 instead of 46.7).

---

## Improvement 3: Per-Round Simulator Calibration

**Expected gain: +3-8 points on rounds where sim is useful**

### Problem
`DEFAULT_PARAMS` in `simulator.py` are static guesses. The API's simulate responses include settlement stats (population, food, wealth, defense). These directly reveal the hidden simulation parameters but are currently ignored.

### Solution
Spend 2-3 early queries extracting settlement stats, then calibrate key simulator params before running Monte Carlo.

### Implementation
1. **Modify: `astar/offline/simulator.py`**
   - Add `calibrate_params(observed_settlements) → dict`
   - Key calibrations:
     - `avg_food > 1.5` → increase `base_food_production`, decrease `winter_food_loss_base`
     - `avg_food < 0.5` → opposite
     - `fraction_with_ports > 0.3` → increase `port_development_chance`
     - `fraction_collapsed > 0.4` → increase `collapse_chance_base`, `winter_severity_mean`

2. **Modify: `astar/run.py` `main()`**
   - After fetching round data, spend 2-3 queries on seed 0 observing viewports with settlements
   - Extract settlement stats from the simulate response's `settlements` field
   - Call `calibrate_params()` with observed stats
   - Use calibrated params for all seeds (hidden params are shared across seeds within a round)

### Why it works
The R3 regression is almost certainly caused by the simulator's default params being wrong for that round's hidden parameters. If R3 has unusually harsh winters, calibrating `winter_severity_mean` from observed food levels would fix the gross miscalibration.

---

## Improvement 4: Per-Seed Viewport Planning

**Expected gain: +2-5 points**

### Problem
`find_dynamic_viewports()` in `run.py` line 354 uses seed 0's initial grid for all seeds. But each seed has a DIFFERENT initial map — dynamic cell locations differ across seeds.

### Solution
Compute dynamic viewports per seed using each seed's own grid.

### Implementation
Modify `astar/run.py` lines 354-397:
- Loop over all 5 seeds to compute `find_dynamic_viewports(seed_grids[s], map_w, map_h)` per seed
- Per-seed viewport counts feed into budget allocation
- Each seed's queries target its own dynamic viewports

### Why it works
If seed 2 has 12 dynamic viewports at different positions than seed 0's 6, querying seed 0's viewport positions for seed 2 may miss half the dynamic cells entirely.

---

## Improvement 5: Uncertainty-Weighted Budget Allocation

**Expected gain: +2-5 points**

### Problem
Budget is split evenly across observed seeds. Seeds with more uncertain dynamic cells would benefit more from observations.

### Solution
Allocate queries proportional to total prior entropy over dynamic cells per seed.

### Implementation
Modify `astar/run.py` lines 354-397:
```python
seed_uncertainty = {}
for s in range(N_SEEDS):
    grid = seed_grids[s]
    unc = sum(entropy(get_contextual_prior(grid, r, c))
              for r in range(map_h) for c in range(map_w)
              if grid[r][c] in (1, 2, 3))
    seed_uncertainty[s] = unc

total_unc = sum(seed_uncertainty.values())
for s in range(N_SEEDS):
    budget_per_seed[s] = max(min_per_seed, int(total_budget * seed_uncertainty[s] / total_unc))
```

### Why it works
Seeds with mostly predictable terrain (coastal forests → stable settlements) need fewer observations. Seeds with inland settlements in harsh terrain benefit more from repeat observations to build reliable empirical distributions.

---

## Implementation Priority

| # | Improvement | Gain | Effort | Risk |
|---|-----------|------|--------|------|
| 1 | Context-aware priors | +5-15 | Medium | Low (backtest validates) |
| 2 | Sim safety net | +3-5 | Low | Very low (fallback to priors) |
| 3 | Per-round sim calibration | +3-8 | Medium | Medium (could overfit) |
| 4 | Per-seed viewport planning | +2-5 | Low | Very low |
| 5 | Uncertainty-weighted budget | +2-5 | Low | Very low |

**Do improvements 1+2 first** — they address the two biggest systematic failures (coarse priors and simulator regression). Combined expected gain: +8-20 points.

## Key Files

- `astar/run.py` — Core pipeline, priors, blending, budget allocation
- `astar/offline/simulator.py` — Monte Carlo simulator with DEFAULT_PARAMS
- `astar/offline/run_local.py` — Offline backtesting and blended predictions
- `astar/offline/score.py` — Scoring implementation for validation
- `astar/offline/sweep.py` — Parameter grid search
- `astar/GAME_RULES.md` — Full game rules and scoring formula
