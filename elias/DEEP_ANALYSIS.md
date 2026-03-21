# Deep Analysis: Astar Island Strategy

## Current Performance Summary

| Round | Score | Prior-only | Delta | Warmth | Notes |
|------:|------:|-----------:|------:|--------|-------|
| 1     | 79.7  | 78.8       | +0.9  | warm   | |
| 2     | 84.3  | 84.6       | -0.3  | warm   | Pipeline hurts slightly |
| 3     | 74.5  | 63.8       | +10.7 | cold   | ABC shines on cold |
| 4     | 88.4  | 87.4       | +1.0  | warm   | |
| 5     | 78.8  | 76.3       | +2.4  | warm   | |
| 6     | 78.0  | 76.5       | +1.4  | warm   | |
| 7     | 62.9  | 58.5       | +4.3  | warm   | Low scores — hard round |
| 8     | 87.6  | 85.5       | +2.1  | cold   | |
| 9     | 88.9  | 88.0       | +0.9  | warm   | |
| 10    | 78.1  | 70.7       | +7.4  | cold   | |
| 11    | 83.6  | 80.2       | +3.4  | warm   | |
| 12    | 50.5  | 45.4       | +5.1  | warm   | Very hard round |
| 13    | 86.4  | 86.1       | +0.3  | warm   | Near-zero delta |
| 14    | 73.1  | 70.5       | +2.6  | warm   | |
| 15    | 89.5  | 88.1       | +1.5  | warm   | Best warm round |
| 16    | 80.6  | 78.1       | +2.5  | warm   | |

**Average score: 79.7. Average delta over prior: +2.8 points.**

---

## What the Current System Does Well

### 1. Contextual Priors are the Foundation (80% weight)
The lookup tables keyed by `{terrain}_{n_forest}_{is_coastal}` capture the most important signal: what terrain type a cell becomes depends on what it starts as and what's around it. This alone gets scores in the 63-88 range. The warm/cold variant priors correctly differentiate high-expansion vs low-expansion rounds.

### 2. Distance-Aware Modeling
The Chebyshev distance decay from initial settlements is sound — settlements expand close to existing settlements, with probability falling off with distance. The learned distance multipliers from observations adapt this per-round.

### 3. Cold Round Handling
Observation pooling across seeds (+5x data), higher Dirichlet equiv samples, and separate cold distance decay curves all work well. Cold rounds show the biggest deltas (+7-10 points).

### 4. Bayesian Dirichlet Update
Using observations as pseudocounts against the prior is mathematically clean and appropriate for this problem. The equiv_samples parameter controls the prior-observation balance well.

---

## Weaknesses and Opportunities

### Critical Issue 1: Live Mode Doesn't Use ABC MC (~2-5 points left on table)

**Impact: HIGH**

In `main()` (line 1313), the live game passes `mc_pred=None` to `generate_prediction_abc`:
```python
prediction = generate_prediction_abc(grid, None, ...)  # No MC!
```

The comment says "no MC in live — too slow", but the ABC fitting + 500 MC runs typically takes 2-5 minutes on modern hardware. With a 2h45m prediction window, this is easily feasible. The backtest scores include ABC MC, but the live submissions don't.

**Fix:** Run ABC fitting + weighted MC during the live round. This alone could gain +1-5 points depending on the round.

### Critical Issue 2: Phase 2 Queries are Never Used

**Impact: MEDIUM**

The function `pick_phase2_viewports()` (lines 433-549) implements an adaptive second phase that targets surprising or high-variance areas. However, it's never called — `run_observation_phases()` uses the fixed depth-over-breadth strategy exclusively. The extra 7-8 queries per deep seed are placed by `_build_depth_viewports()` using a static scoring heuristic (distance 1-4 from settlements), not adaptively based on what was observed in the first pass.

**Fix:** Split the budget into two phases: Phase 1 (coverage tiles) then Phase 2 (adaptive targeting based on Phase 1 results). This would let the system focus extra queries where the simulation is most uncertain.

### Critical Issue 3: Observation Stochasticity Waste

**Impact: MEDIUM-HIGH**

Each observation query runs one stochastic simulation and returns one outcome. With 16 queries per deep seed covering ~1400 interior cells, most cells get only 1-2 observations. The stochastic nature of the simulation means a single observation of a dynamic cell tells us very little about the true probability distribution.

Currently the depth queries target settlement neighborhoods (distance 1-4), which are the most dynamic. But with only 2-3 observations per cell there, the Bayesian update barely moves the prior.

**Opportunities:**
- **Smaller viewports for higher density**: Instead of always 15x15, use smaller viewports (e.g., 10x10 or even 5x5) concentrated on the most dynamic cells. This gives more observations per cell at the cost of coverage. Since the prior handles unobserved cells reasonably well, this trade-off could be worth it.
- **Query the same viewport multiple times**: If a 15x15 area has 30 dynamic cells, querying it 3 times gives 3 observations per cell. The information gained from the 3rd observation of a dynamic cell is worth more than the 1st observation of a static cell.

### Issue 4: Simulator Fidelity Gap

**Impact: MEDIUM**

The local simulator may differ from the server's hidden simulator in important ways:

1. **Trade mechanics**: The local sim allows trade between same-faction ports OR randomly (50% chance) between enemy ports. The actual game may have different conditions (e.g., war blocking trade entirely).
2. **Expansion target selection**: The local sim picks randomly from all buildable cells within radius. The real sim may have terrain preferences (e.g., preferring forests for food, coasts for ports).
3. **Initial conditions**: The local sim randomizes starting population/food/wealth, but the real sim may have deterministic initial values or different distributions.
4. **Defense recovery**: The local sim has `defense += 0.02 * population` per year, but the real sim may have different defense dynamics.
5. **Missing mechanics**: The game rules mention "alliances shift" and "factions clash" — there may be alliance mechanics (multi-faction cooperation) that the simulator doesn't model.

The ABC fitting partially compensates by adjusting 14 parameters, but structural differences in the simulation phases can't be fixed by parameter tuning alone.

**Opportunity:** Use the 50 observation queries not just for cell-level counts, but to extract settlement-level dynamics. The API returns settlement stats (population, food, wealth, defense) — these could be used to calibrate the simulator's internal dynamics (food production rates, raid damage, winter severity) much more precisely than cell-type matching alone.

### Issue 5: Contextual Priors are Coarse

**Impact: MEDIUM**

The priors key on `{terrain}_{n_forest}_{is_coastal}` with n_forest capped at 4. Missing context:

1. **Distance to nearest settlement** is not in the prior key — it's applied separately via `get_distance_aware_prior()`. A unified model that conditions on all features jointly would be more accurate.
2. **Number of adjacent settlements/ports** is not captured. A plains cell surrounded by 3 settlements behaves very differently from one surrounded by 0.
3. **Faction structure** is ignored. A cell between two rival factions may become a battleground (higher ruin probability).
4. **Mountain adjacency** is not captured. Cells backed against mountains have fewer expansion directions, affecting settlement probability.

**Opportunity:** Build a more granular prior model, potentially using a simple statistical model (logistic regression or small neural net) trained on all available ground truth data, conditioning on a richer feature vector: (terrain, n_forest, n_settlement, n_mountain, n_ocean, distance_to_settlement, is_coastal, n_factions_nearby).

### Issue 6: Per-Seed vs Pooled Strategy is Binary

**Impact: LOW-MEDIUM**

Currently: warm rounds use per-seed observations only; cold rounds pool all observations. In reality, there's a spectrum. Even warm rounds benefit from partial pooling — the hidden parameters are shared across all seeds, so the expansion rate and distance decay learned from observed seeds should transfer.

The current system does transfer expansion_rate and dist_multipliers across seeds via `aggregate_expansion_stats()`, but the raw observation counts are per-seed only (warm) or fully pooled (cold).

**Opportunity:** Use hierarchical pooling — partial Bayesian shrinkage toward the pooled mean. This would help unobserved seeds (which currently get 0 observations) benefit from observed data without treating all seeds identically.

### Issue 7: Scoring Function Awareness

**Impact: MEDIUM**

The scoring function weights cells by entropy: `weight = entropy(cell)`. High-entropy cells (where the true outcome is uncertain) matter most. The current system doesn't explicitly optimize for this — it treats all dynamic cells equally.

**Opportunities:**
1. **Entropy-aware query targeting**: Focus observation queries on cells likely to have high entropy (cells near settlement boundaries at distance 2-3, where outcome could be settlement, ruin, forest, or empty with roughly equal probability).
2. **Entropy-aware prediction calibration**: For high-entropy cells, being well-calibrated matters more than being confident. The system should avoid being over-confident on high-entropy cells (lower equiv_samples for these cells).

### Issue 8: R7 and R12 are Outliers (scores 62.9 and 50.5)

**Impact: HIGH for understanding**

These rounds score far below the others. Understanding why would reveal the biggest gaps in the model:
- **R12 (50.5)**: Even the prior-only score is 45.4, meaning the contextual priors are badly miscalibrated for this round's dynamics. This suggests the round has unusual hidden parameters — perhaps very high winter severity, or unusual expansion patterns that the warm/cold binary doesn't capture.
- **R7 (62.9)**: Similar story. The ground truth is very different from what the priors expect.

**Opportunity:** Add a third warmth category ("extreme") or make the model continuous rather than binary warm/cold. Or better: let the ABC fitting adjust the priors themselves, not just the MC simulation.

---

## Concrete Improvement Ideas (Ranked by Expected Impact)

### Tier 1: High Impact, Moderate Effort

#### 1A. Enable ABC MC in Live Mode
- Estimated gain: +1-5 points per round
- Effort: Small (remove the `None` in line 1313, add ABC fitting call)
- The backtest infrastructure already exists; just wire it into the live path

#### 1B. Optimize Observation Strategy: Smaller Viewports for Dynamic Areas
- Estimated gain: +1-3 points
- Effort: Medium
- After the coverage pass (9 queries with 15x15), use 7-8 depth queries with 8x8 or 10x10 viewports centered on settlement neighborhoods. This gives 2-4x more observations per dynamic cell.
- Alternative: Query the same 15x15 viewport 2-3 times instead of querying different areas once.

#### 1C. Use Settlement Stats from API Responses
- Estimated gain: +1-2 points (indirect, via better simulator calibration)
- Effort: Medium
- The simulate API returns settlement population/food/wealth/defense — currently ignored. These could constrain ABC parameter fitting much better (e.g., if observed settlements have low food, winter_severity is probably high).

### Tier 2: Medium Impact, Higher Effort

#### 2A. Richer Prior Features
- Estimated gain: +1-3 points
- Effort: High
- Train a model on all ground truth data (16 rounds) with features: terrain type, n_forest, n_settlement, n_mountain, n_ocean, distance_to_settlement, is_coastal, etc.
- Could be a simple logistic regression (one-vs-rest for 6 classes) or a shallow neural net.
- Risk: overfitting with only 16 rounds of training data.

#### 2B. Adaptive Phase 2 Observation Targeting
- Estimated gain: +0.5-2 points
- Effort: Medium
- Implement the Phase 2 concept: after coverage pass, compute per-cell surprise (observation vs prior disagreement), and target the highest-surprise areas.

#### 2C. Continuous Warmth Modeling
- Estimated gain: +1-2 points on extreme rounds (R7, R12)
- Effort: Medium
- Replace binary warm/cold with a continuous expansion_rate parameter that smoothly interpolates between warm and cold priors, distance decays, and equiv_samples.

### Tier 3: Speculative, Potentially High Impact

#### 3A. Per-Cell Entropy-Aware Equiv Samples
- Estimated gain: +0.5-1 point
- Effort: Low
- For cells that the prior predicts with high certainty (e.g., deep ocean), use very high equiv_samples. For uncertain cells (settlement boundary), use lower equiv_samples to let observations move the prediction more.

#### 3B. Multi-Observation Repeat Strategy
- Estimated gain: +1-3 points (high variance)
- Effort: Medium
- Instead of 3 seeds x 16 queries (depth strategy), try 2 seeds x 25 queries. Each seed gets 9 coverage + 16 depth queries = 2.7 observations per cell on average, vs 1.7 currently. The trade-off is that 3 seeds go unobserved, but they rely on MC anyway.

#### 3C. Ensemble Across Different Parameter Fits
- Estimated gain: +0.5-1 point
- Effort: Low
- Currently the top 8 ABC fits are combined via softmax-weighted MC. Consider also maintaining separate priors for each fit and averaging the final predictions.

#### 3D. Complete Simulator Rewrite Based on Observed Dynamics
- Estimated gain: Unknown, potentially +5-10 points
- Effort: Very High
- Reverse-engineer the actual server simulator by carefully analyzing observation patterns. For example: do settlements always expand before raiding? Does trade happen between enemies? Do forests grow into ruins only when adjacent?
- This is the highest-ceiling improvement but requires significant reverse-engineering effort.

---

## Self-Evaluation of This Analysis

### Strengths of this analysis:
1. **Grounded in data**: Every observation is backed by backtest scores and code references.
2. **Actionable**: Each improvement has estimated impact, effort, and a clear implementation path.
3. **Prioritized**: Tier 1 items are immediate wins; Tier 3 items are speculative but worth considering.

### Weaknesses / uncertainties:
1. **Impact estimates are rough**: Without running experiments, it's hard to know if enabling ABC MC in live mode would gain 1 point or 5. The backtest scores include ABC MC, so the delta is baked into the current numbers — but live mode doesn't use it.
2. **I haven't analyzed the worst cells deeply**: The backtest results include `worst_cells` lists showing which cells contribute most to KL divergence. Analyzing these systematically could reveal specific failure modes (e.g., "the system consistently under-predicts ruin probability at distance 2 from settlements").
3. **Limited understanding of the server simulator**: The local simulator is a best guess. Without more systematic probing of the server's actual mechanics, it's hard to know how faithful it is.
4. **R15 variance**: The 20 backtest runs of R15 show scores ranging from 88.0 to 89.8 — a 1.8-point spread from pure stochastic variance in observation queries. This means any improvement smaller than ~1 point is hard to distinguish from noise.

### What I'd investigate next:
1. Run a backtest with ABC MC disabled to measure its true isolated contribution.
2. Analyze the worst-scoring cells across all rounds to find systematic prediction errors.
3. Test smaller viewport sizes for depth queries.
4. Measure how much the settlement-level stats from the API could improve ABC fitting.

---

## Summary

The current system is well-engineered with a solid three-layer architecture (prior + MC + Bayesian update). The biggest immediate win is **enabling ABC MC in live mode** (currently disabled with a comment "too slow"). Beyond that, the observation strategy could be improved by using **smaller viewports or repeated queries** for dynamic areas, and the prior model could be enriched with **additional spatial features**. The hardest but highest-ceiling improvement would be **reverse-engineering the server simulator** to close the fidelity gap.

The system's average score of ~80 with a +2.8 delta over prior-only suggests it's extracting meaningful signal from observations, but there's substantial room for improvement, especially on hard rounds (R7: 62.9, R12: 50.5) where the model's assumptions about world dynamics break down.
