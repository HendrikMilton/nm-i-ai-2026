# Astar Island Solver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a zero-query Norse civilization simulator that predicts full 40×40 probability maps for all 5 seeds by running Monte Carlo simulations over the parameter space and aggregating results.

**Architecture:** Fetch the initial map state for free via the API, implement the Norse simulator matching the documented mechanics (growth → conflict → trade → winter → environment), then run it thousands of times across sampled hidden parameter combinations. Aggregate per-cell class frequencies into a H×W×6 probability tensor and submit for each seed.

**Tech Stack:** Python 3.11, NumPy (vectorized simulation), requests (API client), scipy (Latin hypercube sampling)

---

## File Structure

```
arian/
├── api_client.py       # REST client: fetch rounds, submit predictions
├── simulator.py        # Norse world simulator — one 50-year run
├── predict.py          # Main pipeline: fetch → Monte Carlo → submit
├── requirements.txt    # requests, numpy, scipy
└── docs/superpowers/plans/  # (this file)
```

---

## Challenge Reference

- **Map:** 40×40 grid, 6 prediction classes (0=Empty/Ocean/Plains, 1=Settlement, 2=Port, 3=Ruin, 4=Forest, 5=Mountain)
- **Grid values in API:** 0=Empty, 1=Settlement, 2=Port, 3=Ruin, 4=Forest, 5=Mountain, 10=Ocean, 11=Plains
- **Mapping:** Ocean(10)→class0, Plains(11)→class0, Empty(0)→class0, Mountain(5)→class5 (static)
- **50 years** per simulation, 5 phases per year: Growth → Conflict → Trade → Winter → Environment
- **Scoring:** entropy-weighted KL divergence. NEVER put 0.0 probability — use 0.01 floor
- **Free endpoint:** `GET /astar-island/rounds/{round_id}` → initial grid + settlements for all seeds
- **Submit:** `POST /astar-island/submit` with `{round_id, seed_index, prediction: H×W×6 float[][][]}`
- **Auth:** Bearer token from `app.ainm.no` login

---

## Task 1: Requirements and API Client

**Files:**
- Create: `arian/requirements.txt`
- Create: `arian/api_client.py`

- [ ] **Step 1: Create requirements.txt**

```
requests
numpy
scipy>=1.7
```

- [ ] **Step 2: Create api_client.py**

```python
"""
API client for Astar Island.
Handles authentication, fetching round data, and submitting predictions.
"""
import os
import requests
import numpy as np

BASE_URL = "https://api.ainm.no/astar-island"


def _headers():
    token = os.environ["AINM_TOKEN"]
    return {"Authorization": f"Bearer {token}"}


def get_round(round_id: str) -> dict:
    """Fetch round details including initial_states for all seeds."""
    resp = requests.get(f"{BASE_URL}/rounds/{round_id}", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def get_active_round() -> dict | None:
    """Return the first active round, or None.
    GET /rounds is a public list endpoint — no query budget consumed.
    """
    resp = requests.get(f"{BASE_URL}/rounds", headers=_headers())
    resp.raise_for_status()
    rounds = resp.json()
    for r in rounds:
        if r["status"] == "active":
            return r
    return None


def submit_prediction(round_id: str, seed_index: int, prediction: np.ndarray) -> dict:
    """
    Submit a H×W×6 prediction tensor for one seed.
    prediction: numpy array shape (H, W, 6), values in [0,1], each row sums to 1.
    """
    payload = {
        "round_id": round_id,
        "seed_index": seed_index,
        "prediction": prediction.tolist(),
    }
    resp = requests.post(f"{BASE_URL}/submit", json=payload, headers=_headers())
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 3: Install requirements**

```bash
cd arian && pip install -r requirements.txt
```

- [ ] **Step 4: Quick smoke test (manual)**

Set `AINM_TOKEN` env var, then run:
```bash
python -c "from api_client import get_active_round; print(get_active_round())"
```
Expected: prints round dict with `status: active` or `None` if no active round.

- [ ] **Step 5: Commit**

```bash
git add arian/requirements.txt arian/api_client.py
git commit -m "feat: add api client for astar island"
```

---

## Task 2: Map Utilities (Grid Parsing)

**Files:**
- Create: `arian/simulator.py` (initial skeleton — grid parsing only)

The initial API response gives us the grid as a 2D list of integers (0,1,2,3,4,5,10,11). We need to:
1. Convert to a NumPy array
2. Identify static cells (mountain=5, ocean=10) — these never change
3. Map API values to our internal representation

- [ ] **Step 1: Create simulator.py with grid parsing**

```python
"""
Norse civilization simulator for Astar Island.
Implements the 5-phase annual cycle for 50 years.
"""
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

# Terrain constants (API grid values)
EMPTY   = 0
SETTLE  = 1
PORT    = 2
RUIN    = 3
FOREST  = 4
MOUNTAIN = 5
OCEAN   = 10
PLAINS  = 11

# Prediction class indices
CLASS_EMPTY    = 0  # Ocean, Plains, Empty
CLASS_SETTLE   = 1
CLASS_PORT     = 2
CLASS_RUIN     = 3
CLASS_FOREST   = 4
CLASS_MOUNTAIN = 5

# Cells that are completely static (never change)
STATIC_CELLS = {MOUNTAIN, OCEAN}

# Map API value → prediction class
API_TO_CLASS = {
    EMPTY:    CLASS_EMPTY,
    SETTLE:   CLASS_SETTLE,
    PORT:     CLASS_PORT,
    RUIN:     CLASS_RUIN,
    FOREST:   CLASS_FOREST,
    MOUNTAIN: CLASS_MOUNTAIN,
    OCEAN:    CLASS_EMPTY,
    PLAINS:   CLASS_EMPTY,
}


def parse_initial_grid(grid_list: list[list[int]]) -> np.ndarray:
    """Convert API grid list to numpy array (H, W) of API values."""
    return np.array(grid_list, dtype=np.int32)


def initial_class_grid(grid: np.ndarray) -> np.ndarray:
    """Convert API grid to prediction class grid (H, W)."""
    out = np.zeros_like(grid)
    for api_val, cls in API_TO_CLASS.items():
        out[grid == api_val] = cls
    return out


def is_static(grid: np.ndarray) -> np.ndarray:
    """Return boolean mask (H, W): True where cell never changes."""
    return (grid == MOUNTAIN) | (grid == OCEAN)
```

- [ ] **Step 2: Verify parsing works (manual check)**

```bash
python -c "
import numpy as np
from simulator import parse_initial_grid, initial_class_grid, is_static
g = [[10,10,0],[0,1,5],[4,11,2]]
arr = parse_initial_grid(g)
print('API grid:', arr)
print('Class grid:', initial_class_grid(arr))
print('Static mask:', is_static(arr))
"
```
Expected: ocean(10)→class0, settlement(1)→class1, mountain(5)→class5 static, forest(4)→class4.

- [ ] **Step 3: Commit**

```bash
git add arian/simulator.py
git commit -m "feat: add grid parsing utilities to simulator"
```

---

## Task 3: Settlement Dataclass and Initialization

**Files:**
- Modify: `arian/simulator.py` (add Settlement and World classes)

- [ ] **Step 1: Add Settlement dataclass and World to simulator.py**

Append to `simulator.py`:

```python
@dataclass
class Settlement:
    x: int
    y: int
    population: float = 3.0
    food: float = 5.0
    wealth: float = 3.0
    defense: float = 2.0
    has_port: bool = False
    alive: bool = True
    owner_id: int = 0
    has_longship: bool = False


@dataclass
class SimParams:
    """Hidden parameters controlling world behavior. Sample these."""
    expansion_rate: float = 0.3        # prob settlement expands to neighbor
    conflict_prob: float = 0.2         # base raid probability
    winter_severity: float = 0.3       # food lost per winter (fraction)
    trade_range: int = 8               # max distance for port trade
    ruin_reclaim_rate: float = 0.3     # prob ruin gets rebuilt by neighbor
    forest_reclaim_rate: float = 0.1   # prob uncontested ruin becomes forest
    longship_prob: float = 0.2         # prob wealthy port builds longship
    longship_range: int = 10           # extra raiding range with longship


@dataclass
class World:
    grid: np.ndarray          # (H, W) current terrain, API values
    settlements: list[Settlement]
    params: SimParams
    rng: np.random.Generator

    @property
    def H(self) -> int:
        return self.grid.shape[0]

    @property
    def W(self) -> int:
        return self.grid.shape[1]

    def land_neighbors(self, x: int, y: int, radius: int = 1) -> list[tuple[int,int]]:
        """Return (x,y) neighbors within radius that are non-ocean, non-mountain."""
        neighbors = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.W and 0 <= ny < self.H:
                    v = self.grid[ny, nx]
                    if v not in (OCEAN, MOUNTAIN):
                        neighbors.append((nx, ny))
        return neighbors

    def adjacent_forest_count(self, x: int, y: int) -> int:
        count = 0
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.W and 0 <= ny < self.H:
                    if self.grid[ny, nx] == FOREST:
                        count += 1
        return count


def build_world(
    grid_list: list[list[int]],
    settlements_data: list[dict],
    params: SimParams,
    rng: np.random.Generator,
) -> World:
    """Construct a World from the API's initial_state data."""
    grid = parse_initial_grid(grid_list)
    settlements = []
    for i, s in enumerate(settlements_data):
        settlements.append(Settlement(
            x=s["x"],
            y=s["y"],
            has_port=s.get("has_port", False),
            alive=s.get("alive", True),
            owner_id=i,
        ))
    return World(grid=grid.copy(), settlements=settlements, params=params, rng=rng)
```

- [ ] **Step 2: Smoke test world construction**

```bash
python -c "
import numpy as np
from simulator import build_world, SimParams
grid = [[10,11,0],[0,1,0],[4,11,2]]
sett = [{'x':1,'y':1,'has_port':False,'alive':True},
        {'x':2,'y':2,'has_port':True,'alive':True}]
w = build_world(grid, sett, SimParams(), np.random.default_rng(42))
print('World H×W:', w.H, w.W)
print('Settlements:', len(w.settlements))
print('Adj forest at (1,1):', w.adjacent_forest_count(1,1))
"
```

- [ ] **Step 3: Commit**

```bash
git add arian/simulator.py
git commit -m "feat: add Settlement, SimParams, World dataclasses"
```

---

## Task 4: Simulator — Growth Phase

**Files:**
- Modify: `arian/simulator.py`

- [ ] **Step 1: Add growth phase**

Append to `simulator.py`:

```python
def phase_growth(world: World) -> None:
    """
    Settlements produce food from adjacent forests.
    Population grows. Ports develop on coast. New settlements founded.
    """
    p = world.params
    rng = world.rng

    for s in world.settlements:
        if not s.alive:
            continue

        # Food production from adjacent forest
        forest_adj = world.adjacent_forest_count(s.x, s.y)
        s.food += 1.0 + 0.5 * forest_adj

        # Population growth
        if s.food > 3.0:
            s.population += 0.2
            s.food -= 0.5

        # Port development along coastline
        if not s.has_port:
            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    nx, ny = s.x + dx, s.y + dy
                    if 0 <= nx < world.W and 0 <= ny < world.H:
                        if world.grid[ny, nx] == OCEAN:
                            if rng.random() < 0.15:
                                s.has_port = True
                                world.grid[s.y, s.x] = PORT
                                break

        # Expansion: found new settlement on adjacent plain/empty
        if s.population > 4.0 and s.food > 4.0:
            if rng.random() < p.expansion_rate:
                candidates = [
                    (nx, ny)
                    for (nx, ny) in world.land_neighbors(s.x, s.y, radius=2)
                    if world.grid[ny, nx] in (EMPTY, PLAINS, RUIN, FOREST)
                ]
                if candidates:
                    nx, ny = candidates[rng.integers(len(candidates))]
                    world.grid[ny, nx] = SETTLE
                    world.settlements.append(Settlement(
                        x=nx, y=ny,
                        population=1.0, food=2.0, wealth=1.0,
                        owner_id=s.owner_id,
                    ))
                    s.food -= 2.0
                    s.population -= 1.0
```

- [ ] **Step 2: Verify growth phase runs without error**

```bash
python -c "
import numpy as np
from simulator import build_world, SimParams, phase_growth
grid = [[10,11,0,10],[11,1,4,10],[4,11,2,10],[10,10,10,10]]
sett = [{'x':1,'y':1,'has_port':False,'alive':True},
        {'x':2,'y':2,'has_port':True,'alive':True}]
w = build_world(grid, sett, SimParams(), np.random.default_rng(42))
phase_growth(w)
print('After growth — food s0:', w.settlements[0].food, 'pop:', w.settlements[0].population)
print('Num settlements:', len(w.settlements))
"
```

- [ ] **Step 3: Commit**

```bash
git add arian/simulator.py
git commit -m "feat: add growth phase to simulator"
```

---

## Task 5: Simulator — Conflict Phase

**Files:**
- Modify: `arian/simulator.py`

- [ ] **Step 1: Add conflict phase**

```python
def phase_conflict(world: World) -> None:
    """
    Settlements raid each other. Desperate ones raid more.
    Longships extend raiding range. Successful raids loot + damage defender.
    """
    p = world.params
    rng = world.rng

    alive = [s for s in world.settlements if s.alive]
    for attacker in alive:
        # Low food → more aggressive
        hunger = max(0.0, 2.0 - attacker.food)
        raid_chance = p.conflict_prob + 0.1 * hunger
        if rng.random() > raid_chance:
            continue

        # Determine raiding range
        max_range = 3 + (p.longship_range if attacker.has_longship else 0)

        # Find targets: enemy settlements in range
        targets = [
            s for s in alive
            if s.owner_id != attacker.owner_id
            and abs(s.x - attacker.x) + abs(s.y - attacker.y) <= max_range
        ]
        if not targets:
            continue

        defender = targets[rng.integers(len(targets))]

        # Combat outcome
        attack_strength = attacker.population * (1 + 0.1 * attacker.wealth)
        defense_strength = defender.population * (1 + defender.defense)

        if attack_strength > defense_strength * rng.uniform(0.5, 1.5):
            # Attacker wins: loot resources
            loot = min(defender.food * 0.3, 3.0)
            attacker.food += loot
            attacker.wealth += loot * 0.5
            defender.food -= loot
            defender.population -= 0.5

            # Sometimes conquer — change allegiance
            if attack_strength > defense_strength * 1.5:
                defender.owner_id = attacker.owner_id
        else:
            # Defender wins
            attacker.population -= 0.3

        # Longship building for wealthy ports
        if attacker.has_port and attacker.wealth > 5.0:
            if rng.random() < p.longship_prob:
                attacker.has_longship = True
```

- [ ] **Step 2: Smoke test conflict phase**

```bash
python -c "
import numpy as np
from simulator import build_world, SimParams, phase_growth, phase_conflict
grid = [[10,11,11,11,10]] * 5
sett = [{'x':1,'y':1,'has_port':False,'alive':True},
        {'x':3,'y':3,'has_port':False,'alive':True}]
w = build_world(grid, sett, SimParams(conflict_prob=1.0), np.random.default_rng(99))
phase_growth(w)
phase_conflict(w)
print('After conflict — pop0:', w.settlements[0].population, 'pop1:', w.settlements[1].population)
"
```

- [ ] **Step 3: Commit**

```bash
git add arian/simulator.py
git commit -m "feat: add conflict phase to simulator"
```

---

## Task 6: Simulator — Trade, Winter, Environment Phases

**Files:**
- Modify: `arian/simulator.py`

- [ ] **Step 1: Add trade phase**

```python
def phase_trade(world: World) -> None:
    """Ports within trade_range that aren't at war exchange food and wealth."""
    p = world.params
    ports = [s for s in world.settlements if s.alive and s.has_port]
    traded = set()
    for i, a in enumerate(ports):
        for j, b in enumerate(ports):
            if i >= j or (i, j) in traded:
                continue
            dist = abs(a.x - b.x) + abs(a.y - b.y)
            if dist <= p.trade_range:
                # Exchange resources
                avg_food = (a.food + b.food) / 2
                avg_wealth = (a.wealth + b.wealth) / 2
                a.food = a.food * 0.7 + avg_food * 0.3 + 0.5
                b.food = b.food * 0.7 + avg_food * 0.3 + 0.5
                a.wealth = a.wealth * 0.7 + avg_wealth * 0.3 + 0.3
                b.wealth = b.wealth * 0.7 + avg_wealth * 0.3 + 0.3
                traded.add((i, j))
```

- [ ] **Step 2: Add winter phase**

```python
def phase_winter(world: World) -> None:
    """All settlements lose food. Starvation causes collapse → Ruin."""
    p = world.params
    rng = world.rng

    severity = p.winter_severity * rng.uniform(0.5, 1.5)

    for s in world.settlements:
        if not s.alive:
            continue
        s.food -= severity * (1.0 + 0.1 * s.population)

        if s.food <= 0 or s.population <= 0:
            # Settlement collapses
            s.alive = False
            s.food = 0
            world.grid[s.y, s.x] = RUIN

            # Disperse survivors to nearby friendly settlements
            friendly = [
                f for f in world.settlements
                if f.alive and f.owner_id == s.owner_id
                and abs(f.x - s.x) + abs(f.y - s.y) <= 5
            ]
            if friendly:
                closest = min(friendly, key=lambda f: abs(f.x - s.x) + abs(f.y - s.y))
                closest.population += max(0, s.population * 0.3)
                closest.food += max(0, s.food * 0.5)
```

- [ ] **Step 3: Add environment phase**

```python
def phase_environment(world: World) -> None:
    """Ruins reclaimed by nearby settlements or reverted to forest/plains."""
    p = world.params
    rng = world.rng
    H, W = world.H, world.W

    ruin_positions = list(zip(*np.where(world.grid == RUIN)))

    for (ry, rx) in ruin_positions:
        alive = [s for s in world.settlements if s.alive]

        # Check if any alive settlement is close enough to reclaim
        nearby = [
            s for s in alive
            if abs(s.x - rx) + abs(s.y - ry) <= 3 and s.food > 3.0
        ]

        if nearby and rng.random() < p.ruin_reclaim_rate:
            patron = min(nearby, key=lambda s: abs(s.x - rx) + abs(s.y - ry))
            # Rebuild as port if coastal, else settlement
            is_coastal = any(
                world.grid[ny, nx] == OCEAN
                for dx in [-1, 0, 1] for dy in [-1, 0, 1]
                if 0 <= (nx := rx + dx) < W and 0 <= (ny := ry + dy) < H
            )
            new_type = PORT if is_coastal else SETTLE
            world.grid[ry, rx] = new_type
            world.settlements.append(Settlement(
                x=rx, y=ry,
                population=patron.population * 0.3,
                food=patron.food * 0.3,
                wealth=patron.wealth * 0.2,
                has_port=(new_type == PORT),
                owner_id=patron.owner_id,
            ))
            patron.food -= patron.food * 0.2
            patron.population -= patron.population * 0.15
        elif rng.random() < p.forest_reclaim_rate:
            world.grid[ry, rx] = FOREST
        elif rng.random() < 0.05:
            world.grid[ry, rx] = EMPTY
```

- [ ] **Step 4: Commit**

```bash
git add arian/simulator.py
git commit -m "feat: add trade, winter, environment phases to simulator"
```

---

## Task 7: Full 50-Year Simulation Loop

**Files:**
- Modify: `arian/simulator.py`

- [ ] **Step 1: Add the main run_simulation function**

```python
def run_simulation(
    grid_list: list[list[int]],
    settlements_data: list[dict],
    params: SimParams,
    rng: np.random.Generator,
    years: int = 50,
) -> np.ndarray:
    """
    Run one full simulation for `years` years.
    Returns final class grid (H, W) of prediction class indices.
    """
    world = build_world(grid_list, settlements_data, params, rng)
    # Save original values of static cells (mountain, ocean) so phases
    # can never accidentally overwrite them.
    static_mask = is_static(world.grid)
    original_grid = world.grid.copy()

    for _ in range(years):
        phase_growth(world)
        phase_conflict(world)
        phase_trade(world)
        phase_winter(world)
        phase_environment(world)
        # Restore static cells after every year — guaranteed invariant
        world.grid[static_mask] = original_grid[static_mask]

    return initial_class_grid(world.grid)
```

- [ ] **Step 2: Run a smoke test — single full simulation**

```bash
python -c "
import numpy as np, time
from simulator import run_simulation, SimParams

# Minimal 10x10 grid
grid = [[10]*10 for _ in range(10)]
for r in range(2,8):
    for c in range(2,8):
        grid[r][c] = 11  # plains
grid[4][4] = 1  # settlement
grid[4][5] = 4  # forest nearby
sett = [{'x':4,'y':4,'has_port':False,'alive':True}]

t0 = time.time()
result = run_simulation(grid, sett, SimParams(), np.random.default_rng(42))
print(f'Sim complete in {time.time()-t0:.3f}s')
print('Unique classes in result:', set(result.flatten().tolist()))
print('Settlement count in result:', (result == 1).sum())
"
```
Expected: completes in <1 second, result contains class 0, 1, and possibly 2/3/4.

- [ ] **Step 3: Commit**

```bash
git add arian/simulator.py
git commit -m "feat: add full 50-year simulation loop"
```

---

## Task 8: Monte Carlo Aggregation

**Files:**
- Modify: `arian/simulator.py` (add monte_carlo function)

- [ ] **Step 1: Add monte_carlo_predict function**

```python
def monte_carlo_predict(
    grid_list: list[list[int]],
    settlements_data: list[dict],
    n_runs: int = 500,
    param_samples: int = 10,
    seed: int = 0,
) -> np.ndarray:
    """
    Run Monte Carlo over both stochastic outcomes and parameter uncertainty.

    - Samples `param_samples` different SimParams from a plausible prior
    - For each param set, runs `n_runs // param_samples` simulations
    - Aggregates all runs → H×W×6 probability tensor

    Returns array shape (H, W, 6) with per-cell class probabilities.
    Applies 0.01 floor and renormalizes to avoid zero-probability KL blowup.
    """
    import scipy.stats

    H = len(grid_list)
    W = len(grid_list[0])
    counts = np.zeros((H, W, 6), dtype=np.float32)

    rng = np.random.default_rng(seed)
    runs_per_param = max(1, n_runs // param_samples)

    # Sample parameter combinations via Latin Hypercube Sampling
    # Parameter ranges based on documented mechanics
    param_ranges = {
        "expansion_rate":     (0.05, 0.60),
        "conflict_prob":      (0.05, 0.50),
        "winter_severity":    (0.10, 0.70),
        "trade_range":        (4,    12),
        "ruin_reclaim_rate":  (0.10, 0.60),
        "forest_reclaim_rate":(0.02, 0.25),
        "longship_prob":      (0.05, 0.40),
        "longship_range":     (5,    15),
    }

    sampler = scipy.stats.qmc.LatinHypercube(d=len(param_ranges), seed=int(rng.integers(2**31)))
    lhs_samples = sampler.random(n=param_samples)
    keys = list(param_ranges.keys())

    for i in range(param_samples):
        # Map [0,1] LHS sample to parameter range
        param_vals = {}
        for j, key in enumerate(keys):
            lo, hi = param_ranges[key]
            val = lo + lhs_samples[i, j] * (hi - lo)
            param_vals[key] = int(round(val)) if key in ("trade_range", "longship_range") else float(val)

        params = SimParams(**param_vals)

        for _ in range(runs_per_param):
            run_seed = int(rng.integers(2**31))
            run_rng = np.random.default_rng(run_seed)
            result = run_simulation(grid_list, settlements_data, params, run_rng)
            # Accumulate class counts
            for cls in range(6):
                counts[:, :, cls] += (result == cls).astype(np.float32)

    # Normalize to probabilities
    total = counts.sum(axis=2, keepdims=True)
    total = np.maximum(total, 1.0)  # avoid divide-by-zero
    probs = counts / total

    # Enforce 0.01 floor + renormalize (critical for KL divergence)
    probs = np.maximum(probs, 0.01)
    probs = probs / probs.sum(axis=2, keepdims=True)

    return probs
```

- [ ] **Step 2: Test Monte Carlo on small grid**

```bash
python -c "
import numpy as np, time
from simulator import monte_carlo_predict

grid = [[10]*8 for _ in range(8)]
for r in range(1,7):
    for c in range(1,7):
        grid[r][c] = 11
grid[3][3] = 1
grid[3][4] = 4
sett = [{'x':3,'y':3,'has_port':False,'alive':True}]

t0 = time.time()
probs = monte_carlo_predict(grid, sett, n_runs=50, param_samples=5, seed=42)
print(f'Monte Carlo complete in {time.time()-t0:.2f}s')
print('Shape:', probs.shape)
print('All probs sum to 1?', np.allclose(probs.sum(axis=2), 1.0, atol=1e-5))
print('Min prob (should be >= 0.01):', probs.min())
print('Settlement cell (3,3) distribution:', probs[3,3].round(3))
"
```
Expected: shape (8,8,6), all rows sum to 1, min ≥ 0.01.

- [ ] **Step 3: Commit**

```bash
git add arian/simulator.py
git commit -m "feat: add monte carlo aggregation with LHS parameter sampling"
```

---

## Task 9: Static Cell Overrides

**Files:**
- Modify: `arian/simulator.py`

Static cells (ocean, mountain) never change. We can override their probabilities with near-certainty before submitting — this costs us nothing and makes those cells perfect.

- [ ] **Step 1: Add static override function**

```python
def apply_static_overrides(
    probs: np.ndarray,
    initial_grid: np.ndarray,
) -> np.ndarray:
    """
    For cells that are provably static (ocean, mountain), override
    probabilities with near-certainty.
    Returns a modified copy of probs.
    """
    probs = probs.copy()

    # Ocean → class 0 (CLASS_EMPTY)
    # Use two separate assignments — combined boolean+integer fancy indexing
    # is fragile across NumPy versions.
    ocean_mask = (initial_grid == OCEAN)
    probs[ocean_mask, :] = 0.01          # all 6 classes → 0.01 (sum = 0.06)
    probs[ocean_mask, CLASS_EMPTY] = 0.95 # dominant class → 0.95 (sum = 1.00)

    # Mountain → class 5 (CLASS_MOUNTAIN)
    mountain_mask = (initial_grid == MOUNTAIN)
    probs[mountain_mask, :] = 0.01
    probs[mountain_mask, CLASS_MOUNTAIN] = 0.95

    # Renormalize (no-op for static cells, safety net for others)
    probs = probs / probs.sum(axis=2, keepdims=True)
    return probs
```

- [ ] **Step 2: Test static overrides**

```bash
python -c "
import numpy as np
from simulator import parse_initial_grid, apply_static_overrides

grid_list = [[10, 11, 5], [11, 1, 11], [10, 4, 10]]
grid = parse_initial_grid(grid_list)
probs = np.ones((3, 3, 6)) / 6  # uniform start

probs = apply_static_overrides(probs, grid)
print('Ocean cell (0,0) class 0 prob:', probs[0,0,0].round(3))   # should be ~0.95
print('Mountain cell (0,2) class 5 prob:', probs[0,2,5].round(3)) # should be ~0.95
print('Settlement cell (1,1):', probs[1,1].round(3))               # unchanged uniform
"
```

- [ ] **Step 3: Commit**

```bash
git add arian/simulator.py
git commit -m "feat: apply static cell overrides for ocean/mountain"
```

---

## Task 10: Main Prediction Pipeline

**Files:**
- Create: `arian/predict.py`

- [ ] **Step 1: Create predict.py**

```python
"""
Main Astar Island prediction pipeline.

Usage:
    AINM_TOKEN=<token> python predict.py --round-id <uuid> [--n-runs 500] [--dry-run]

Steps:
    1. Fetch active round + initial states for all 5 seeds
    2. Run Monte Carlo simulation for each seed
    3. Apply static overrides
    4. Submit predictions (or print stats if --dry-run)
"""
import argparse
import time
import numpy as np
from api_client import get_round, get_active_round, submit_prediction
from simulator import (
    parse_initial_grid,
    monte_carlo_predict,
    apply_static_overrides,
)


def predict_seed(
    initial_state: dict,
    n_runs: int,
    param_samples: int,
    seed: int,
) -> np.ndarray:
    grid_list = initial_state["grid"]
    settlements_data = initial_state["settlements"]

    print(f"  Running {n_runs} simulations ({param_samples} param sets × {n_runs // param_samples} runs each)...")
    t0 = time.time()
    probs = monte_carlo_predict(
        grid_list,
        settlements_data,
        n_runs=n_runs,
        param_samples=param_samples,
        seed=seed,
    )
    print(f"  Monte Carlo done in {time.time() - t0:.1f}s")

    grid = parse_initial_grid(grid_list)
    probs = apply_static_overrides(probs, grid)

    return probs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-id", help="Round UUID (uses active round if omitted)")
    parser.add_argument("--n-runs", type=int, default=500, help="Total simulation runs per seed")
    parser.add_argument("--param-samples", type=int, default=10, help="Parameter combinations to sample")
    parser.add_argument("--dry-run", action="store_true", help="Print stats without submitting")
    args = parser.parse_args()

    # Fetch round
    if args.round_id:
        round_data = get_round(args.round_id)
    else:
        round_data = get_active_round()
        if round_data is None:
            print("No active round found.")
            return
        round_data = get_round(round_data["id"])

    round_id = round_data["id"]

    # Defensive field access — print keys on failure to aid debugging
    if "initial_states" not in round_data:
        print(f"ERROR: 'initial_states' not in round response. Keys: {list(round_data.keys())}")
        return
    initial_states = round_data["initial_states"]
    n_seeds = round_data.get("seeds_count", len(initial_states))

    print(f"Round {round_data['round_number']} ({round_id})")
    print(f"Map: {round_data['map_width']}×{round_data['map_height']}, {n_seeds} seeds")

    for seed_index in range(n_seeds):
        print(f"\n[Seed {seed_index}]")
        initial_state = initial_states[seed_index]
        probs = predict_seed(
            initial_state,
            n_runs=args.n_runs,
            param_samples=args.param_samples,
            seed=seed_index * 1000,  # decorrelated seeds per run; 0 for seed 0 is intentional
        )

        print(f"  Prediction shape: {probs.shape}")
        print(f"  Min prob: {probs.min():.4f}, Max prob: {probs.max():.4f}")
        print(f"  Sums to 1: {np.allclose(probs.sum(axis=2), 1.0, atol=1e-4)}")

        if not args.dry_run:
            print(f"  Submitting...")
            result = submit_prediction(round_id, seed_index, probs)
            print(f"  Submitted: {result}")
        else:
            print(f"  [dry-run] Would submit seed {seed_index}")

    print("\nDone.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test dry-run (no actual submission)**

Set `AINM_TOKEN` env var, then:
```bash
cd arian
AINM_TOKEN=<your_token> python predict.py --dry-run --n-runs 100 --param-samples 5
```
Expected: prints round info, runs simulations for each seed, prints shape/stats, does not call submit.

- [ ] **Step 3: Commit**

```bash
git add arian/predict.py
git commit -m "feat: add main prediction pipeline (predict.py)"
```

---

## Task 11: Full Run and Submit

- [ ] **Step 1: Run full prediction with 500 simulations per seed**

```bash
cd arian
AINM_TOKEN=<your_token> python predict.py --n-runs 500 --param-samples 10
```

Monitor output: each seed should take ~10–60 seconds depending on machine.

- [ ] **Step 2: If running on GCP L4 GPU — increase n-runs**

The GCP L4 is available at `35.205.29.3`. To run remotely with more iterations:
```bash
# Copy code to GCP
gcloud compute scp --recurse arian/ nm-ai-2026:~/astar/ --zone europe-west1-c

# SSH and run
gcloud compute ssh nm-ai-2026 --zone europe-west1-c
cd ~/astar && pip install -r requirements.txt
AINM_TOKEN=<token> python predict.py --n-runs 5000 --param-samples 50
```

- [ ] **Step 3: Verify submission on leaderboard**

```bash
AINM_TOKEN=<token> python -c "
from api_client import _headers
import requests
resp = requests.get('https://api.ainm.no/astar-island/my-rounds', headers=_headers())
import json; print(json.dumps(resp.json(), indent=2))
"
```

---

## Iteration Notes

After first submission, iterate to improve score:

1. **Increase n-runs**: More simulations → smoother distributions → lower KL
2. **Tune parameter prior**: If early results show under/over-prediction of settlements, adjust `expansion_rate` and `conflict_prob` ranges
3. **Use actual queries** (if budget permits): Observe a few cells, compare to simulator predictions, identify where simulator diverges and adjust params
4. **Per-cell calibration**: For cells with very high/low entropy in predictions, consider adding a temperature parameter to sharpen/soften distributions

---

## Quick Reference

```bash
# Dry run (no submission)
AINM_TOKEN=xxx python predict.py --dry-run --n-runs 100 --param-samples 5

# Full run (submits all 5 seeds)
AINM_TOKEN=xxx python predict.py --n-runs 500 --param-samples 10

# Specific round
AINM_TOKEN=xxx python predict.py --round-id <uuid> --n-runs 1000 --param-samples 20

# Check your scores
python -c "from api_client import _headers; import requests,json; print(json.dumps(requests.get('https://api.ainm.no/astar-island/my-rounds',headers=_headers()).json(),indent=2))"
```
