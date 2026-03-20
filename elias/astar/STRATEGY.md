# Astar Island — Strategy

## v1 Results (Round 3)

- Score: 0.26/100, Rank: 100/100
- Problem: 1 observation per cell per seed = deterministic guess, KL divergence punishes hard
- 89.7% of cells are deterministic (static terrain) — we get those free
- The 10.3% uncertain cells (Forest/Empty boundaries, Settlement dynamics) are what matter
- Biggest errors: predicting 95% for one class when truth is ~64/29 split

## v2 Strategy — Repeat Observations

### Key Insight

Since each simulate call is stochastic (different random seed each time), observing the
same viewport multiple times on the same seed gives us different outcomes. Counting
occurrences gives us empirical probability distributions — exactly what we need.

### Query Budget Allocation (50 total)

- **2 focus seeds** get heavy observation: ~22 queries each (44 total)
  - 9 queries for full map tiling (coverage)
  - 13 queries for repeat observations of dynamic areas
- **3 remaining seeds** get 2 queries each (6 total) for partial coverage
- All 5 seeds share the same initial map, so cross-seed observations help

### How to pick repeat observation targets

1. First pass: tile the map (9 queries) to identify which cells are dynamic
2. Second pass: re-observe viewports that contained settlements/ports/ruins
3. Dynamic cells near forests/settlements are the most uncertain

### Prediction improvements

- **Static cells** (ocean, mountain): one-hot prediction (same as v1)
- **Forest cells from initial state**: mostly static, but can be reclaimed — use a prior
  like 85% forest / 14% empty / 1% other instead of 100% forest
- **Observed dynamic cells with N>1 observations**: empirical frequency
- **Observed dynamic cells with N=1**: blend with a prior based on initial terrain
  (e.g., if initial state was Settlement, predict ~40% settlement / 30% ruin / 20% empty / 10% port)
- **Unobserved seeds**: copy probability distribution from observed seeds
  (all seeds share the same hidden parameters, just different random outcomes)
- **Floor**: 0.01 minimum per class, renormalize
