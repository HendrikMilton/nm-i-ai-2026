# Astar Island — Strategy

## Results History

### Live Submissions

| Round | Strategy | Queries | Score | Notes |
|-------|----------|---------|-------|-------|
| R3    | v1 (1 obs/cell, deterministic) | 50 | 0.26 | |
| R5    | v2 (focus seeds + cross-seed avg) | 48 | 25.0 | Cross-seed averaging was catastrophic |
| R6    | v5 (simulator_v5, no queries) | 0 | — | Sim-only, no observations |
| R7    | v5 (obs_sim_prior_v5) | 50 | — | Full pipeline |

### Offline Backtests (full pipeline, budget=50)

| Round | Score | Best Sim-Only | Prior-Only | Oracle |
|-------|-------|---------------|------------|--------|
| R1    | **83.7** | 83.3 (sw0.3/pw6) | 73.5 | ~84 |
| R2    | **85.2** | 83.8 (sw0.3/pw6) | 75.4 | 84.1 |
| R3    | **68.4** | 67.6 (no sim) | 52.8 | 89.3 |
| R4    | **91.7** | 91.8 (sw0.1/pw4) | 87.6 | 89.3 |
| R5    | **78.5** | 76.2 (sw0.3/pw6) | 69.1 | 76.0 |
| R6    | **76.8** | 70.9 (no sim) | — | 78.9 |
| R7    | **59.0** | — | — | — | ⚠ Significant drop — investigate what differs from R1-6 |
| **Avg (R1-6)** | **80.7** | | | |

### Key Sweep Findings

**Sim weight:** Lower is almost always better. The simulator hurts on cold rounds (R3, R6) and barely helps on warm ones. Best configs are sw=0.0-0.3.

**Prior weight:** Higher is better up to ~6.0, then diminishing returns. pw=4-6 is the sweet spot.

**Distance-aware priors** were the single biggest improvement: +5 to +15 pts per round vs flat contextual priors.

---

## Current Strategy (v5)

### Overview

Three-signal blend: **observations + Monte Carlo simulator + distance-aware priors**.

Observations are used to estimate the round's expansion rate, which adjusts priors. The sim provides a secondary signal. Priors are the backbone.

### Current Weights (as in run.py)

```
OBS_WEIGHT   = 0.0   ← PROBLEM: observations not blended into predictions
SIM_WEIGHT   = 0.0   ← disabled — sim hurts on cold rounds
PRIOR_WEIGHT = 1.0
N_SIMS       = 1     ← minimal since sim is disabled
```

**Critical issue:** All three signals besides priors are disabled. We spend 50 queries per round solely to estimate expansion rate, then throw away the direct observation data. The simulator is also off because `DEFAULT_PARAMS` hurt on cold rounds. The full pipeline backtests show observations help (+1 to +6 pts per round), but this gain currently comes only from expansion rate estimation, not from direct blending.

### Pipeline Steps

1. **Fetch round data** — per-seed initial grids (40x40, 5 seeds)
2. **Plan viewports** — greedy set-cover to hit all dynamic cells (settlements/ports/ruins) per seed
3. **Phase 1 observations** — one pass of dynamic viewports across all 5 seeds
4. **Phase 2 observations** — re-query same viewports, prioritizing seeds with highest surprise vs priors (impact unquantified — needs Phase 1-only vs Phase 1+2 backtest comparison)
5. **Estimate expansion rate** — from observed settlement frequency near initial settlements (cells dist 1-3)
6. **Build distance-aware priors** — contextual priors adjusted by distance to nearest settlement × expansion rate decay curve
7. **Run Monte Carlo** — 200 stochastic sims per seed, produces H×W×6 probability tensor
8. **Blend** — weighted average of obs (currently 0), sim (0.5), and prior (4.0) per cell
9. **Floor & normalize** — per-class minimum floors, renormalize to sum=1
10. **Submit** — 5 predictions, one per seed

### Distance-Aware Prior System

The expansion rate varies wildly by round:

| Round | Expansion Rate | Character |
|-------|---------------|-----------|
| R3    | ~1%           | Cold — everything dies |
| R4    | ~12%          | Moderate |
| R5    | ~24%          | Warm — active expansion |
| R2    | ~23%          | Warm |
| R6    | ~30%          | Hot — very aggressive |

Settlement probability decays with Chebyshev distance from nearest initial settlement:

```
dist 0: 0.0   (already a settlement)
dist 1: 1.20 × expansion_rate
dist 2: 1.00 × expansion_rate
dist 3: 0.70 × expansion_rate
dist 4: 0.50 × expansion_rate
dist 5: 0.30 × expansion_rate
dist 6: 0.20 × expansion_rate
dist 7: 0.10 × expansion_rate
dist 8+: 0.5/dist (≤10), 0.0 (>10)
```

These multipliers were calibrated from R2-R6 ground truth (see `run.py:185`), not swept/fitted. A sweep over decay shapes (linear, exponential, per-round fitted) could yield a few more points.

### What Works

- **Distance-aware priors** — the biggest lever. Correctly estimating expansion rate is worth +10-20 pts on extreme rounds.
- **Low sim weight** — the simulator's DEFAULT_PARAMS rarely match hidden parameters. Less sim = better.
- **Contextual priors** — terrain type + forest neighbors + coastal proximity gives a solid baseline.
- **Per-class floors** — prevents KL infinity. Port/mountain get smaller floors (0.001) than common classes (0.01).

### What Doesn't Work

- **Cross-seed averaging** — each seed has a different map. Never share data across seeds.
- **High sim weight** — hurts R3 by -8 pts, R4 by -3 pts. The sim is directionally wrong on some rounds.
- **1-2 observations per cell** — too noisy to beat priors (but currently moot since OBS_WEIGHT=0).

### Where the Score Comes From

Entropy weight by terrain type (determines what matters most for scoring):

- **Plains: 65.6%** — most cells, moderate uncertainty. Getting plains predictions right dominates the score.
- **Forest: 27.8%** — second largest. Correctly predicting whether forests survive or get consumed by expansion matters.
- **Settlement: 6.6%** — small weight but high entropy per cell.
- Port/Ruin/Mountain: negligible weight.

Implication: improvements that target plains and forest cell accuracy are disproportionately valuable. Overestimating expansion on a cold round hurts massively because it's wrong on the 65.6% of entropy weight that is plains cells.

---

## Next Steps

See `IMPROVEMENTS.md` for the full checklist. Top priorities:

1. **Enable observation blending** — set OBS_WEIGHT > 0. Backtests show +1-6 pts from observations.
2. **Warm/cold round classification** — separate prior tables for warm vs cold rounds to close the R3 gap (oracle: 89.3, current: 68.4). This is the single biggest opportunity: the 21-point gap on R3 comes from overestimating expansion by ~9x, which is wrong on plains cells (65.6% of score weight).
3. **Simulator safety net** — auto-disable sim when it diverges from observations.
4. **Investigate R7** — 59.0 is a significant regression from the R1-6 average of 80.7. Need oracle scores and ground truth to determine if this is a new round archetype or a bug.

---

## Key Lessons Learned

1. **Priors > simulator > observations (currently)**. With OBS_WEIGHT=0, priors carry ~89% of the blend. This works because priors are smooth and never catastrophically wrong, while the sim can be.
2. **One number matters most:** the round's expansion rate. Getting this right adjusts priors correctly across all 1600 cells.
3. **The scoring formula is exponential** — reducing weighted KL from 0.25→0.15 is worth ~20 points. Small improvements compound.
4. **R3 is the biggest opportunity** — 21 point gap to oracle. It's a cold round where settlements die. Our average-trained priors overestimate settlement expansion by ~9x.
5. **50 queries is enough** to estimate expansion rate reliably, but the direct observation signal is currently wasted.
