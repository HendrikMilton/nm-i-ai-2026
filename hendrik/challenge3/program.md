# Challenge 3 — Astar Island: Viking Civilisation Prediction

## Task
Predict probability distributions of terrain types on a 40x40 grid after a 50-year Norse civilization simulation. Submit H×W×6 probability tensors for 5 seeds per round. Scored by entropy-weighted KL divergence.

## API
- Base URL: `https://api.ainm.no/astar-island`
- Auth: `Authorization: Bearer <token>` or cookie `access_token`
- `GET /rounds` — list rounds
- `GET /rounds/{round_id}` — round details + initial states (free, no query cost)
- `GET /budget` — check remaining queries
- `POST /simulate` — observe one stochastic sim through viewport (costs 1 query)
- `POST /submit` — submit prediction tensor for one seed
- `GET /my-rounds` — your scores, ranks, budget
- `GET /analysis/{round_id}/{seed_index}` — post-round ground truth comparison

## Grid terrain types → 6 prediction classes
| Code | Terrain    | Class |
|------|-----------|-------|
| 10   | Ocean     | 0 (Empty) |
| 11   | Plains    | 0 (Empty) |
| 0    | Empty     | 0 |
| 1    | Settlement| 1 |
| 2    | Port      | 2 |
| 3    | Ruin      | 3 |
| 4    | Forest    | 4 |
| 5    | Mountain  | 5 |

## Simulation mechanics (50 years, phases per year)
1. **Growth** — settlements produce food from adjacent terrain, grow population, develop ports on coasts, build longships, expand by founding new settlements
2. **Conflict** — settlements raid each other, longships extend range, desperate settlements raid more, conquered settlements change faction
3. **Trade** — ports within range trade if not at war, generates wealth/food, tech diffuses
4. **Winter** — varying severity, all lose food, settlements can collapse → Ruin
5. **Environment** — ruins reclaimed by nearby settlements or overtaken by forest

## Key constraints
- 50 queries per round shared across all 5 seeds
- Each query: max 15×15 viewport of 40×40 map
- Each query runs a NEW stochastic sim (different outcome each time)
- Initial grid is free (GET round details)

## Scoring
- `KL(ground_truth || prediction)` weighted by cell entropy
- `score = max(0, min(100, 100 * exp(-3 * weighted_kl)))`
- Only dynamic cells matter (static ocean/mountain/forest excluded by entropy weighting)
- **NEVER use 0.0 probability** — floor at 0.01 and renormalize
- Round score = average of 5 seed scores

## Training data available
`../elias/logs/` contains past round data:
- `rounds/` — query logs (viewport observations) per round
- `offline/` — backtests with ground truth, predictions, configs, scores
  - Each file has: `seeds[i].initial_grid`, `seeds[i].ground_truth` (40×40×6), `seeds[i].prediction`, `seeds[i].queries`
  - Multiple config experiments with scores (sim_weight, prior_weight, obs_weight tuning)

## Strategy
1. **Static cells are free** — ocean, mountain, isolated forest → deterministic, assign ~1.0 prob
2. **Train a small CNN (U-Net style)** on initial_grid → ground_truth using past round data
   - Input: one-hot terrain channels + derived features (coast distance, settlement proximity, forest adjacency)
   - Output: 40×40×6 softmax probabilities
   - Loss: KL divergence (matches scoring)
3. **Use queries strategically** — observe settlement-dense regions, aggregate stochastic outcomes
4. **Blend CNN + observations** — CNN as prior, update with empirical frequencies from queries
5. **Always floor probabilities at 0.01 and renormalize**

## Training data details
- Location: `../../elias/logs/offline/` — JSON files with backtests
- Each file contains `seeds` dict with keys "0"-"4", each having:
  - `initial_grid` — 40×40 int array (terrain codes: 0,1,2,3,4,5,10,11)
  - `ground_truth` — 40×40×6 float array (probability distribution per cell)
  - `prediction`, `obs_score`, `prior_score`, `queries`
- **Input:** `initial_grid` → one-hot encode terrain types into channels
- **Target:** `ground_truth` → 40×40×6 probability tensor
- ~6 rounds × 5 seeds = ~30 samples. Use rotations/flips for augmentation.

## Eval / Validation
- Split past rounds: train on N-1 rounds, validate on 1 (leave-one-round-out)
- Validation metric: entropy-weighted KL divergence (same as competition scoring)
- Score formula: `score = max(0, min(100, 100 * exp(-3 * weighted_kl)))`
- Compute per-cell entropy from ground truth, weight KL by it, average
- Report score per seed and mean across seeds

## Model checkpoints (Hugging Face)
Trained LightGBM models are uploaded to: https://huggingface.co/SaulGoodmens/nm-ai-astar
- `checkpoints/` — latest production models
- `checkpoints_v2/` — v2 models with expanded features
- `checkpoints_v3/` — v3 models with additional tuning

## Files
- `solve.py` — all logic here
- `main.py` — FastAPI wrapper (DO NOT MODIFY)
