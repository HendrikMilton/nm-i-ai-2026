# Astar Island — Strategy

## Current Scores (budget=50, rounds 9-12)

| Round | Pipeline | Prior-only | Delta | Warmth | Expansion Rate |
|------:|--------:|-----------:|------:|--------|---------------:|
| 9     | 88.5    | 88.6       | -0.1  | warm   | 0.156          |
| 10    | 82.9    | 73.7       | +9.2  | cold   | 0.014          |
| 11    | 84.6    | 80.1       | +4.5  | warm   | ~0.10          |
| 12    | 54.5    | 48.4       | +6.1  | cold   | ~0.01          |
| **Avg** | **77.6** |          |       |        |                |

## Pipeline Architecture

Three-layer blending (ABC path):

1. **Distance-aware contextual prior** — lookup tables keyed by `{terrain}_{n_forest}_{is_coastal}`, with warm/cold variants, adjusted by Chebyshev distance to nearest initial settlement
2. **ABC-fitted Monte Carlo** (20% weight) — 14 directly-fitted simulator parameters, 500 weighted MC runs from top 15 parameter sets
3. **Bayesian Dirichlet update** — observations as pseudocounts against the blended prior (equiv_samples: 20 warm, 50 cold)

Cold rounds pool observations across all 5 seeds for 5x data amplification.

## Observation Strategy

- **Phase 1**: 9 viewports (3x3 tiling) per seed, all 5 seeds = 45 queries. Covers ~90% of the 40x40 map.
- **Phase 2**: 5 remaining queries targeted at boundary cells (distance 1-3 from settlements) on the most surprising seeds.
- Expansion rate, distance decay, port/ruin ratios estimated from Phase 1 observations.
- Warm/cold classification at expansion rate threshold 0.05.

## Key Parameters

| Parameter | Value | Role |
|-----------|-------|------|
| `ABC_PRIOR_WEIGHT` | 0.80 | Prior weight in prior+MC blend |
| `ABC_MC_WEIGHT` | 0.20 | MC weight in prior+MC blend |
| `EQUIV_WARM_PER_SEED` | 20 | Dirichlet prior strength (warm) |
| `EQUIV_COLD_POOLED` | 50 | Dirichlet prior strength (cold) |
| `MC_TOTAL_RUNS` | 500 | Total MC simulations per seed |
| `CLASS_FLOORS` | [0.001, 0.001, 0.0002, 0.0005, 0.001, 0.0002] | Minimum per-class probabilities |
| `WARM_COLD_THRESHOLD` | 0.05 | Expansion rate cutoff |

## ABC Parameter Fitting

Two-stage Approximate Bayesian Computation with 14 directly-fitted parameters:

**Stage 1**: 500 LHS candidates x 2 sims x 5 seeds, scored by argmax match rate, keep top 50.
**Stage 2**: Perturb top 20 into 200 candidates x 50 sims, scored by log-likelihood, keep top 15.

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
- **Observation pooling** on cold rounds is essential (5x data amplification)
- **Distance-aware priors** correctly model settlement probability decay from initial positions
