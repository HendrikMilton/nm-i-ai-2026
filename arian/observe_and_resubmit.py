"""
Use all 50 queries to observe the real simulator, calibrate predictions, resubmit.

Strategy:
- 9 viewports cover the full 40x40 map with 15x15 windows (slight overlap)
- ~1-2 queries per seed for full map coverage
- Observed cells get their prediction shifted toward the actual observed class
- Resubmit all 5 seeds with calibrated predictions
"""
import time
import numpy as np
import requests
import os

from api_client import _headers, get_round, submit_prediction
from simulator import (
    parse_initial_grid, monte_carlo_predict, apply_static_overrides,
    API_TO_CLASS
)
from dashboard_logger import log_action, log_query, log_submission, log_prediction

TOKEN = "REDACTED_TOKEN"
os.environ["AINM_TOKEN"] = TOKEN

ROUND_ID = "76909e29-f664-4b2f-b16b-61b7507277e9"
BASE_URL = "https://api.ainm.no/astar-island"

# 9 viewports that tile the 40x40 map with 15x15 windows
VIEWPORTS = [
    (0,  0,  15, 15),
    (13, 0,  15, 15),
    (25, 0,  15, 15),
    (0,  13, 15, 15),
    (13, 13, 15, 15),
    (25, 13, 15, 15),
    (0,  25, 15, 15),
    (13, 25, 15, 15),
    (25, 25, 15, 15),
]

# With 5 seeds x 9 viewports = 45 queries, leaving 5 for extra repeats on uncertain areas
# We'll do all 9 viewports per seed = full map coverage for every seed


def simulate(seed_index: int, vx: int, vy: int, vw: int, vh: int) -> dict:
    """Call POST /simulate — costs 1 query."""
    resp = requests.post(f"{BASE_URL}/simulate", headers=_headers(), json={
        "round_id": ROUND_ID,
        "seed_index": seed_index,
        "viewport_x": vx,
        "viewport_y": vy,
        "viewport_w": vw,
        "viewport_h": vh,
    })
    resp.raise_for_status()
    return resp.json()


def apply_observations(
    probs: np.ndarray,
    observations: list[tuple[int, int, int]],  # (x, y, class)
    observation_weight: float = 0.7,
) -> np.ndarray:
    """
    Shift prediction toward observed class for each observed cell.
    observation_weight: how much weight to put on the observation (vs prior).
    """
    probs = probs.copy()
    for (x, y, obs_class) in observations:
        if obs_class < 0 or obs_class > 5:
            continue
        # Shift: observed class gets observation_weight, rest split
        prior = probs[y, x].copy()
        new_probs = np.full(6, (1.0 - observation_weight) / 5 * prior.sum())
        new_probs[obs_class] = observation_weight
        # Blend with prior
        blended = 0.5 * prior + 0.5 * new_probs
        blended = np.maximum(blended, 0.01)
        blended = blended / blended.sum()
        probs[y, x] = blended
    return probs


def main():
    print(f"Fetching round {ROUND_ID}...")
    round_data = get_round(ROUND_ID)
    initial_states = round_data["initial_states"]
    n_seeds = len(initial_states)
    print(f"Map: {round_data['map_width']}x{round_data['map_height']}, {n_seeds} seeds")
    print(f"Plan: {n_seeds} seeds x {len(VIEWPORTS)} viewports = {n_seeds * len(VIEWPORTS)} queries\n")

    queries_used = 0

    for seed_index in range(n_seeds):
        print(f"=== Seed {seed_index} ===")
        initial_state = initial_states[seed_index]
        grid_list = initial_state["grid"]
        settlements_data = initial_state["settlements"]

        # Run Monte Carlo first (our prior)
        print(f"  Running Monte Carlo (500 runs)...")
        t0 = time.time()
        probs = monte_carlo_predict(grid_list, settlements_data, n_runs=500, param_samples=10, seed=seed_index * 1000)
        initial_grid = parse_initial_grid(grid_list)
        probs = apply_static_overrides(probs, initial_grid)
        print(f"  Monte Carlo done in {time.time()-t0:.1f}s")

        # Observe all viewports
        observations = []
        for (vx, vy, vw, vh) in VIEWPORTS:
            try:
                result = simulate(seed_index, vx, vy, vw, vh)
                queries_used += 1
                remaining = result.get("queries_max", 50) - result.get("queries_used", queries_used)

                # Parse observed grid
                obs_grid = result["grid"]
                actual_vp = result["viewport"]
                ax, ay = actual_vp["x"], actual_vp["y"]

                for row_i, row in enumerate(obs_grid):
                    for col_i, api_val in enumerate(row):
                        cx = ax + col_i
                        cy = ay + row_i
                        if 0 <= cx < 40 and 0 <= cy < 40:
                            obs_class = API_TO_CLASS.get(api_val, 0)
                            observations.append((cx, cy, obs_class))

                print(f"  VP ({vx},{vy}) → {len(obs_grid)}x{len(obs_grid[0])} observed | queries used: {result.get('queries_used','?')}/{result.get('queries_max','?')} | remaining: {remaining}")

                log_query(ROUND_ID, seed_index,
                          {"x": ax, "y": ay, "w": 15, "h": 15},
                          obs_grid, remaining)

                time.sleep(0.25)  # stay within 5 req/sec rate limit

            except Exception as e:
                print(f"  VP ({vx},{vy}) FAILED: {e}")

        # Apply observations to calibrate prediction
        print(f"  Applying {len(observations)} cell observations...")
        probs = apply_observations(probs, observations, observation_weight=0.7)

        # Submit calibrated prediction
        log_prediction(ROUND_ID, seed_index, probs)
        print(f"  Submitting calibrated prediction...")
        result = submit_prediction(ROUND_ID, seed_index, probs)
        print(f"  Response: {result}\n")
        log_submission(ROUND_ID, seed_index, result)

    print(f"Done. Total queries used: {queries_used}/50")


if __name__ == "__main__":
    main()
