# Astar Island — Strategy (v1)

## Query Budget Allocation (50 total)

- 9 viewports tile the full 40x40 map with 15x15 windows (3x3 grid)
- 9 queries × 5 seeds = **45 queries** for one full observation pass per seed
- Remaining **5 queries** used for extra observations on seed 0 (center, corners) to get better probability estimates on dynamic cells

## Prediction Pipeline

1. Fetch active round + initial state to identify **static cells** (mountains, forests, ocean) — these get one-hot predictions for free
2. Tile each seed's map with viewports, counting terrain class occurrences per cell
3. Convert counts to empirical probability distributions
4. Unobserved dynamic cells fall back to uniform
5. Apply `floor_and_normalize` (min 0.01 per class) to avoid KL divergence going to infinity
6. Submit all 5 seeds
