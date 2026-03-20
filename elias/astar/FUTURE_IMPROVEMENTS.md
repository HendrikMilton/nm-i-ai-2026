# Astar Island — Future Improvements

New findings from deep research (ASTAR_DEEP_RESEARCH.md) that are **not already covered** in IMPROVEMENTS.md or implemented in the code.

Sources: mathematical research on KL-optimal estimation, optimal probability pooling, and query allocation theory.

---

## Tier 1 — High Impact, Low Effort

### 1. KT-estimator replaces flat probability floors (+1-3 pts, 20 min)

**What:** The Krichevsky-Trofimov estimator (α=0.5) is **proven minimax optimal for KL divergence** — our exact scoring metric. Current `floor_and_normalize()` uses a fixed 0.01 floor regardless of how many observations a cell has.

```python
# KT-estimator: adaptive floor based on observation count
q(c) = (n_c + 0.5) / (N + 3.0)    # K=6 classes
```

| Observations (N) | KT adaptive floor | Our fixed 0.01 |
|---|---|---|
| 0 (unobserved) | 0.167 | 0.01 |
| 5 | 0.063 | 0.01 |
| 10 | 0.038 | 0.01 |
| 30 | 0.015 | 0.01 |

Our fixed 0.01 is **too low** for cells with few observations (which is nearly all dynamic cells). KT gives stronger smoothing when data is sparse — exactly when we need it.

**How:** Replace `floor_and_normalize()` in `utils.py`. Apply a small uniform mixture on top for safety:
```python
q_final = 0.97 * q_kt + 0.03 * [1/6]*6
q_final = clip(q_final, 0.005, 0.995)
q_final /= sum(q_final)
```

**Differs from IMPROVEMENTS.md #7** which only suggests terrain-aware floor values. This is a fundamentally different approach — adaptive floors based on observation count, with mathematical optimality guarantees.

**File:** `utils.py` (replace `floor_and_normalize`)

---

### 2. Float64 in submission pipeline (edge-case safety, 5 min)

**What:** Float32 lacks precision in log computations near zero. Since scoring uses `log(p/q)`, rounding errors in float32 can cause small but avoidable KL penalties.

**How:** Ensure all probability arrays use float64 before the final floor+normalize+submit step.

**File:** `run.py` (in `generate_prediction` and `floor_and_normalize`)

---

### 3. Fixed 3×3 tiling as query baseline (+0-2 pts, 30 min)

**What:** Submodularity theory (Krause et al., 2008) confirms uniform allocation is near-optimal. A fixed 3×3 tiling with viewport corners at `{0, 13, 25} × {0, 13, 25}` gives:
- 9 viewports per seed × 5 seeds = 45 queries
- Full map coverage with 2-3 cells overlap between viewports (free extra observations)
- 5 queries left over for adaptive refinement

Current greedy set-cover only targets dynamic cells (settlements/ports/ruins). The 3×3 tiling covers ALL cells including plains/forest at the frontier, which is where 65.6% + 27.8% = 93.4% of scoring entropy weight comes from.

**Trade-off:** Set cover uses fewer queries per seed (~3-6 vs 9) leaving more for Phase 2 repeats. But the deep research shows repeat observations have sharply diminishing returns (2nd obs worth 1/3 of 1st, 3rd worth 1/6). Full coverage with 1 obs each is better than partial coverage with repeats.

**File:** `run.py` (add `build_fixed_tiling()`, compare against `find_dynamic_viewports()` in backtests)

---

## Tier 2 — High Impact, Moderate Effort

### 4. Regime-specific Dirichlet priors with Bayesian Model Averaging (+10-20 pts on outliers, 1-2 hrs)

**What:** Instead of a hard warm/cold threshold (IMPROVEMENTS.md #2), use Dirichlet-Multinomial conjugacy for mathematically proper regime priors, and **soft-blend** between regimes using Bayesian Model Averaging.

```python
# Build regime-specific priors from ground truth
alpha_expansion[y, x, class] += count   # from warm rounds (R1, R2, R4, R5)
alpha_collapse[y, x, class] += count    # from cold rounds (R3)

# Prediction = Dirichlet posterior mean
pred_warm = alpha_expansion / alpha_expansion.sum(axis=-1)
pred_cold = alpha_collapse / alpha_collapse.sum(axis=-1)

# Soft blend using observation log-likelihood under each regime
p_final = w_warm * pred_warm + w_cold * pred_cold
```

**Advantage over hard threshold:** When early observations are ambiguous (moderate round), soft blending hedges between regimes instead of committing to one. This is strictly better than the binary classify-then-predict approach in IMPROVEMENTS.md #2.

**Files:** New `offline/build_regime_priors.py`, new JSON prior files, modify `run.py`

---

### 5. Importance-weighted ABC ensemble — connect Arian's LHS with observations (+3-8 pts, 1-2 hrs)

**What:** The simplest form of Approximate Bayesian Computation that bridges the two pipelines:

1. Run local simulator with M=500 LHS parameter settings (Arian already does step 1-2)
2. For each parameter set θ, compute per-cell class frequencies from stochastic runs
3. **NEW:** Weight each parameter set by how well it matches API observations:
   ```python
   for theta in parameter_settings:
       sim_freq = compute_frequencies(simulator_runs[theta], viewport_cells)
       obs_freq = compute_frequencies(api_observations, viewport_cells)
       discrepancy = sum_KL(obs_freq, sim_freq)
       weights[theta] = exp(-lambda * discrepancy)
   ```
4. Final prediction: weighted average across all parameter sets

**Effect:** Parameters that produce reality-like outcomes get high weight. Parameters that diverge get near-zero weight. Lets the data determine `winter_severity` instead of guessing.

**Differs from IMPROVEMENTS.md #5** (per-round calibration) which adjusts parameters heuristically based on stats. This is a principled Bayesian approach that considers ALL parameter sets simultaneously.

**Files:** New ensemble module, modify `run.py` to orchestrate LHS → observe → reweight → predict

---

### 6. Hausser-Strimmer optimal shrinkage replaces hardcoded prior_weight (+1-3 pts, 30 min)

**What:** Current blending uses `obs_weight * sqrt(n_obs)` with a fixed `PRIOR_WEIGHT=4.0`. Hausser-Strimmer (2009) gives a **closed-form optimal shrinkage** that adapts per-cell:

```python
def optimal_shrinkage(counts, prior):
    N = sum(counts)
    p_mle = [c/N for c in counts]
    V = (1.0 - sum(p**2 for p in p_mle)) / (N - 1)  # MLE variance
    D_sq = sum((p - q)**2 for p, q in zip(p_mle, prior))  # distance to prior
    lam = clip(V / (V + D_sq), 0, 1)
    return clip(lam * N / (1.0 - lam), 0.5, 50.0)  # effective prior weight
```

If observations match the prior → high prior weight. If they diverge → low prior weight. Adapts per-cell automatically.

**Differs from IMPROVEMENTS.md #6** which suggests sweeping fixed obs_weight values. This is an adaptive, per-cell, theoretically grounded approach.

**File:** `run.py` (modify `generate_prediction` blending logic)

---

## Tier 3 — Moderate Impact, More Effort

### 7. Distance transform features for richer priors (+2-5 pts, 1-2 hrs)

**What:** Replace the simple (terrain, n_forest_neighbors, is_coastal) feature set with `scipy.ndimage.distance_transform_edt`, giving distance from each cell to every terrain type. 18 features per cell in ~0.1ms.

Key features beyond what we currently have:
- **Distance to ocean** — predicts port formation probability (currently only binary is_coastal)
- **Distance to forest** — correlates with food availability and survival (currently only neighbor count, capped at 4)
- **Distance to mountain** — may correlate with defensibility

Can be used to build a richer prior model (e.g., small regression or lookup table with finer bins).

**File:** New feature extraction, modify contextual prior generation

---

### 8. Entropy-weighted query allocation — Neyman allocation (+1-3 pts, 1 hr)

**What:** Optimal query allocation follows the √-entropy rule. Number of observations per cell should be proportional to `√(entropy_weight)`.

Key insight: diminishing returns are steep:
- 2nd observation is worth 1/3 of 1st observation
- 3rd observation is worth 1/6 of 1st observation
- A 2nd obs on cell i is only better than a 1st obs on cell j if `entropy_weight_i > 3 × entropy_weight_j`

**Implication:** With 50 queries, ~40-50 unique cells should get exactly 1 observation each. Only cells with 3× median entropy weight should get repeat observations.

Current Phase 2 re-queries all dynamic viewports for the highest-surprise seed. This wastes queries on low-entropy cells that happen to be in the same viewport as high-entropy ones.

**File:** `run.py` (modify Phase 2 in `run_observation_phases`)

---

## Validated Design Decisions

These findings from the deep research **confirm** our current approach is correct:

- **Linear pooling is optimal for KL(true ‖ pred)** — our blending (weighted average) is mathematically correct. Log-linear pooling would be wrong for our scoring metric. (Abbas, 2009)
- **Scoring is robust against individual catastrophes** — one cell with KL=10 only changes score by ~1.9%. Systematic accuracy across all cells matters far more than perfecting individual cells. This validates focusing on prior quality over cell-level tuning.
- **Score 90+ requires better priors, not more observations** — the score-to-KL table shows 90 requires weighted_kl < 0.035, which needs ~71 obs/cell (impossible with 50 queries). Prior quality is the binding constraint.

---

## Score-to-KL Reference Table

| Target Score | Required weighted KL | What it takes |
|---|---|---|
| 95 | < 0.017 | ~146 obs/cell (unrealistic) |
| 90 | < 0.035 | Perfect priors + some observations |
| 80 | < 0.074 | Good priors + observations |
| 70 | < 0.119 | Prior-only on good rounds |
| 50 | < 0.231 | Prior-only on bad rounds |
