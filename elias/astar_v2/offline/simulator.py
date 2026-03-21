"""
Astar Island v2 — Simulator (reuses v1 core, unified floors).
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Reuse the v1 simulator wholesale — the sim logic itself is fine
from astar.offline.simulator import (
    Simulator,
    DEFAULT_PARAMS,
    TERRAIN_TO_CLASS,
    OCEAN, PLAINS, EMPTY, SETTLEMENT, PORT, RUIN, FOREST, MOUNTAIN,
    _run_single_sim,
)

# Import unified floors from v2
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from run import CLASS_FLOORS


def run_monte_carlo(grid, settlements_data, n_sims=200, params=None, base_seed=None):
    """Run MC simulations. Uses unified CLASS_FLOORS (v2 fix)."""
    from concurrent.futures import ProcessPoolExecutor

    h = len(grid)
    w = len(grid[0]) if h > 0 else 0

    tasks = []
    for i in range(n_sims):
        seed = (base_seed or 0) + i if base_seed is not None else None
        tasks.append((grid, settlements_data, params, seed))

    n_workers = min(n_sims, max(1, os.cpu_count() - 1))
    counts = [[[0] * 6 for _ in range(w)] for _ in range(h)]

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        for flat_grid in pool.map(_run_single_sim, tasks):
            idx = 0
            for r in range(h):
                for c in range(w):
                    counts[r][c][flat_grid[idx]] += 1
                    idx += 1

    # Convert to probabilities with unified floors
    prediction = [[[0.0] * 6 for _ in range(w)] for _ in range(h)]
    for r in range(h):
        for c in range(w):
            for k in range(6):
                prediction[r][c][k] = max(counts[r][c][k] / n_sims, CLASS_FLOORS[k])
            total = sum(prediction[r][c])
            for k in range(6):
                prediction[r][c][k] /= total

    return prediction
