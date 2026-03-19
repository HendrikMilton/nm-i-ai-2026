"""
Norse civilization simulator for Astar Island.
Implements the 5-phase annual cycle for 50 years.

Phases per year: Growth → Conflict → Trade → Winter → Environment
"""
import numpy as np
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Terrain constants (API grid values)
# ---------------------------------------------------------------------------
EMPTY    = 0
SETTLE   = 1
PORT     = 2
RUIN     = 3
FOREST   = 4
MOUNTAIN = 5
OCEAN    = 10
PLAINS   = 11

# Prediction class indices
CLASS_EMPTY    = 0  # Ocean, Plains, Empty
CLASS_SETTLE   = 1
CLASS_PORT     = 2
CLASS_RUIN     = 3
CLASS_FOREST   = 4
CLASS_MOUNTAIN = 5

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


# ---------------------------------------------------------------------------
# Grid utilities
# ---------------------------------------------------------------------------

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
    """Return boolean mask (H, W): True where cell never changes (ocean, mountain)."""
    return (grid == MOUNTAIN) | (grid == OCEAN)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

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
    """Hidden parameters controlling world behavior. These are sampled during Monte Carlo."""
    expansion_rate: float = 0.3        # prob settlement expands to neighbor each year
    conflict_prob: float = 0.2         # base raid probability per settlement per year
    winter_severity: float = 0.3       # mean food lost per settlement per winter
    trade_range: int = 8               # max manhattan distance for port trade
    ruin_reclaim_rate: float = 0.3     # prob a ruin gets rebuilt by a nearby settlement
    forest_reclaim_rate: float = 0.1   # prob an uncontested ruin becomes forest
    longship_prob: float = 0.2         # prob a wealthy port builds a longship
    longship_range: int = 10           # extra raiding range granted by longship


@dataclass
class World:
    grid: np.ndarray           # (H, W) current terrain, API values
    settlements: list          # list[Settlement]
    params: SimParams
    rng: np.random.Generator

    @property
    def H(self) -> int:
        return self.grid.shape[0]

    @property
    def W(self) -> int:
        return self.grid.shape[1]

    def land_neighbors(self, x: int, y: int, radius: int = 1) -> list[tuple[int, int]]:
        """Return (x, y) neighbors within manhattan radius that are non-ocean, non-mountain."""
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


# ---------------------------------------------------------------------------
# Simulation phases
# ---------------------------------------------------------------------------

def phase_growth(world: World) -> None:
    """
    Settlements produce food from adjacent forests.
    Population grows. Ports develop on coastlines. New settlements founded.
    """
    p = world.params
    rng = world.rng

    for s in list(world.settlements):
        if not s.alive:
            continue

        # Food production: base + bonus per adjacent forest
        forest_adj = world.adjacent_forest_count(s.x, s.y)
        s.food += 1.0 + 0.5 * forest_adj

        # Population growth when well-fed
        if s.food > 3.0:
            s.population += 0.2
            s.food -= 0.5

        # Port development when adjacent to ocean
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
                if s.has_port:
                    break

        # Expansion: found new settlement on adjacent open land
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


def phase_conflict(world: World) -> None:
    """
    Settlements raid each other. Desperate (low-food) ones raid more aggressively.
    Longships extend raiding range. Successful raids loot resources; may conquer.
    """
    p = world.params
    rng = world.rng

    alive = [s for s in world.settlements if s.alive]
    for attacker in alive:
        # Hunger increases aggression
        hunger = max(0.0, 2.0 - attacker.food)
        raid_chance = p.conflict_prob + 0.1 * hunger
        if rng.random() > raid_chance:
            continue

        # Raiding range extended by longship
        max_range = 3 + (p.longship_range if attacker.has_longship else 0)

        targets = [
            s for s in alive
            if s.owner_id != attacker.owner_id
            and abs(s.x - attacker.x) + abs(s.y - attacker.y) <= max_range
        ]
        if not targets:
            continue

        defender = targets[rng.integers(len(targets))]

        attack_strength = attacker.population * (1 + 0.1 * attacker.wealth)
        defense_strength = defender.population * (1 + defender.defense)

        if attack_strength > defense_strength * rng.uniform(0.5, 1.5):
            loot = min(defender.food * 0.3, 3.0)
            attacker.food += loot
            attacker.wealth += loot * 0.5
            defender.food -= loot
            defender.population -= 0.5

            # Decisive victory → conquer
            if attack_strength > defense_strength * 1.5:
                defender.owner_id = attacker.owner_id
        else:
            attacker.population -= 0.3

        # Wealthy ports build longships
        if attacker.has_port and attacker.wealth > 5.0:
            if rng.random() < p.longship_prob:
                attacker.has_longship = True


def phase_trade(world: World) -> None:
    """Ports within trade_range that aren't at war exchange food and wealth."""
    p = world.params
    ports = [s for s in world.settlements if s.alive and s.has_port]
    traded: set[tuple[int, int]] = set()

    for i, a in enumerate(ports):
        for j, b in enumerate(ports):
            if i >= j or (i, j) in traded:
                continue
            dist = abs(a.x - b.x) + abs(a.y - b.y)
            if dist <= p.trade_range:
                avg_food = (a.food + b.food) / 2
                avg_wealth = (a.wealth + b.wealth) / 2
                a.food = a.food * 0.7 + avg_food * 0.3 + 0.5
                b.food = b.food * 0.7 + avg_food * 0.3 + 0.5
                a.wealth = a.wealth * 0.7 + avg_wealth * 0.3 + 0.3
                b.wealth = b.wealth * 0.7 + avg_wealth * 0.3 + 0.3
                traded.add((i, j))


def phase_winter(world: World) -> None:
    """All settlements lose food. Starvation or sustained attrition → collapse to Ruin."""
    p = world.params
    rng = world.rng

    severity = p.winter_severity * rng.uniform(0.5, 1.5)

    for s in world.settlements:
        if not s.alive:
            continue

        s.food -= severity * (1.0 + 0.1 * s.population)

        if s.food <= 0 or s.population <= 0:
            s.alive = False
            s.food = 0
            world.grid[s.y, s.x] = RUIN

            # Disperse survivors to nearest friendly settlement
            friendly = [
                f for f in world.settlements
                if f.alive and f.owner_id == s.owner_id
                and abs(f.x - s.x) + abs(f.y - s.y) <= 5
            ]
            if friendly:
                closest = min(friendly, key=lambda f: abs(f.x - s.x) + abs(f.y - s.y))
                closest.population += max(0, s.population * 0.3)
                closest.food += max(0, s.food * 0.5)


def phase_environment(world: World) -> None:
    """
    Natural reclamation: ruins rebuilt by nearby thriving settlements,
    or slowly reverted to forest/plains by nature.
    """
    p = world.params
    rng = world.rng
    H, W = world.H, world.W

    ruin_ys, ruin_xs = np.where(world.grid == RUIN)

    for ry, rx in zip(ruin_ys.tolist(), ruin_xs.tolist()):
        nearby = [
            s for s in world.settlements
            if s.alive
            and abs(s.x - rx) + abs(s.y - ry) <= 3
            and s.food > 3.0
        ]

        if nearby and rng.random() < p.ruin_reclaim_rate:
            patron = min(nearby, key=lambda s: abs(s.x - rx) + abs(s.y - ry))

            # Coastal ruins rebuilt as ports
            is_coastal = any(
                world.grid[ny, nx] == OCEAN
                for ddx in [-1, 0, 1]
                for ddy in [-1, 0, 1]
                if 0 <= (nx := rx + ddx) < W and 0 <= (ny := ry + ddy) < H
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


# ---------------------------------------------------------------------------
# Full simulation run
# ---------------------------------------------------------------------------

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
    Static cells (ocean, mountain) are restored after every year — guaranteed invariant.
    """
    world = build_world(grid_list, settlements_data, params, rng)
    static_mask = is_static(world.grid)
    original_grid = world.grid.copy()

    for _ in range(years):
        phase_growth(world)
        phase_conflict(world)
        phase_trade(world)
        phase_winter(world)
        phase_environment(world)
        # Enforce static cell invariant — no phase can overwrite ocean or mountain
        world.grid[static_mask] = original_grid[static_mask]

    return initial_class_grid(world.grid)


# ---------------------------------------------------------------------------
# Monte Carlo aggregation
# ---------------------------------------------------------------------------

def monte_carlo_predict(
    grid_list: list[list[int]],
    settlements_data: list[dict],
    n_runs: int = 500,
    param_samples: int = 10,
    seed: int = 0,
) -> np.ndarray:
    """
    Predict terrain probabilities via Monte Carlo over both:
      - Stochastic simulation outcomes (different rng per run)
      - Parameter uncertainty (Latin Hypercube Sampling over plausible param space)

    Returns array shape (H, W, 6) with per-cell class probabilities.
    Applies 0.01 floor + renormalizes to prevent zero-probability KL blowup.

    Args:
        n_runs: total simulation runs (split evenly across param_samples)
        param_samples: number of distinct parameter combinations to sample
        seed: master RNG seed (use different seeds per map-seed to decorrelate)
    """
    from scipy.stats import qmc

    H = len(grid_list)
    W = len(grid_list[0])
    counts = np.zeros((H, W, 6), dtype=np.float32)

    rng = np.random.default_rng(seed)
    runs_per_param = max(1, n_runs // param_samples)

    # Parameter space — plausible ranges based on documented mechanics
    param_ranges = {
        "expansion_rate":      (0.05, 0.60),
        "conflict_prob":       (0.05, 0.50),
        "winter_severity":     (0.10, 0.70),
        "trade_range":         (4,    12),
        "ruin_reclaim_rate":   (0.10, 0.60),
        "forest_reclaim_rate": (0.02, 0.25),
        "longship_prob":       (0.05, 0.40),
        "longship_range":      (5,    15),
    }
    keys = list(param_ranges.keys())

    # Latin Hypercube Sampling for good coverage of parameter space
    sampler = qmc.LatinHypercube(d=len(param_ranges), seed=int(rng.integers(2**31)))
    lhs_samples = sampler.random(n=param_samples)

    for i in range(param_samples):
        param_vals = {}
        for j, key in enumerate(keys):
            lo, hi = param_ranges[key]
            val = lo + lhs_samples[i, j] * (hi - lo)
            param_vals[key] = int(round(val)) if key in ("trade_range", "longship_range") else float(val)

        params = SimParams(**param_vals)

        for _ in range(runs_per_param):
            run_rng = np.random.default_rng(int(rng.integers(2**31)))
            result = run_simulation(grid_list, settlements_data, params, run_rng)
            for cls in range(6):
                counts[:, :, cls] += (result == cls).astype(np.float32)

    # Normalize to probabilities
    total = counts.sum(axis=2, keepdims=True)
    total = np.maximum(total, 1.0)
    probs = counts / total

    # 0.01 floor + renormalize — critical: prevents infinite KL divergence
    probs = np.maximum(probs, 0.01)
    probs = probs / probs.sum(axis=2, keepdims=True)

    return probs


# ---------------------------------------------------------------------------
# Static cell overrides
# ---------------------------------------------------------------------------

def apply_static_overrides(
    probs: np.ndarray,
    initial_grid: np.ndarray,
) -> np.ndarray:
    """
    For provably static cells (ocean, mountain), override probabilities
    with near-certainty (0.95 for dominant class, 0.01 for others).

    Uses two separate assignments per mask — combined boolean+integer fancy
    indexing is fragile across NumPy versions.
    """
    probs = probs.copy()

    # Ocean → class 0 (CLASS_EMPTY)
    ocean_mask = (initial_grid == OCEAN)
    probs[ocean_mask, :] = 0.01
    probs[ocean_mask, CLASS_EMPTY] = 0.95   # 0.01*5 + 0.95 = 1.00

    # Mountain → class 5 (CLASS_MOUNTAIN)
    mountain_mask = (initial_grid == MOUNTAIN)
    probs[mountain_mask, :] = 0.01
    probs[mountain_mask, CLASS_MOUNTAIN] = 0.95

    # Renormalize (no-op for static cells, safety net for dynamic cells)
    probs = probs / probs.sum(axis=2, keepdims=True)
    return probs
