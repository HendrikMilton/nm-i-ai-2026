# New Implementation — Best of Both Pipelines

## Philosophy

Take the **ABC parameter fitting** from v3 (the fundamental breakthrough) and combine it with the **smart query strategy + distance-aware priors** from run.py. Add the best ideas from the deep research docs.

The current pipeline (run.py) has strong priors but can't adapt to hidden params. v3 can fit params but wastes its query budget and ignores the prior system. The new pipeline should do both.

## Pipeline Overview

```
1. Observe     — Phase 1 tiling (45 queries) + smart Phase 2 (5 queries)
2. Classify    — Expansion rate + round archetype from observations
3. Fit params  — Pooled ABC across all 5 seeds (not per-seed)
4. Simulate    — Weighted MC with fitted params
5. Blend       — Distance-aware priors + MC + observations via Bayesian update
6. Submit      — KT-estimator floors, normalize, submit per seed
```

## Step 1: Observe (from run.py, improved)

Use the existing Phase 1 + Phase 2 system from run.py:

- **Phase 1:** 9 viewports × 5 seeds = 45 queries, full map coverage
- **Phase 2:** 5 remaining queries allocated based on expansion rate confidence

This is better than v3's approach because:
- v3 uses all 45 queries on observation and has no Phase 2 flexibility
- v3 with `n_sweeps>1` burns the entire budget on repeat observations (diminishing returns)
- run.py's Phase 2 can target high-value cells based on what Phase 1 revealed

**Phase 2 allocation** (from QUERY_IMPROVEMENTS.md):
- Compute expansion rate variance across seeds after Phase 1
- If variance is high → target distance 1-3 boundary cells to nail down expansion rate
- If variance is low → target highest-surprise seed's boundary cells

## Step 2: Classify Round (from run.py, keep as-is)

Use `classify_round_warmth()` with the expansion rate threshold (< 0.05 = cold).

- Selects warm or cold contextual prior table
- Expansion rate estimated from observations at distance 1-3 from settlements
- Pooled across all 5 seeds for stability

**Improvement:** Use Bayesian updating (Beta prior centered on 0.10) instead of raw ratio for expansion rate estimation. This prevents a single spurious settlement observation from inflating the estimate on cold rounds. From IMPROVEMENTS.md issue #5.

## Step 3: Fit Params — Pooled ABC (from v3, improved)

This is v3's core contribution. But with a critical change: **pool observations from all 5 seeds into one ABC fit** instead of running 5 independent fits.

Why: Hidden params are identical across seeds. 5 seeds × ~1400 non-ocean cells = ~7000 data points for fitting, vs ~1400 per seed. More data → better parameter estimates, especially on cold rounds where most cells look the same.

**Two-stage ABC:**

1. **Stage 1 — Fast filter (500 LHS candidates, 2-3 sims each)**
   - Score by match rate against observed cells across all 5 seeds
   - Keep top 50
   - Parallelized across CPU cores

2. **Stage 2 — Likelihood refinement (200 candidates, 50 MC each)**
   - Top 20 from Stage 1 + 180 perturbations
   - Score by log-likelihood of observations under MC distribution
   - Keep top 15

**Parameter ranges** (from v3, already tightened):
```
expansion_rate:      [0.05, 0.65]
conflict_prob:       [0.05, 0.55]
winter_severity:     [0.08, 0.75]
trade_range:         [3, 14]
ruin_reclaim_rate:   [0.08, 0.65]
forest_reclaim_rate: [0.01, 0.30]
longship_prob:       [0.04, 0.45]
longship_range:      [4, 17]
```

**Improvement over v3:** Use round classification from Step 2 to narrow ABC search space. If classified as cold, constrain `expansion_rate` to [0.01, 0.15] and `winter_severity` to [0.4, 0.75]. This makes ABC faster and more accurate on the rounds where it matters most (R3).

## Step 4: Simulate — Weighted MC (from v3)

Run MC using the top 15 fitted parameter sets, weighted by log-likelihood:

```
weights = softmax(log_likelihoods)
runs_per_param_set = weights × total_runs
```

- Total 500 runs distributed proportionally
- Better-fitting params get more runs
- Produces H×W×6 probability tensor per seed
- Parallelized with multiprocessing

**Per-seed simulation** (not pooled): Even though params are shared, each seed has a different map layout, so MC must run independently per seed.

## Step 5: Blend — Three-Signal Bayesian Update (new, combines both)

This is where both pipelines' strengths merge. Three layers, applied in sequence:

### Layer 1: Distance-aware contextual prior (from run.py)

Start with the distance-aware prior system — the single biggest improvement in the current pipeline (+5-15 pts):

```
prior = contextual_prior[terrain][n_forest][is_coastal]
target_settle = expansion_rate × dist_decay[distance_to_settlement]
```

Uses warm/cold prior table selected by round classification.

### Layer 2: Blend MC into prior (from v3, improved)

Blend the fitted MC prediction into the prior. Use the MC prediction's confidence as a guide:

```
blended = prior_weight × prior + mc_weight × mc_prediction
```

**Key difference from v3:** The prior here is distance-aware (not flat contextual), so the blend starts from a much better baseline. MC refines it rather than replacing it.

**Simulator safety net** (from run.py): If MC argmax disagrees with observations on >40% of observed cells, reduce mc_weight to near-zero. The fitted params may still be wrong on extreme rounds.

### Layer 3: Bayesian correction with observations (from v3)

Treat the blended prediction as a Dirichlet prior worth N pseudo-observations, then update with real observations:

```
alpha = blended × mc_equiv_samples
posterior = alpha + obs_counts
prediction = posterior / sum(posterior)
```

This is v3's Bayesian correction but applied on top of the distance-aware + MC blend instead of just MC alone. The `mc_equiv_samples` parameter controls how much trust we place in the model vs raw observations.

**Adaptive mc_equiv_samples:** Set higher (100) when MC fits well (high agreement with obs), lower (20) when MC is uncertain. This lets observations override a bad model more easily.

## Step 6: Floor & Submit (improved)

### KT-estimator floors (from deep research)

Replace the fixed per-class floors with the KT-estimator, which is minimax optimal for KL divergence:

```
q(c) = (n_c + 0.5) / (N + 3.0)
```

where n_c is the count for class c and N is total observations. This adapts per-cell:
- Unobserved cells: floor = 0.167 (safe uniform)
- Well-observed cells: floor = 0.038 (tighter, more confident)

This replaces the current fixed floors `[0.01, 0.01, 0.001, 0.005, 0.01, 0.001]` which are hand-tuned and suboptimal.

### Static overrides

Ocean cells → [0.99, 0.002, ...], Mountain cells → [..., 0.99]. These never change and shouldn't waste probability mass.

## Expected Impact by Round Type

| Round Type | Current | Expected | Why |
|------------|---------|----------|-----|
| Cold (R3)  | 68      | 85-90    | ABC fits winter_severity correctly, constrained search space, cold priors as baseline |
| Moderate (R4) | 92   | 92-94    | Already strong, MC refinement adds ~1-2 pts |
| Warm (R2/R5) | 80-85 | 87-92   | Fitted expansion_rate + distance-aware priors |
| Hot (R6)   | 77      | 83-88    | ABC fits aggressive expansion, prior prevents overestimation |

## Compute Budget

The main cost is ABC. Rough estimates:

- Stage 1: 500 candidates × 2 sims × 5 seeds = 5000 simulations (~30s with 8 cores)
- Stage 2: 200 candidates × 50 MC = 10000 simulations (~60s with 8 cores)
- Final MC: 500 runs × 5 seeds = 2500 simulations (~15s with 8 cores)
- **Total: ~2 minutes** on a modern machine

This fits within the round time limit. The current pipeline takes seconds but leaves 20+ points on the table.

## What's NOT Included (and why)

- **Multiple observation sweeps** — Diminishing returns. One full sweep + 5 smart Phase 2 queries is better than 2 full sweeps with no flexibility.
- **Per-seed ABC** — Params are shared. Pooling gives 5× more data for the fitter.
- **Soft regime blending** (Bayesian Model Averaging) — Good idea from deep research but adds complexity. Hard warm/cold classification + ABC already adapts to the actual params. Can add later if the hard threshold misclassifies rounds.
- **Hausser-Strimmer shrinkage** — Replaces fixed prior_weight with per-cell optimal weight. Theoretically better but complex. The three-layer blend already adapts trust levels. Save for v2.
