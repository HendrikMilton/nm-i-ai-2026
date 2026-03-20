# Astar Island — Viking Civilisation Prediction

## What is this?

Astar Island is a machine learning challenge in NM i AI 2026 where you observe a black-box Norse civilisation simulator through a limited viewport and predict the final world state. The simulator runs a procedurally generated Norse world for **50 years** — settlements grow, factions clash, trade routes form, alliances shift, forests reclaim ruins, and harsh winters reshape entire civilisations.

**Goal:** Observe, learn the world's hidden rules, and predict the probability distribution of terrain types across the entire map.

- **Task type**: Observation + probabilistic prediction
- **Platform**: [app.ainm.no](https://app.ainm.no)
- **API**: REST endpoints at `https://api.ainm.no/astar-island/`

---

## How It Works

1. **A round starts** — the admin creates a round with a fixed map, many hidden parameters, and 5 random seeds
2. **Observe through a viewport** — call `POST /astar-island/simulate` with viewport coordinates to observe one stochastic run through a window (max 15x15 cells). You have **50 queries total** per round, shared across all 5 seeds.
3. **Learn the hidden rules** — analyze viewport observations to understand the forces that govern the world
4. **Generate predictions** — use your understanding to build probability distributions for the full map
5. **Submit predictions** — for each of the 5 seeds, submit a W x H x 6 probability tensor predicting terrain type probabilities per cell
6. **Scoring** — your prediction is compared against the ground truth using entropy-weighted KL divergence

---

## The World

The world is a rectangular grid (default **40x40**) with 8 terrain types that map to **6 prediction classes**:

| Internal Code | Terrain    | Class Index | Description                          |
|---------------|------------|-------------|--------------------------------------|
| 10            | Ocean      | 0 (Empty)   | Impassable water, borders the map    |
| 11            | Plains     | 0 (Empty)   | Flat land, buildable                 |
| 0             | Empty      | 0           | Generic empty cell                   |
| 1             | Settlement | 1           | Active Norse settlement              |
| 2             | Port       | 2           | Coastal settlement with harbour      |
| 3             | Ruin       | 3           | Collapsed settlement                 |
| 4             | Forest     | 4           | Provides food to adjacent settlements|
| 5             | Mountain   | 5           | Impassable terrain                   |

- Ocean, Plains, and Empty all map to **class 0** in predictions
- Mountains are static (never change)
- Forests are mostly static but can reclaim ruined land
- The interesting cells are those that can become Settlements, Ports, or Ruins

---

## Map Generation

Each map is procedurally generated from a **map seed**:

- **Ocean borders** surround the map
- **Fjords** cut inland from random edges
- **Mountain chains** form via random walks
- **Forest patches** cover land with clustered groves
- **Initial settlements** placed on land cells, spaced apart

The map seed is visible to you — you can reconstruct the initial terrain layout locally.

---

## Simulation Phases (per year, for 50 years)

### 1. Growth
Settlements produce food based on adjacent terrain. When conditions are right, settlements grow in population, develop ports along coastlines, and build longships for naval operations. Prosperous settlements expand by founding new settlements on nearby land.

### 2. Conflict
Settlements raid each other. Longships extend raiding range significantly. Desperate settlements (low food) raid more aggressively. Successful raids loot resources and damage the defender. Sometimes, conquered settlements change allegiance to the raiding faction.

### 3. Trade
Ports within range of each other can trade if not at war. Trade generates wealth and food for both parties, and technology diffuses between trading partners.

### 4. Winter
Each year ends with a winter of varying severity. All settlements lose food. Settlements can collapse from starvation, sustained raids, or harsh winters — becoming **Ruins** and dispersing population to nearby friendly settlements.

### 5. Environment
The natural world slowly reclaims abandoned land. Nearby thriving settlements may reclaim and rebuild ruined sites, establishing new outposts that inherit a portion of their patron's resources and knowledge. Coastal ruins can even be restored as ports. If no settlement steps in, ruins are eventually overtaken by forest growth or fade back into open plains.

---

## Settlement Properties

Each settlement tracks: position, population, food, wealth, defense, tech level, port status, longship ownership, and faction allegiance (owner_id).

- Initial states expose settlement positions and port status only
- Internal stats (population, food, wealth, defense) are only visible through simulation queries

---

## Key Constraints

| Concept            | Description                                                      |
|--------------------|------------------------------------------------------------------|
| **Map seed**       | Determines terrain layout (fixed per seed, visible to you)       |
| **Sim seed**       | Random seed for each simulation run (different every query)      |
| **Hidden params**  | Values controlling the world's behavior (same for all seeds)     |
| **50 queries**     | Your budget per round, shared across all 5 seeds                 |
| **Viewport**       | Each query reveals a max 15x15 window of the map                 |
| **W x H x 6 tensor** | Your prediction — probability of each of 6 terrain classes per cell |
| **50 years**       | Each simulation runs for 50 time steps                           |
| **Stochastic**     | The same map and parameters produce different outcomes every run  |

---

## API Endpoints

| Method | Path                                            | Auth   | Description                          |
|--------|-------------------------------------------------|--------|--------------------------------------|
| `GET`  | `/astar-island/rounds`                          | Public | List all rounds                      |
| `GET`  | `/astar-island/rounds/{round_id}`               | Public | Round details + initial states       |
| `GET`  | `/astar-island/budget`                          | Team   | Query budget for active round        |
| `POST` | `/astar-island/simulate`                        | Team   | Observe one simulation through viewport |
| `POST` | `/astar-island/submit`                          | Team   | Submit prediction tensor             |
| `GET`  | `/astar-island/my-rounds`                       | Team   | Rounds with your scores, rank, budget|
| `GET`  | `/astar-island/my-predictions/{round_id}`       | Team   | Your predictions with argmax/confidence |
| `GET`  | `/astar-island/analysis/{round_id}/{seed_index}`| Team   | Post-round ground truth comparison   |
| `GET`  | `/astar-island/leaderboard`                     | Public | Astar Island leaderboard             |

### Authentication

All team endpoints require JWT authentication via either:
- **Cookie:** `access_token` JWT cookie (set when you log in at app.ainm.no)
- **Bearer token:** `Authorization: Bearer <token>` header

### Rate Limits

| Endpoint         | Limit                        |
|------------------|------------------------------|
| `POST /simulate` | 5 requests/second per team   |
| `POST /submit`   | 2 requests/second per team   |

### Simulate Request

```json
{
  "round_id": "uuid-of-active-round",
  "seed_index": 3,
  "viewport_x": 10,
  "viewport_y": 5,
  "viewport_w": 15,
  "viewport_h": 15
}
```

- `seed_index`: 0–4
- `viewport_w` / `viewport_h`: 5–15

### Simulate Response

Returns the viewport grid (terrain after 50-year simulation), settlements within the viewport with full stats (population, food, wealth, defense, has_port, alive, owner_id), and remaining query budget.

### Submit Request

```json
{
  "round_id": "uuid",
  "seed_index": 0,
  "prediction": [[[p_empty, p_settlement, p_port, p_ruin, p_forest, p_mountain], ...], ...]
}
```

- `prediction`: H x W x 6 tensor where each cell's 6 probabilities must sum to 1.0
- All probabilities must be non-negative

---

## Scoring

### Ground Truth

For each seed, organizers pre-compute ground truth by running the simulation **hundreds of times** with the true hidden parameters. This produces a probability distribution for each cell.

### KL Divergence

```
KL(p || q) = sum( p_i * log(p_i / q_i) )
```

Where `p` = ground truth, `q` = your prediction. Lower KL = better match.

### Entropy Weighting

Only **dynamic cells** (those that change between simulation runs) contribute to your score, weighted by their entropy:

```
entropy(cell) = -sum( p_i * log(p_i) )
```

Cells with higher entropy (more uncertain outcomes) count more toward your score.

### Final Score Formula

```
weighted_kl = sum( entropy(cell) * KL(ground_truth[cell], prediction[cell]) )
              / sum( entropy(cell) )

score = max(0, min(100, 100 * exp(-3 * weighted_kl)))
```

- **100** = perfect prediction
- **0** = terrible prediction

### Per-Round and Leaderboard Scoring

- **Round score** = average of 5 per-seed scores (unsubmitted seeds score 0)
- **Leaderboard score** = best round score of all time (weighted by round weight)
- **Hot streak score** = average of last 3 rounds

### Round Timing

Each round has a **prediction window** (typically 2 hours 45 minutes). After it closes, submissions are scored and the leaderboard updates.

### Round Status Flow

`pending` → `active` → `scoring` → `completed`

---

## Critical Tips

1. **Never assign probability 0.0 to any class.** If the ground truth has `p_i > 0` but your prediction has `q_i = 0`, KL divergence goes to **infinity**. Always enforce a minimum floor of **0.01** per class and renormalize:
   ```python
   prediction = np.maximum(prediction, 0.01)
   prediction = prediction / prediction.sum(axis=-1, keepdims=True)
   ```

2. **Always submit for every seed** — even a uniform prediction beats scoring 0.

3. **Be strategic with your 50 queries** — they're shared across all 5 seeds and each only reveals a 15x15 window of a 40x40 map.

4. **The simulation is stochastic** — the same map and parameters produce different outcomes every run. Multiple observations of the same area help estimate probabilities.
