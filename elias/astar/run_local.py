"""
Astar Island — Local simulator pipeline.

Uses the offline simulator to generate predictions via Monte Carlo,
instead of burning API queries for raw observations.

Usage:
    python run_local.py              # Run against active round
    python run_local.py --sims 500   # More simulations for better estimates
"""

import argparse
import json
import os
import time

from utils import (
    get_active_round,
    get_round,
    submit,
    floor_and_normalize,
)
from simulator import run_monte_carlo, DEFAULT_PARAMS

N_SEEDS = 5
N_CLASSES = 6


def extract_grid_and_settlements(round_data, seed_index):
    """Extract initial grid and settlement data for a specific seed."""
    initial_states = round_data.get("initial_states") or []
    if seed_index >= len(initial_states):
        raise ValueError(
            f"Seed index {seed_index} not found (only {len(initial_states)} seeds)")

    state = initial_states[seed_index]
    grid = state.get("grid") or state.get("terrain") or []
    settlements = state.get("settlements") or []
    return grid, settlements


def load_custom_params(path=None):
    """Load tuned parameters from a JSON file, falling back to defaults."""
    if path and os.path.exists(path):
        with open(path) as f:
            custom = json.load(f)
        params = {**DEFAULT_PARAMS, **custom}
        print(f"Loaded custom params from {path} ({len(custom)} overrides)")
        return params
    return DEFAULT_PARAMS.copy()


def main():
    parser = argparse.ArgumentParser(description="Astar Island local sim pipeline")
    parser.add_argument("--sims", type=int, default=200,
                        help="Number of Monte Carlo simulations per seed (default: 200)")
    parser.add_argument("--params", type=str, default=None,
                        help="Path to custom params JSON file")
    parser.add_argument("--no-submit", action="store_true",
                        help="Generate predictions without submitting")
    parser.add_argument("--seed", type=int, default=None,
                        help="Only run for a specific seed index (0-4)")
    parser.add_argument("--output", type=str, default=None,
                        help="Save predictions to JSON file")
    args = parser.parse_args()

    # Load params
    params = load_custom_params(args.params)

    # Find active round
    print("Fetching active round...")
    active = get_active_round()
    if not active:
        print("No active round found. Exiting.")
        return

    round_id = active["id"]
    print(f"Active round: {round_id}")

    # Get round details
    round_data = get_round(round_id)
    map_w = round_data.get("map_width", 40)
    map_h = round_data.get("map_height", 40)
    print(f"Map: {map_w}x{map_h}")

    seeds = [args.seed] if args.seed is not None else list(range(N_SEEDS))
    predictions = {}

    for seed_idx in seeds:
        print(f"\n--- Seed {seed_idx} ---")
        grid, settlements = extract_grid_and_settlements(round_data, seed_idx)
        print(f"  Initial settlements: {len(settlements)}")
        print(f"  Running {args.sims} Monte Carlo simulations...")

        t0 = time.time()
        prediction = run_monte_carlo(
            grid, settlements,
            n_sims=args.sims,
            params=params,
            base_seed=seed_idx * 10000,
        )
        elapsed = time.time() - t0
        print(f"  Done in {elapsed:.1f}s")

        prediction = floor_and_normalize(prediction)
        predictions[seed_idx] = prediction

        if not args.no_submit:
            print(f"  Submitting seed {seed_idx}...")
            try:
                result = submit(round_id, seed_idx, prediction)
                print(f"  Result: {result}")
            except Exception as e:
                print(f"  Submit ERROR: {e}")
            time.sleep(0.6)

    if args.output:
        # Convert int keys to strings for JSON
        out = {str(k): v for k, v in predictions.items()}
        with open(args.output, "w") as f:
            json.dump(out, f)
        print(f"\nPredictions saved to {args.output}")

    print("\nDone!")


if __name__ == "__main__":
    main()
