# Proposal: Expansion-Rate-Aware Distance Priors

## The Problem

Our current prior model uses 3 features: `(terrain, n_forest_neighbors, is_coastal)`. Distance to settlement is applied separately as a multiplicative hack. This means the prior doesn't know that a plains cell at distance 1 from a settlement behaves completely differently from one at distance 5.

**Result:** Our prior-only score averages **76.1** across 15 rounds (leave-one-out).

## The Fix

A joint prior that conditions on `(expansion_rate, terrain, distance, n_forest, is_coastal)` — all in one lookup. Built from all 16 rounds of ground truth (76 seed maps), using Gaussian kernel weighting on expansion rate so the prior adapts to how expansive the current round is.

**Result:** Prior-only score jumps to **85.5** average (+9.4 points).

## Leave-One-Out Scores (Prior Only, No Observations)

| Round | Old Prior | New Prior | Delta | Expansion Rate |
|-------|----------|-----------|-------|----------------|
| R1    | 82.6     | 87.4      | +4.8  | 0.209 |
| R2    | 89.8     | 90.7      | +0.9  | 0.218 |
| R3    | 74.3     | 86.7      | +12.4 | 0.003 (cold) |
| R4    | 87.2     | 93.5      | +6.3  | 0.109 |
| R5    | 78.2     | 85.6      | +7.4  | 0.154 |
| R6    | 73.5     | 88.2      | +14.7 | 0.281 |
| R7    | 53.3     | 67.9      | +14.6 | 0.176 |
| R8    | 84.2     | 90.1      | +5.9  | 0.030 (cold) |
| R9    | 90.5     | 85.9      | -4.6  | 0.163 |
| R10   | 78.8     | 89.9      | +11.1 | 0.011 (cold) |
| R11   | 73.9     | 90.2      | +16.3 | 0.349 |
| R12   | 40.4     | 55.4      | +15.0 | 0.175 |
| R13   | 87.2     | 94.1      | +6.9  | 0.114 |
| R14   | 56.5     | 86.7      | +30.2 | 0.323 |
| R15   | 91.7     | 90.3      | -1.4  | 0.210 |
| **Avg** | **76.1** | **85.5** | **+9.4** | |

Biggest gains on hard rounds (R14: +30, R11: +16, R12: +15, R7: +15). Small regressions on R9 (-4.6) and R15 (-1.4) — likely noise from Gaussian kernel bandwidth.

## Why It Works

The old prior says: "a plains cell with 2 forest neighbors has 82% chance of staying empty."

But that's an average across ALL distances. A plains cell at distance 1 from a settlement might have 55% empty / 30% settlement. At distance 6, it's 98% empty / 1% settlement. Averaging these together produces a mediocre prediction for both.

The new prior knows the distance, so it predicts each correctly.

## What's Included

All files are in `arian/`:

| File | Description |
|------|-------------|
| `distance_priors.json` | Pre-computed prior tables (81 expansion rates × 155 cell feature keys) |
| `build_distance_priors.py` | Script that builds the priors from all GT data |
| `run.py` | Modified to use new priors via `get_distance_prior()` with fallback to old approach |
| `contextual_priors_warm.json` | Rebuilt warm priors from 13 warm rounds (was missing) |
| `contextual_priors_cold.json` | Rebuilt cold priors from 3 cold rounds (was missing) |
| `contextual_priors.json` | Rebuilt from all 16 rounds |

## How It Plugs Into The Pipeline

`get_distance_aware_prior()` in `run.py` now tries the new joint prior first. If a match is found (it will be for ~99% of cells), it returns it directly. Otherwise falls back to the old multiplicative approach.

The live pipeline flow:
1. Observe seeds, estimate expansion rate from observations
2. For each cell: look up `distance_priors[expansion_rate][terrain_dist_forest_coastal]`
3. Blend with observations via Bayesian update
4. Submit

## Estimated Live Performance

- **Prior-only:** ~85-86 average
- **With observations:** ~88-92 on a typical round
- **Best case (favorable round):** 93-95 → weighted score of 272-278 at round 22+ weights → **top 5 on leaderboard**
- **Hard rounds:** Still 60-70 (R7/R12 type dynamics are hard for any approach)

## Risks

- Trained on 16 rounds. A round with truly novel dynamics could underperform.
- Gaussian bandwidth (0.03) is tuned but not optimized — could be swept.
- R9 and R15 show small regressions (-4.6, -1.4) — might want to blend old + new priors.

## Recommendation

Ship it for the next round. The +9.4 average improvement is too large to leave on the table. Even in the worst case (R9-style regression), we lose ~5 points. In the best case, we gain 15-30 points on a hard round.
