# Astar Island — Strategy

## Results History

| Round | Strategy | Score | Rank |
|-------|----------|-------|------|
| R3    | v1 (1 obs/cell, deterministic) | 0.26 | 100/100 |
| R5    | v2 (focus seeds + cross-seed avg) | 25.0 | 120/144 |

## v3 Strategy — Conservative Priors + Targeted Observations

### Key Lessons

1. Each seed has a **different map** — never share observations across seeds
2. Priors alone score **55-85** — observations only help if we have enough (>=3) to beat the prior
3. 1-2 observations per cell add **noise that hurts** more than helps
4. Cross-seed averaging is **catastrophically wrong** (destroyed seeds 2-4 in R5)

### Approach

**Priors are the backbone.** Learned from R1-R4 ground truth, they give a smooth probability distribution per cell based on initial terrain type. They're never wrong by more than ~0.2 KL.

**Observations are surgical.** Only used when we can get >= 3 observations per cell on the same seed, which gives enough signal to improve on the prior. Otherwise, prior is used unchanged.

### Query Budget Allocation (50 total)

- Calculate how many seeds we can observe with >= 3 repeats per dynamic viewport
- With 9 dynamic viewports: 9 × 3 = 27 queries per seed → observe 1 seed (5+ repeats)
- With 5 dynamic viewports: 5 × 3 = 15 queries per seed → observe 3 seeds (3+ repeats)
- Unobserved seeds: pure priors (reliable 55-85 baseline)
- Observed seeds: priors blended with empirical observations (should score higher)

### Prediction Pipeline

1. Fetch round data → get **per-seed** initial grids
2. Identify dynamic viewports (containing settlements/ports/ruins)
3. Allocate budget: maximize seeds observed at >= 3 repeats
4. For each cell:
   - **< 3 observations**: pure prior from initial terrain type
   - **>= 3 observations**: blend empirical counts with prior (pseudo-count=3)
5. Floor all probabilities at 0.01, renormalize
6. Submit all 5 seeds

### Backtest Scores (prior-only floor)

| Round | Avg Score |
|-------|-----------|
| R2    | 69.5      |
| R3    | 54.9      |
| R4    | 85.4      |
| R5    | 63.8      |
