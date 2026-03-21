# Scoring Analysis Across Rounds

Analysis of prediction scoring vs observation quality, round weights, and warm/cold dynamics.

## Summary Table

| Round | Weight | Score | Rank | Method | Expansion Rate | Dynamic Cells Observed | Warmth |
|---:|---:|---:|---:|---|---:|---:|---|
| 2 | 1.10 | 33.6 | 109/153 | early | ? | 0 (no queries logged) | ? |
| 3 | 1.16 | 0.3 | 100/100 | early | ? | minimal | ? |
| 5 | 1.28 | 25.0 | 120/144 | early | ? | some | ? |
| 6 | 1.34 | 61.4 | 78/186 | simulator_v5 | ? | 0 (sim only) | ? |
| 7 | 1.41 | 12.3 | 182/199 | obs_sim_prior_v5 | 0.172 | ~37/query | warm |
| 8 | 1.48 | 77.3 | 73/214 | v6_kt | ? | imported external | ? |
| 9 | 1.55 | 86.7 | 57/221 | obs_sim_prior_v5 | 0.154 | 1814 (16.1%) | warm |
| 10 | 1.63 | 76.1 | 84/238 | obs_sim_prior_v5 | 0.011 | 141 (1.3%) | cold |

## Key Findings

### 1. Cold vs warm rounds are the dominant factor

Round 10 had the highest weight (1.63) but scored 10.6 points lower than round 9 (weight 1.55). The difference: round 10 was **cold** (expansion_rate=0.011) while round 9 was **warm** (0.154). In cold rounds, only 1.3% of observed cells were dynamic (settlements/ports/ruins) vs 16.1% in warm rounds. With so few dynamic observations, the system has almost no real signal about the cells that matter for scoring.

### 2. Observation quality directly correlates with score

- **Round 9 (86.7):** 1,814 dynamic cells observed — rich signal for settlement patterns
- **Round 10 (76.1):** 141 dynamic cells observed — 13x less signal, mostly static terrain
- The scoring function *only cares about dynamic cells* (high entropy), so observing forests and plains is essentially wasted budget

### 3. Observation weight (equiv_samples) matters more on information-poor rounds

Sweep results from offline backtests on rounds 7, 8, 9:

| equiv_samples | Round 7 | Round 8 | Round 9 |
|---:|---:|---:|---:|
| 10 | **63.6** | 84.3 | 86.0 |
| 20 | 62.7 | 85.1 | 87.5 |
| 30 | 61.9 | **85.2** | 87.8 |
| 40 | 61.4 | 85.2 | **87.9** |
| 60 (old default) | 60.7 | 85.1 | 87.8 |

When observations are sparse and noisy (round 7), trusting them more (lower equiv_samples) has a bigger impact (+3 points). When observations are rich (round 9), it barely matters. Default was updated from 60 → 18, adaptive range from 20–100 → 8–30.

### 4. Round 7 logging anomaly

Local scoring of logged round 7 predictions gives ~61 per seed, but the API returned 43.8/4.7/4.8/3.9/4.4. The predictions that were actually submitted appear to differ from what was logged — possibly a bug in the logging at that code version, or the predictions were rebuilt after logging.

### 5. Round weight increases ~0.07/round

Later rounds count more toward the leaderboard. Since the code has been improving (round 6→8→9 trending up), the increasing weight works in our favor — but a bad cold round at high weight (like round 10 at 1.63) hurts disproportionately.

## Biggest Improvement Opportunity

The largest lever is **how the system handles cold rounds**. When expansion is low, almost all query budget is wasted on static cells. A smarter query strategy for cold rounds — e.g., focusing viewports tightly around initial settlements, or running more observations on fewer seeds — could improve cold round scores more than any weight tuning.

## Actionable Improvements

### 1. Smarter query allocation for cold rounds

Currently, phase 1 tiles the entire map uniformly for every seed. On cold rounds, most of those viewports observe only static terrain (plains, forest, ocean) — wasted budget.

**Approach:** After phase 1 observes seed 0, check the expansion rate. If cold (< 0.05), skip full-coverage tiling for remaining seeds and instead concentrate viewports on cells within distance 1–2 of initial settlements. This is where the few dynamic cells will be, and multiple observations of these cells would give much better probability estimates for the high-entropy cells that drive the score.

### 2. Adaptive viewport sizing for cold rounds

On cold rounds, settlements barely expand — dynamic activity is concentrated in a small area around initial positions. Using smaller viewports (e.g., 8x8 instead of 15x15) centered on settlement clusters would allow more targeted observations within the same budget, getting multiple observations per dynamic cell rather than one observation of mostly empty terrain.

### 3. Per-seed budget allocation based on early signal

Currently budget is split roughly evenly (9–14 queries per seed). If early observations of a seed show very low expansion, fewer additional queries are needed (the prior is already close to correct). Reallocate that budget to seeds showing more dynamic activity where extra observations would reduce prediction uncertainty.

### 4. Cold round prior calibration

The warm/cold threshold (0.05) switches between two prior tables. On round 10, the expansion rate was 0.011 — deep cold. The cold prior table may not be well-calibrated for this extreme. Consider a more granular approach: scale settlement probability continuously with observed expansion rate rather than a binary warm/cold switch.

### 5. Resubmission strategy

The auto_submit loop now runs continuously. On later iterations within the same round, the system could use cached observations plus additional queries (if budget remains) to refine predictions. Currently it reuses cached queries but doesn't adapt the prediction strategy based on what was already submitted.

## Observation Breakdown: Round 9 (warm) vs Round 10 (cold)

| Terrain | Round 9 | Round 10 |
|---|---:|---:|
| Settlement | 13.8% | 1.0% |
| Port | 0.7% | 0.0% |
| Ruin | 1.6% | 0.2% |
| Forest | 22.2% | 25.2% |
| Mountain | 1.8% | 1.8% |
| Ocean | 3.8% | 2.8% |
| Plains | 56.0% | 68.9% |
| **Dynamic total** | **16.1%** | **1.3%** |
