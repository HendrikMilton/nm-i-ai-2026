# Astar Island v2 — Strategy

## Current Pipeline

Three-layer blending (ABC path):
1. **Distance-aware contextual prior** — based on terrain type, distance to settlements, expansion rate
2. **ABC-fitted Monte Carlo** — simulator with fitted parameters blended into prior
3. **Bayesian Dirichlet update** — observations update the blended prior as pseudocounts

## Baseline Scores (v2, budget=50)

| Round | Pipeline | Prior-only | Delta | Warmth | Expansion Rate |
|---:|---:|---:|---:|---|---:|
| 9 | 87.6 | 88.2 | -0.6 | warm | 0.154 |
| 10 | 73.1 | 73.5 | -0.4 | cold | 0.014 |

**Key finding:** The ABC pipeline is currently *hurting* scores vs prior-only on both warm and cold rounds. The MC-fitted simulator predictions are introducing noise rather than signal.

## Scoring Mechanics

- `score = 100 × exp(-3 × weighted_kl)`
- Only **dynamic cells** (entropy > 0.01) contribute — static terrain is irrelevant
- High-entropy cells (uncertain outcomes) are weighted more heavily
- KL divergence punishes under-prediction severely: predicting q=0.02 when truth p=0.20 is catastrophic

## Key Observations

### Cold rounds (expansion < 0.05)
- Very few dynamic cells (~1.3% of observations are settlements)
- Most query budget wasted on static terrain
- Observations carry little signal since so few dynamic cells are seen
- Prior dominates and is reasonably accurate already (73.5 on round 10)

### Warm rounds (expansion > 0.05)
- Many dynamic cells (~16% of observations are settlements)
- Observations carry strong signal
- Prior is already good (88.2 on round 9) — hard to beat

## Iteration Log

| # | Change | R10 Score | R10 Delta | Notes |
|---|---|---:|---:|---|
| 0 | Baseline (v2 ABC) | 73.1 | — | ABC hurts vs prior |
