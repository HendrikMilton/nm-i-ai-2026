# Astar Island — Strategy

## Current Scores (budget=50, offline backtests)

| Round | Pipeline | Prior-only | Delta | Warmth | Expansion Rate |
|------:|--------:|-----------:|------:|--------|---------------:|
| 1     | 82.8    | 77.7       | +5.1  | warm   | 0.192          |
| 9     | 88.9    | 88.1       | +0.8  | warm   | 0.159          |
| 13    | 87.2    | 87.6       | -0.4  | warm   | 0.104          |
| 14    | 72.3    | 69.1       | +3.1  | warm   | 0.309          |

## Pipeline Architecture

Three-layer blending (ABC path):

1. **Distance-aware contextual prior** — lookup tables keyed by `{terrain}_{n_forest}_{is_coastal}`, with warm/cold variants, adjusted by Chebyshev distance to nearest initial settlement
2. **ABC-fitted Monte Carlo** (20% weight) — 14 directly-fitted simulator parameters, 500 weighted MC runs from top 15 parameter sets
3. **Bayesian Dirichlet update** — observations as pseudocounts against the blended prior (equiv_samples: 20 warm, 50 cold)

Cold rounds pool observations across all 5 seeds for 5x data amplification.

## Observation Strategy — Depth Over Breadth

Instead of spreading 50 queries thinly across all 5 seeds (9 each, ~1 obs/cell), we observe **3 seeds deeply** and let the remaining 2 rely on learned parameters + priors + MC.

- **Deep seed selection**: Pick 3 seeds with the most diverse initial terrain (greedy max-min terrain diff) to maximize the variety of dynamics we learn from.
- **Per-seed budget**: ~16-17 queries each (50 / 3), split as:
  - **Coverage** (9 queries): Full 3x3 tiling covering ~90% of the map
  - **Depth** (7-8 queries): Extra viewports targeting dynamic areas near settlements (Chebyshev distance 1-4), scored by proximity to initial settlements. Overlap with coverage viewports avoided.
- **Unobserved seeds** (2 of 5): Get 0 direct observations. Predictions come from distance-aware prior + ABC-fitted MC simulation. MC is trusted without validation since it was fitted on observed seeds.
- **MC validation**: For observed seeds, MC is gated by argmax agreement (threshold 0.72). For unobserved seeds, MC is always used.
- Expansion rate, distance decay, port/ruin ratios estimated from the 3 observed seeds.
- Warm/cold classification at expansion rate threshold 0.05.

## Key Parameters

| Parameter | Value | Role |
|-----------|-------|------|
| `ABC_PRIOR_WEIGHT` | 0.80 | Prior weight in prior+MC blend |
| `ABC_MC_WEIGHT` | 0.20 | MC weight in prior+MC blend |
| `SIM_SAFETY_THRESHOLD` | 0.72 | MC argmax agreement gate (observed seeds only) |
| `N_DEEP_SEEDS` | 3 | Seeds to observe deeply |
| `EQUIV_WARM_PER_SEED` | 20 | Dirichlet prior strength (warm) |
| `EQUIV_COLD_POOLED` | 50 | Dirichlet prior strength (cold) |
| `MC_TOTAL_RUNS` | 500 | Total MC simulations per seed |
| `CLASS_FLOORS` | [0.001, 0.001, 0.0002, 0.0005, 0.001, 0.0002] | Minimum per-class probabilities |
| `WARM_COLD_THRESHOLD` | 0.05 | Expansion rate cutoff |

## ABC Parameter Fitting

Two-stage Approximate Bayesian Computation with 14 directly-fitted parameters:

**Stage 1**: 50 LHS candidates x 2 sims x 5 seeds, scored by argmax match rate, keep top 15.
**Stage 2**: Perturb top 15 into 40 candidates x 20 sims, scored by log-likelihood, keep top 8.

Parameters fitted directly (no translation layer):
- Growth: `expansion_chance`, `expansion_threshold`, `base_food_production`, `population_growth_rate`
- Conflict: `raid_chance`, `conquest_chance`
- Winter: `winter_severity_mean`, `winter_food_loss_base`, `collapse_chance_base`
- Trade: `trade_range`
- Environment: `settlement_reclaim_chance`, `ruin_forest_reclaim_chance`
- Longships: `longship_build_chance`, `longship_raid_range`

All parameters have separate warm/cold ranges. Winter severity range extends to 1.5 for cold rounds.

## Simulator Mechanics

5 phases per year, 50 years:
1. **Growth** — food from adjacent forests, population growth, port/longship development, expansion onto buildable terrain (plains, empty, ruin, **forest**)
2. **Conflict** — raids between factions, longships extend range, desperate raids when food is low
3. **Trade** — port-to-port within range, tech diffusion
4. **Winter** — stochastic severity, food loss, settlement collapse into ruins
5. **Environment** — nearby settlements reclaim ruins (grid scan), forests overtake unclaimed ruins

All distance checks use Chebyshev (max of |dx|, |dy|).

## What Works

- **Contextual priors** with terrain+neighborhood context are the strongest single signal
- **ABC MC** now helps (+1-9 points over prior) after fixing direct parameter mapping and simulator bugs
- **Depth-over-breadth observations** — 3 deep seeds with MC transfer to unobserved seeds reduces spread (1.6-2.6) and improves average score on dynamic rounds
- **Observation pooling** on cold rounds is essential (5x data amplification)
- **Distance-aware priors** correctly model settlement probability decay from initial positions
