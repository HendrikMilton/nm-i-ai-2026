"""
Observe, SAVE observations to disk, then resubmit with tunable weight.

Usage:
    # Step 1: observe and save (costs queries)
    python resubmit_cached.py --observe --round-id <id> --cache observations.json

    # Step 2: resubmit with different weights (NO queries)
    python resubmit_cached.py --resubmit --cache observations.json --weight 0.9
    python resubmit_cached.py --resubmit --cache observations.json --weight 0.95
"""
import argparse
import json
import time
import os
import numpy as np
import requests

from api_client import _headers, get_round, get_active_round, submit_prediction
from simulator import parse_initial_grid, monte_carlo_predict, apply_static_overrides, API_TO_CLASS
from dashboard_logger import log_action, log_query, log_submission, log_prediction

BASE_URL = "https://api.ainm.no/astar-island"

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


def simulate(round_id: str, seed_index: int, vx: int, vy: int, vw: int, vh: int) -> dict:
    resp = requests.post(f"{BASE_URL}/simulate", headers=_headers(), json={
        "round_id": round_id,
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
    observations: list,
    observation_weight: float = 0.9,
) -> np.ndarray:
    probs = probs.copy()
    for (x, y, obs_class) in observations:
        if obs_class < 0 or obs_class > 5:
            continue
        prior = probs[y, x].copy()
        new_probs = np.full(6, (1.0 - observation_weight) / 5)
        new_probs[obs_class] = observation_weight
        blended = 0.5 * prior + 0.5 * new_probs
        blended = np.maximum(blended, 0.01)
        blended = blended / blended.sum()
        probs[y, x] = blended
    return probs


def observe(round_id: str, cache_file: str, viewports=None):
    if viewports is None:
        viewports = VIEWPORTS

    round_data = get_round(round_id)
    initial_states = round_data["initial_states"]
    n_seeds = len(initial_states)
    print(f"Round {round_id}: {n_seeds} seeds, {len(viewports)} viewports each = {n_seeds * len(viewports)} queries")

    cache = {"round_id": round_id, "seeds": {}}

    for seed_index in range(n_seeds):
        print(f"\n=== Seed {seed_index} ===")
        seed_observations = []

        for (vx, vy, vw, vh) in viewports:
            try:
                result = simulate(round_id, seed_index, vx, vy, vw, vh)
                obs_grid = result["grid"]
                actual_vp = result["viewport"]
                ax, ay = actual_vp["x"], actual_vp["y"]

                for row_i, row in enumerate(obs_grid):
                    for col_i, api_val in enumerate(row):
                        cx = ax + col_i
                        cy = ay + row_i
                        if 0 <= cx < 40 and 0 <= cy < 40:
                            obs_class = API_TO_CLASS.get(api_val, 0)
                            seed_observations.append([cx, cy, obs_class])

                remaining = result.get("queries_max", 50) - result.get("queries_used", 0)
                print(f"  VP ({vx},{vy}) observed | remaining queries: {remaining}")

                # Log query for dashboard
                actual_vp = result["viewport"]
                log_query(round_id, seed_index,
                          {"x": actual_vp["x"], "y": actual_vp["y"], "w": vw, "h": vh},
                          obs_grid, remaining)

                time.sleep(0.25)

            except Exception as e:
                print(f"  VP ({vx},{vy}) FAILED: {e}")

        cache["seeds"][str(seed_index)] = seed_observations
        print(f"  Seed {seed_index}: {len(seed_observations)} cells observed")

    with open(cache_file, "w") as f:
        json.dump(cache, f)
    print(f"\nObservations saved to {cache_file}")
    return cache


def resubmit(cache_file: str, weight: float, n_runs: int = 500, param_samples: int = 10):
    with open(cache_file) as f:
        cache = json.load(f)

    round_id = cache["round_id"]
    round_data = get_round(round_id)
    initial_states = round_data["initial_states"]

    print(f"Resubmitting round {round_id} with observation_weight={weight}")

    for seed_index in range(len(initial_states)):
        print(f"\n=== Seed {seed_index} ===")
        initial_state = initial_states[seed_index]
        grid_list = initial_state["grid"]
        settlements_data = initial_state["settlements"]

        print(f"  Running Monte Carlo ({n_runs} runs)...")
        t0 = time.time()
        probs = monte_carlo_predict(grid_list, settlements_data, n_runs=n_runs, param_samples=param_samples, seed=seed_index * 1000)
        initial_grid = parse_initial_grid(grid_list)
        probs = apply_static_overrides(probs, initial_grid)
        print(f"  MC done in {time.time()-t0:.1f}s")

        observations = cache["seeds"].get(str(seed_index), [])
        print(f"  Applying {len(observations)} cached observations (weight={weight})...")
        probs = apply_observations(probs, observations, observation_weight=weight)

        log_prediction(round_id, seed_index, probs)

        result = submit_prediction(round_id, seed_index, probs)
        print(f"  Response: {result}")
        log_submission(round_id, seed_index, result)

    print("\nDone.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe", action="store_true", help="Collect observations (costs queries)")
    parser.add_argument("--resubmit", action="store_true", help="Resubmit from cache (no queries)")
    parser.add_argument("--round-id", help="Round UUID (auto-detects active if omitted)")
    parser.add_argument("--cache", default="observations.json", help="Cache file path")
    parser.add_argument("--weight", type=float, default=0.9, help="Observation weight for resubmit (default 0.9)")
    parser.add_argument("--n-runs", type=int, default=500)
    parser.add_argument("--param-samples", type=int, default=10)
    parser.add_argument("--viewports", type=int, default=9, help="Number of viewports per seed (1-9)")
    args = parser.parse_args()

    if args.round_id:
        round_id = args.round_id
    else:
        active = get_active_round()
        if active is None:
            print("No active round. Pass --round-id explicitly.")
            return
        round_id = active["id"]

    viewports = VIEWPORTS[:args.viewports]

    if args.observe:
        observe(round_id, args.cache, viewports=viewports)
    elif args.resubmit:
        resubmit(args.cache, args.weight, args.n_runs, args.param_samples)
    else:
        print("Pass --observe to collect (costs queries) or --resubmit to resubmit from cache.")


if __name__ == "__main__":
    main()
