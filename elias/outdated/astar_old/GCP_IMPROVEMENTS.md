# Astar Island — Improvements

Concrete changes to implement, ordered by impact. Based on backtesting all 8 completed rounds (R1–R8) with budget=50.

**Current average: 78.4 → Target: 82.4+ (verified in backtest)**

---

## 1. Port Ratio Floor — +3.2 pts avg

**The single biggest fix.** The observed `port_ratio` is ~0.06 but the true value is 0.5–1.0 for warm rounds. With 1 observation per cell, port events (~10% probability) are almost never sampled, making the estimate 10x too low. Every coastal cell's port prediction is catastrophically wrong.

**Change in `run.py`:**

After `estimate_port_ruin_ratios()` returns, apply a floor:

```python
# After line 982 (port_ratio, ruin_ratio = estimate_port_ruin_ratios(...))
if warmth_label == "warm":
    port_ratio = max(port_ratio, 0.50)
else:
    port_ratio = max(port_ratio, 0.20)
    ruin_ratio = max(ruin_ratio, 0.20)
```

The floor values come from ground truth analysis across R1–R8:
- Warm rounds: port/settle ratio ranges 0.67–1.06, floor at 0.50 is conservative
- Cold rounds: port/settle ratio ~0.47, ruin/settle ~0.23

**Per-round impact:**

| Round | Before | After | Delta |
|-------|--------|-------|-------|
| R1 | 80.5 | 86.4 | +5.9 |
| R2 | 85.7 | 89.6 | +3.9 |
| R4 | 89.2 | 91.2 | +2.0 |
| R5 | 78.0 | 82.1 | +4.1 |
| R6 | 77.2 | 82.2 | +5.0 |
| R7 | 64.0 | 68.8 | +4.8 |

---

## 2. Per-Distance Settlement Rates — +0.4 pts avg

Replace `expansion_rate × decay_multiplier` with directly observed settlement rates per distance band. The current approach averages d1–d3 into a single expansion rate, then multiplies by a decay curve. This dilutes the signal on rounds like R7 where d1=32% but d3=1%.

**Change in `run.py`:**

Compute per-distance rates alongside the existing expansion rate estimation (in `run_observation_phases`, around line 936):

```python
# Compute per-distance absolute settlement rates
per_dist_rates = {}
for d in range(1, 11):
    if d in agg_dist_settle and agg_dist_settle[d][1] >= 5:
        per_dist_rates[d] = agg_dist_settle[d][0] / agg_dist_settle[d][1]
    else:
        per_dist_rates[d] = 0.0
```

Then in `get_distance_aware_prior`, use `per_dist_rates[dist]` directly as `target_settle` instead of `expansion_rate * decay`:

```python
# Instead of:
#   target_settle = expansion_rate * decay
# Use:
#   target_settle = per_dist_rates.get(dist, 0.0)
```

**Why it helps:** On R7, the d1-d3 average expansion rate is 0.163, but actual d1 rate is 0.322 and d3 is 0.011. Per-distance rates capture this shape exactly.

---

## 3. Dirichlet Conjugate Update — +0.3 pts avg

Replace the weighted average blend with a Bayesian Dirichlet update. The current blend uses `(prior_weight * prior + obs_weight * obs) / total_weight`, which doesn't properly account for observation count uncertainty.

**Change in `generate_prediction` (run.py line 727–757):**

```python
equiv_samples = 20  # effective prior strength

for r in range(map_h):
    for c in range(map_w):
        prior = get_distance_aware_prior(...)
        n_obs = sum(obs_counts[r][c]) if obs_counts else 0

        if n_obs > 0:
            # Dirichlet-conjugate update
            alpha = [prior[k] * equiv_samples for k in range(N_CLASSES)]
            posterior = [alpha[k] + obs_counts[r][c][k] for k in range(N_CLASSES)]
            total = sum(posterior)
            prediction[r][c] = [p / total for p in posterior]
        else:
            prediction[r][c] = prior
```

`equiv_samples=20` was found optimal via sweep (tested 5, 10, 15, 20, 30, 40, 60, 80). It means the prior is equivalent to 20 pseudo-observations. With 1 real observation, the prior still gets ~95% weight — but the math is correct for KL scoring.

---

## 4. Tighter Probability Floors — +0.2 pts avg

The current floors in `floor_and_normalize` (`utils.py:125`) use the same values for observed and unobserved cells. Observed cells need less safety margin.

**Change in `utils.py`:**

```python
def floor_and_normalize(prediction, obs_counts=None):
    # Tighter floors for observed cells, wider for unobserved
    unobs_floors = [0.008, 0.008, 0.001, 0.004, 0.008, 0.001]
    obs_floors   = [0.005, 0.005, 0.0005, 0.002, 0.005, 0.0005]

    for r, row in enumerate(prediction):
        for c, cell in enumerate(row):
            n_obs = sum(obs_counts[r][c]) if obs_counts else 0
            floors = obs_floors if n_obs > 0 else unobs_floors
            for i in range(len(cell)):
                cell[i] = max(cell[i], floors[i] if i < len(floors) else 0.005)
            total = sum(cell)
            for i in range(len(cell)):
                cell[i] /= total
    return prediction
```

---

## 5. Investigate R3 Cold Round — potential +10-20 pts on R3

R3 is stuck at 73.6 across all strategies (oracle is 99.1). The cold contextual priors overestimate settlement expansion by ~9x. None of the improvements above help R3.

**Suggested approach:**
- Build a dedicated cold prior table from R3+R8 ground truth with finer distance bins
- Use ruin density as an additional signal for cold classification (R3 has high ruin rates)
- Consider soft Bayesian blending between warm/cold regimes instead of the hard threshold at 0.05

---

## 6. Investigate R7 Residual Gap — R7 at 68.8, other warm rounds at 82-91

Even after all fixes, R7 scores 20+ points below other warm rounds. The warm contextual priors assume ~16% settlement at d1, but R7 has 36%. The per-dist rates capture the settlement rate correctly, but the prior's empty/forest allocation for unobserved cells is still calibrated to the average warm round.

**Suggested approach:**
- Sub-classify warm rounds by expansion intensity (tight vs diffuse)
- Use observed d1 rate to dynamically scale the contextual prior's settlement allocation
- Build a "tight expansion" prior table from R5+R7 ground truth

---

## 7. Soft Warm/Cold Classification

The binary threshold at `expansion_rate < 0.05` is a single point of failure. Replace with a sigmoid blend:

```python
import math
w_cold = 1.0 / (1.0 + math.exp(50 * (expansion_rate - 0.05)))
w_warm = 1.0 - w_cold
prior = [w_warm * warm_prior[k] + w_cold * cold_prior[k] for k in range(6)]
```

This hedges when the signal is ambiguous. On R3 (expansion ~0.003) it still goes ~100% cold. On borderline rounds it avoids catastrophic commitment.

---

## 8. Wire ABC Into Live Pipeline

The backtest already uses `generate_prediction_abc` with fitted parameters (`offline/run_local.py:285-297`), but the live `main()` in `run.py` still uses the older `generate_prediction`. The ABC path fits simulator parameters to match observations and uses Dirichlet-conjugate updating. Wiring it into `main()` would combine the simulator signal with the prior improvements above.

---

## Backtest Verification

All numbers above come from `offline/investigate_r7_final.py` run on 2026-03-20. Full results are in `logs/offline/investigations/`. To reproduce:

```bash
python offline/investigate_r7_final.py          # All rounds
python offline/investigate_r7_final.py --round 7  # Single round
```
