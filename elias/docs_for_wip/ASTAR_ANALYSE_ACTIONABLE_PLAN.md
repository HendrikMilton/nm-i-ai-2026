# Actionable Plan — Based on ASTAR_ANALYSE.md

**Status:** Current pipeline is v5 with distance-aware priors already implemented.
**Goal:** Go from ~72 avg backtest score to 85+ (top 10).

---

## What's Already Done (from the analysis recommendations)

The analysis was written before some v5 features were added. These are **already implemented**:

- [x] Distance-to-settlement priors (`get_distance_aware_prior()` in `run.py:191`)
- [x] Expansion rate estimation from observations (`estimate_expansion_rate()` in `run.py:145`)
- [x] Per-class probability floors in `floor_and_normalize()` (`utils.py`)
- [x] Greedy set cover viewport placement (`find_dynamic_viewports()`)
- [x] Phase 1+2 surprise-based query allocation (`run_observation_phases()`)
- [x] Per-seed grids (no cross-seed averaging)

---

## Tier 1 — Quick Wins (< 30 min each)

### 1.1 Default to `sim_weight=0` (prior-only mode)

**Why:** Backtest data shows the simulator with fixed params has **negative expected value**. It helps on R1/R2 (+2.7) but hurts on R3 (-7.8) and R4 (-2.5). Prior-only averages 71.7 vs 66.4 for sim-dominated.

**File:** `astar/run.py`
**Change:**
```python
# Line 31: Change from
SIM_WEIGHT = 0.5
# To
SIM_WEIGHT = 0.0
```

**Impact:** +5-10 points on bad-sim rounds, slight regression on good-sim rounds. Net positive.

**Backtest verification:** Run `python offline/run_local.py --backtest-all` with `SIM_WEIGHT=0.0` and compare.

---

### 1.2 Verify `floor_and_normalize()` runs on ALL output paths

**Why:** A single cell with P(class)=0 where ground truth > 0 causes KL divergence to explode. This was the root cause of R3's 0.26 score.

**Files:** `astar/run.py`, `astar/offline/run_local.py`
**Check:** Grep for all `submit()` calls and trace backward — every prediction must pass through `floor_and_normalize()` before submission. Currently `generate_prediction()` calls it at line 614, which is correct. Also verify `counts_to_prediction_v4()` output goes through it if used independently.

---

## Tier 2 — Warm/Cold Round Classification (1-2 hours)

### 2.1 Create warm/cold prior sets

**Why:** The single biggest remaining gap. Contextual priors are a static average across all rounds. On R3 (cold/harsh), P(settlement) should be ~0.03 but the prior says 0.274 — **9x too high**. Two prior sets would fix this.

**Files to create/modify:**
- `astar/contextual_priors_warm.json` — trained from R1, R2, R4, R5 ground truth
- `astar/contextual_priors_cold.json` — trained from R3 ground truth
- Script to generate these: use `get_analysis()` API to pull ground truth, compute per-(terrain, n_forest, is_coastal) distributions separately for warm vs cold rounds

**Steps:**
1. Write a script `astar/offline/build_priors.py` that:
   - Fetches ground truth for R1-R6 via `get_analysis(round_id, seed)`
   - Classifies rounds: R3 = cold, rest = warm (use settlement survival rate as metric)
   - Computes contextual prior tables for each group using the same (terrain, n_forest, is_coastal) key scheme
   - Saves as `contextual_priors_warm.json` and `contextual_priors_cold.json`
2. Also generate priors for **terrain 0 (Empty) and terrain 3 (Ruin)** which are currently missing from `contextual_priors.json` and fall back to coarse `TERRAIN_PRIORS`

**Expected gain:** +10-20 points on cold rounds (R3-type), +1-2 points on warm rounds from better terrain coverage.

### 2.2 Implement round classification using settlement stats

**Why:** Need to decide which prior set to use *before* spending the full query budget. The API `simulate` response includes settlement stats (population, food, alive) — this is currently logged but never used.

**File:** `astar/run.py`
**Changes:**

1. Add a new function `classify_round()`:
```python
def classify_round(round_id, seed_index, viewport, map_w, map_h):
    """Use 1-2 queries on seed 0 to classify the round as warm or cold.

    Indicators:
    - food > 2.0 and >50% settlements alive → WARM
    - food < 0.5 and <30% alive → COLD

    Returns: "warm" or "cold"
    """
    result = simulate(round_id, seed_index, viewport[0], viewport[1], VIEWPORT, VIEWPORT)
    settlements = result.get("settlements", [])

    if not settlements:
        return "warm"  # default

    alive_count = sum(1 for s in settlements if s.get("alive", False))
    alive_ratio = alive_count / len(settlements)
    avg_food = sum(s.get("food", 0) for s in settlements) / len(settlements)

    if avg_food < 0.5 and alive_ratio < 0.3:
        return "cold"
    return "warm"
```

2. In `main()`, call `classify_round()` with 1-2 queries before the main observation loop. Deduct from budget.

3. Load the appropriate prior set based on classification:
```python
if round_type == "cold":
    _CONTEXTUAL_PRIORS = load_cold_priors()
else:
    _CONTEXTUAL_PRIORS = load_warm_priors()
```

**Cost:** 1-2 queries (2-4% of budget)
**Expected gain:** +15-20 points on R3-type rounds by using correct priors

### 2.3 Use expansion rate as a secondary classifier

**Why:** The expansion rate estimated from Phase 1 observations already tells us about round severity. If expansion_rate < 0.03, it's likely a cold round. This can be combined with settlement stats for more robust classification.

**File:** `astar/run.py`
**Change:** After `run_observation_phases()` returns `avg_expansion`, add:
```python
# Cross-check: if expansion rate suggests cold round, switch priors
if avg_expansion < 0.03 and round_type == "warm":
    print("WARNING: Low expansion rate suggests cold round, switching priors")
    round_type = "cold"
    # Re-run predictions with cold priors
```

This provides a safety net — even if the initial classification is wrong, the expansion rate estimate from observations can correct it.

---

## Tier 3 — LHS Parameter Sampling for Simulator (2-3 hours)

### 3.1 Replace fixed simulator params with Latin Hypercube Sampling

**Why:** The analysis shows Arian's LHS approach is fundamentally better than fixed params. Fixed `winter_severity_mean=0.4` never produces R3-type outcomes. LHS over `[0.10, 0.70]` naturally covers the full range.

**File:** `astar/offline/simulator.py`
**Changes:**

1. Add LHS sampling function:
```python
def generate_lhs_params(n_samples=10, seed=42):
    """Generate n_samples parameter sets using Latin Hypercube Sampling.

    Key parameters to vary (from Arian's approach):
    - expansion_chance:      [0.02, 0.20]
    - raid_chance:           [0.05, 0.50]
    - winter_severity_mean:  [0.10, 0.70]  ← CRITICAL
    - trade_range:           [4, 12]
    - settlement_reclaim_chance: [0.03, 0.20]
    - ruin_forest_reclaim_chance: [0.02, 0.15]
    - longship_build_chance: [0.03, 0.25]
    - expansion_radius:      [2, 5]
    """
```

2. Modify `run_monte_carlo()` to accept multiple param sets:
```python
def run_monte_carlo(grid, settlements, n_sims=200, params=None,
                    base_seed=0, param_sets=None):
    """If param_sets is provided, distribute n_sims across all param sets."""
```

**File:** `astar/run.py`
**Change in `generate_prediction()`:** Pass `param_sets` from LHS instead of single `params`.

**Expected gain:** +2-5 points from broader parameter coverage, especially on outlier rounds.

### 3.2 Calibrate simulator from observed settlement stats

**Why:** Settlement stats (food, population, defense, alive) from the simulate API response are an unused signal. They can constrain which parameter sets are plausible.

**File:** `astar/run.py`
**Changes:**

1. In `observe_seed()`, collect settlement stats from each response (currently logged but discarded):
```python
# After getting result from simulate():
settlements_stats = result.get("settlements", [])
# Store for later calibration
```

2. Add `calibrate_params_from_stats()`:
```python
def calibrate_params_from_stats(settlement_stats):
    """Adjust LHS param ranges based on observed settlement statistics.

    - High avg food → narrow winter_severity to [0.1, 0.3]
    - Low avg food → narrow winter_severity to [0.4, 0.7]
    - Many dead settlements → increase collapse_chance range
    - Many expansions observed → increase expansion_chance range
    """
```

3. Use calibrated ranges in LHS sampling before running Monte Carlo.

**Expected gain:** +3-8 points by making simulator params match the actual round dynamics.

---

## Tier 4 — Fine-tuning (1-2 hours)

### 4.1 Increase `n_sims` (only if LHS is implemented)

**File:** `astar/run.py`
**Change:** `N_SIMS = 500` (from 200). Only worth doing after LHS is in place, otherwise more sims with wrong params just increases confidence in wrong answers.

### 4.2 Observation weight tuning

**Why:** API observations are ground-truth samples. Current blend gives 1 observation only 12% weight. Could be higher.

**File:** `astar/run.py`
**Change in `generate_prediction()`:** Try `obs_weight=2.0` or `3.0` instead of `1.0`. Backtest to verify.

### 4.3 Simulator safety net

**Why:** When simulator disagrees with observations, trust observations. Simple argmax agreement check.

**File:** `astar/run.py`
**Change in `generate_prediction()`:**
```python
# After Phase 1 observations, check sim vs obs agreement
# If >30% of observed cells have different argmax → set sim_weight=0 for this seed
```

---

## Implementation Order

| Priority | Change | Files | Expected Gain | Effort |
|----------|--------|-------|---------------|--------|
| **1** | Set `SIM_WEIGHT=0` | `run.py:31` | +3-5 avg | 5 min |
| **2** | Build warm/cold priors | new `offline/build_priors.py`, new JSON files | +10-20 on cold | 1 hr |
| **3** | Round classification | `run.py` (new function + main changes) | enables #2 | 30 min |
| **4** | LHS parameter sampling | `offline/simulator.py`, `run.py` | +2-5 avg | 2 hr |
| **5** | Calibrate sim from stats | `run.py` (observe_seed + new function) | +3-8 | 1.5 hr |
| **6** | Observation weight tuning | `run.py:571` | +1-3 | 15 min |
| **7** | Simulator safety net | `run.py` | +1-3 | 30 min |
| **8** | Increase n_sims | `run.py:33` | +1-2 | 5 min |

**Estimated total gain:** From ~72 avg to ~85-90 avg (top 5-10 territory).

---

## Verification Plan

After each change, run:
```bash
cd astar
python offline/run_local.py --backtest-all
```

Compare per-round and average scores against the baseline. Key rounds to watch:
- **R3:** Most sensitive to prior quality (cold round). Target: 70+ (from 52.8)
- **R4:** Should stay high (87+). Regression here means priors are worse.
- **R1/R2:** Should stay stable or improve slightly.

For round classification specifically, test by running `--backtest-full` which simulates the full query pipeline including classification.
