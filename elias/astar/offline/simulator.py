"""
Astar Island — Offline Simulator

Implements the 5-phase Norse civilisation simulation based on documented mechanics.
Hidden parameters are configurable via a params dict for calibration against real API data.
"""

import copy
import math
import random
from dataclasses import dataclass, field

# Terrain codes (internal)
OCEAN = 10
PLAINS = 11
EMPTY = 0
SETTLEMENT = 1
PORT = 2
RUIN = 3
FOREST = 4
MOUNTAIN = 5

# Prediction class mapping
TERRAIN_TO_CLASS = {
    EMPTY: 0, OCEAN: 0, PLAINS: 0,
    SETTLEMENT: 1, PORT: 2, RUIN: 3, FOREST: 4, MOUNTAIN: 5,
}

# Default hidden parameters — tune these against real observations
DEFAULT_PARAMS = {
    # Growth
    "base_food_production": 0.3,
    "forest_food_bonus": 0.4,
    "population_growth_rate": 0.1,
    "population_food_threshold": 0.5,
    "port_development_threshold": 0.6,
    "port_development_chance": 0.15,
    "longship_build_threshold": 0.7,
    "longship_build_chance": 0.1,
    "expansion_threshold": 1.5,
    "expansion_chance": 0.08,
    "expansion_radius": 3,

    # Conflict
    "raid_range": 4,
    "longship_raid_range": 10,
    "raid_chance": 0.15,
    "desperate_raid_multiplier": 2.5,
    "desperate_food_threshold": 0.3,
    "raid_damage": 0.3,
    "raid_loot_fraction": 0.4,
    "conquest_chance": 0.1,

    # Trade
    "trade_range": 6,
    "trade_food_bonus": 0.15,
    "trade_wealth_bonus": 0.2,
    "tech_diffusion_rate": 0.1,

    # Winter
    "winter_severity_mean": 0.4,
    "winter_severity_std": 0.2,
    "winter_food_loss_base": 0.3,
    "collapse_food_threshold": 0.1,
    "collapse_defense_threshold": 0.15,
    "collapse_chance_base": 0.3,

    # Environment
    "ruin_forest_reclaim_chance": 0.05,
    "ruin_plains_reclaim_chance": 0.08,
    "settlement_reclaim_chance": 0.1,
    "settlement_reclaim_radius": 3,
    "reclaim_resource_fraction": 0.3,
}


@dataclass
class Settlement:
    x: int
    y: int
    population: float = 1.0
    food: float = 1.0
    wealth: float = 0.5
    defense: float = 0.5
    tech_level: float = 0.0
    has_port: bool = False
    has_longship: bool = False
    owner_id: int = 0
    alive: bool = True


class Simulator:
    """Runs a single stochastic simulation of the Astar Island world."""

    def __init__(self, grid, settlements_data, params=None, seed=None):
        """
        Args:
            grid: 2D list of terrain codes (H x W)
            settlements_data: list of dicts with settlement info from initial state
            params: dict of simulation parameters (defaults used if None)
            seed: random seed for this simulation run
        """
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self.rng = random.Random(seed)
        self.height = len(grid)
        self.width = len(grid[0]) if self.height > 0 else 0
        self.grid = [row[:] for row in grid]
        self.settlements: list[Settlement] = []

        # Build settlements from initial data
        for s in settlements_data:
            self.settlements.append(Settlement(
                x=s["x"], y=s["y"],
                has_port=s.get("has_port", False),
                alive=s.get("alive", True),
                owner_id=s.get("owner_id", len(self.settlements)),
                population=s.get("population", 0.8 + self.rng.random() * 0.4),
                food=s.get("food", 0.8 + self.rng.random() * 0.4),
                wealth=s.get("wealth", 0.3 + self.rng.random() * 0.4),
                defense=s.get("defense", 0.3 + self.rng.random() * 0.4),
                tech_level=s.get("tech_level", self.rng.random() * 0.2),
            ))

        # Sync grid with settlement positions
        for s in self.settlements:
            if s.alive:
                self.grid[s.y][s.x] = PORT if s.has_port else SETTLEMENT

    def _dist(self, x1, y1, x2, y2):
        return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

    def _adjacent_cells(self, x, y):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    yield nx, ny

    def _is_coastal(self, x, y):
        for nx, ny in self._adjacent_cells(x, y):
            if self.grid[ny][nx] == OCEAN:
                return True
        return False

    def _adjacent_terrain_count(self, x, y, terrain):
        return sum(1 for nx, ny in self._adjacent_cells(x, y)
                   if self.grid[ny][nx] == terrain)

    def _settlement_at(self, x, y):
        for s in self.settlements:
            if s.x == x and s.y == y and s.alive:
                return s
        return None

    def _alive_settlements(self):
        return [s for s in self.settlements if s.alive]

    def _is_buildable(self, x, y):
        """Check if a cell can have a new settlement."""
        t = self.grid[y][x]
        return t in (PLAINS, EMPTY, RUIN)

    # --- Phase 1: Growth ---
    def _phase_growth(self):
        p = self.params
        for s in self._alive_settlements():
            # Food production
            forest_adj = self._adjacent_terrain_count(s.x, s.y, FOREST)
            food_prod = p["base_food_production"] + forest_adj * p["forest_food_bonus"]
            food_prod *= (1 + s.tech_level * 0.5)
            s.food += food_prod

            # Population growth
            if s.food > p["population_food_threshold"]:
                s.population += p["population_growth_rate"] * s.population
                s.population = min(s.population, 5.0)

            # Defense grows with population
            s.defense = min(s.defense + 0.02 * s.population, 2.0)

            # Port development
            if not s.has_port and self._is_coastal(s.x, s.y):
                if s.wealth > p["port_development_threshold"]:
                    if self.rng.random() < p["port_development_chance"]:
                        s.has_port = True
                        self.grid[s.y][s.x] = PORT

            # Longship building
            if s.has_port and not s.has_longship:
                if s.wealth > p["longship_build_threshold"]:
                    if self.rng.random() < p["longship_build_chance"]:
                        s.has_longship = True

            # Expansion — found new settlement nearby
            if s.population > p["expansion_threshold"]:
                if self.rng.random() < p["expansion_chance"]:
                    self._try_expand(s)

    def _try_expand(self, parent):
        """Try to found a new settlement near a prosperous parent."""
        p = self.params
        radius = p["expansion_radius"]
        candidates = []
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = parent.x + dx, parent.y + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    if self._is_buildable(nx, ny):
                        candidates.append((nx, ny))

        if not candidates:
            return

        x, y = self.rng.choice(candidates)
        is_port = self._is_coastal(x, y) and self.rng.random() < 0.3
        new_s = Settlement(
            x=x, y=y,
            population=parent.population * 0.3,
            food=parent.food * 0.3,
            wealth=parent.wealth * 0.2,
            defense=0.3,
            tech_level=parent.tech_level * 0.8,
            has_port=is_port,
            owner_id=parent.owner_id,
        )
        parent.population *= 0.7
        parent.food *= 0.7
        self.settlements.append(new_s)
        self.grid[y][x] = PORT if is_port else SETTLEMENT

    # --- Phase 2: Conflict ---
    def _phase_conflict(self):
        p = self.params
        alive = self._alive_settlements()
        self.rng.shuffle(alive)

        for attacker in alive:
            if not attacker.alive:
                continue

            raid_range = p["longship_raid_range"] if attacker.has_longship else p["raid_range"]
            raid_chance = p["raid_chance"]
            if attacker.food < p["desperate_food_threshold"]:
                raid_chance *= p["desperate_raid_multiplier"]

            if self.rng.random() > raid_chance:
                continue

            # Find targets in range from different factions
            targets = [
                t for t in alive
                if t.alive and t.owner_id != attacker.owner_id
                and self._dist(attacker.x, attacker.y, t.x, t.y) <= raid_range
            ]
            if not targets:
                continue

            defender = self.rng.choice(targets)
            # Raid outcome based on relative strength
            attack_power = attacker.population * (1 + attacker.tech_level) * attacker.defense
            defend_power = defender.population * (1 + defender.tech_level) * defender.defense

            if attack_power > defend_power * self.rng.uniform(0.5, 1.5):
                # Successful raid
                loot_food = defender.food * p["raid_loot_fraction"]
                loot_wealth = defender.wealth * p["raid_loot_fraction"]
                attacker.food += loot_food
                attacker.wealth += loot_wealth
                defender.food -= loot_food
                defender.wealth -= loot_wealth
                defender.defense -= p["raid_damage"]
                defender.population *= (1 - p["raid_damage"] * 0.5)

                # Conquest
                if self.rng.random() < p["conquest_chance"]:
                    defender.owner_id = attacker.owner_id

    # --- Phase 3: Trade ---
    def _phase_trade(self):
        p = self.params
        ports = [s for s in self._alive_settlements() if s.has_port]

        for i, a in enumerate(ports):
            for b in ports[i + 1:]:
                if a.owner_id == b.owner_id or self.rng.random() < 0.5:
                    # Same faction always trades; different factions trade sometimes
                    dist = self._dist(a.x, a.y, b.x, b.y)
                    if dist <= p["trade_range"]:
                        a.food += p["trade_food_bonus"]
                        b.food += p["trade_food_bonus"]
                        a.wealth += p["trade_wealth_bonus"]
                        b.wealth += p["trade_wealth_bonus"]

                        # Tech diffusion
                        tech_diff = abs(a.tech_level - b.tech_level)
                        transfer = tech_diff * p["tech_diffusion_rate"]
                        if a.tech_level > b.tech_level:
                            b.tech_level += transfer
                        else:
                            a.tech_level += transfer

    # --- Phase 4: Winter ---
    def _phase_winter(self):
        p = self.params
        severity = max(0, self.rng.gauss(
            p["winter_severity_mean"], p["winter_severity_std"]))

        for s in self._alive_settlements():
            food_loss = p["winter_food_loss_base"] * (1 + severity)
            s.food -= food_loss
            s.food = max(s.food, 0)

            # Population loss from starvation
            if s.food <= 0:
                s.population *= 0.7

            # Check for collapse
            should_collapse = False
            if s.food < p["collapse_food_threshold"]:
                if self.rng.random() < p["collapse_chance_base"] * (1 + severity):
                    should_collapse = True
            if s.defense < p["collapse_defense_threshold"] and s.population < 0.3:
                if self.rng.random() < p["collapse_chance_base"]:
                    should_collapse = True

            if should_collapse:
                self._collapse_settlement(s)

    def _collapse_settlement(self, s):
        """Settlement collapses into a ruin, dispersing population."""
        s.alive = False
        self.grid[s.y][s.x] = RUIN

        # Disperse population to nearby friendly settlements
        nearby = [
            t for t in self._alive_settlements()
            if t.owner_id == s.owner_id
            and self._dist(s.x, s.y, t.x, t.y) <= 5
        ]
        if nearby:
            share = s.population / len(nearby)
            for t in nearby:
                t.population += share * 0.5

    # --- Phase 5: Environment ---
    def _phase_environment(self):
        p = self.params
        ruins = [(s.x, s.y) for s in self.settlements if not s.alive]

        for rx, ry in ruins:
            if self.grid[ry][rx] != RUIN:
                continue

            # Check if a nearby thriving settlement reclaims it
            reclaimed = False
            for s in self._alive_settlements():
                dist = self._dist(s.x, s.y, rx, ry)
                if dist <= p["settlement_reclaim_radius"] and s.population > 1.0:
                    if self.rng.random() < p["settlement_reclaim_chance"]:
                        is_port = self._is_coastal(rx, ry) and self.rng.random() < 0.4
                        new_s = Settlement(
                            x=rx, y=ry,
                            population=s.population * p["reclaim_resource_fraction"],
                            food=s.food * p["reclaim_resource_fraction"],
                            wealth=s.wealth * p["reclaim_resource_fraction"] * 0.5,
                            defense=0.3,
                            tech_level=s.tech_level * 0.5,
                            has_port=is_port,
                            owner_id=s.owner_id,
                        )
                        self.settlements.append(new_s)
                        self.grid[ry][rx] = PORT if is_port else SETTLEMENT
                        reclaimed = True
                        break

            if not reclaimed:
                # Nature reclaims: forest or plains
                if self._adjacent_terrain_count(rx, ry, FOREST) > 0:
                    if self.rng.random() < p["ruin_forest_reclaim_chance"]:
                        self.grid[ry][rx] = FOREST
                elif self.rng.random() < p["ruin_plains_reclaim_chance"]:
                    self.grid[ry][rx] = PLAINS

    # --- Run simulation ---
    def step(self):
        """Run one year (all 5 phases)."""
        self._phase_growth()
        self._phase_conflict()
        self._phase_trade()
        self._phase_winter()
        self._phase_environment()

    def run(self, years=50):
        """Run the full simulation."""
        for _ in range(years):
            self.step()
        return self.grid

    def get_class_grid(self):
        """Return grid mapped to prediction classes (H x W)."""
        return [
            [TERRAIN_TO_CLASS.get(cell, 0) for cell in row]
            for row in self.grid
        ]


def run_monte_carlo(grid, settlements_data, n_sims=200, params=None, base_seed=None):
    """
    Run many stochastic simulations and return per-cell probability distributions.

    Returns: H x W x 6 probability tensor
    """
    h = len(grid)
    w = len(grid[0]) if h > 0 else 0
    counts = [[[0] * 6 for _ in range(w)] for _ in range(h)]

    for i in range(n_sims):
        seed = (base_seed or 0) + i if base_seed is not None else None
        sim = Simulator(grid, settlements_data, params=params, seed=seed)
        sim.run()
        class_grid = sim.get_class_grid()

        for r in range(h):
            for c in range(w):
                counts[r][c][class_grid[r][c]] += 1

    # Convert counts to probabilities with minimal smoothing
    # Uses per-class floors matching floor_and_normalize to avoid double-inflation
    class_floors = [0.005, 0.005, 0.001, 0.002, 0.005, 0.001]
    prediction = [[[0.0] * 6 for _ in range(w)] for _ in range(h)]
    for r in range(h):
        for c in range(w):
            for k in range(6):
                prediction[r][c][k] = max(counts[r][c][k] / n_sims, class_floors[k])
            total = sum(prediction[r][c])
            for k in range(6):
                prediction[r][c][k] /= total

    return prediction


if __name__ == "__main__":
    # Quick test with a small map
    test_grid = [
        [OCEAN, OCEAN, OCEAN, OCEAN, OCEAN, OCEAN, OCEAN, OCEAN, OCEAN, OCEAN],
        [OCEAN, FOREST, PLAINS, PLAINS, PLAINS, PLAINS, FOREST, PLAINS, PLAINS, OCEAN],
        [OCEAN, PLAINS, PLAINS, FOREST, PLAINS, PLAINS, PLAINS, PLAINS, PLAINS, OCEAN],
        [OCEAN, PLAINS, PLAINS, PLAINS, PLAINS, MOUNTAIN, PLAINS, PLAINS, PLAINS, OCEAN],
        [OCEAN, FOREST, PLAINS, PLAINS, PLAINS, PLAINS, PLAINS, FOREST, PLAINS, OCEAN],
        [OCEAN, PLAINS, PLAINS, PLAINS, PLAINS, PLAINS, PLAINS, PLAINS, PLAINS, OCEAN],
        [OCEAN, PLAINS, PLAINS, MOUNTAIN, PLAINS, PLAINS, FOREST, PLAINS, PLAINS, OCEAN],
        [OCEAN, PLAINS, FOREST, PLAINS, PLAINS, PLAINS, PLAINS, PLAINS, PLAINS, OCEAN],
        [OCEAN, PLAINS, PLAINS, PLAINS, PLAINS, PLAINS, PLAINS, PLAINS, PLAINS, OCEAN],
        [OCEAN, OCEAN, OCEAN, OCEAN, OCEAN, OCEAN, OCEAN, OCEAN, OCEAN, OCEAN],
    ]
    test_settlements = [
        {"x": 2, "y": 2, "has_port": False, "alive": True, "owner_id": 0},
        {"x": 7, "y": 4, "has_port": False, "alive": True, "owner_id": 1},
        {"x": 4, "y": 7, "has_port": False, "alive": True, "owner_id": 2},
    ]

    print("Running single simulation...")
    sim = Simulator(test_grid, test_settlements, seed=42)
    final_grid = sim.run()
    for row in sim.get_class_grid():
        print([str(c) for c in row])

    print(f"\nSettlements: {sum(1 for s in sim.settlements if s.alive)} alive, "
          f"{sum(1 for s in sim.settlements if not s.alive)} dead")

    print("\nRunning Monte Carlo (100 sims)...")
    probs = run_monte_carlo(test_grid, test_settlements, n_sims=100, base_seed=0)
    # Show entropy of dynamic cells
    dynamic = 0
    for r in range(len(probs)):
        for c in range(len(probs[0])):
            p = probs[r][c]
            entropy = -sum(pi * math.log(pi) for pi in p if pi > 0)
            if entropy > 0.1:
                dynamic += 1
    print(f"Dynamic cells (entropy > 0.1): {dynamic}")
    print("Done.")
