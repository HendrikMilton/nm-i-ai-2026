"""
Main Astar Island prediction pipeline.

Usage:
    AINM_TOKEN=<token> python predict.py [--round-id <uuid>] [--n-runs 500] [--param-samples 10] [--dry-run]

Steps:
    1. Fetch active round + initial states for all 5 seeds (free GET, no query budget used)
    2. Run Monte Carlo simulation for each seed
    3. Apply static cell overrides (ocean=class0, mountain=class5 at near-certainty)
    4. Submit predictions (or print stats only if --dry-run)
"""
import argparse
import time
import numpy as np

from api_client import get_round, get_active_round, submit_prediction
from simulator import parse_initial_grid, monte_carlo_predict, apply_static_overrides


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
    parser = argparse.ArgumentParser(description="Astar Island predictor — zero query budget usage")
    parser.add_argument("--round-id", help="Round UUID (auto-detects active round if omitted)")
    parser.add_argument("--n-runs", type=int, default=500,
                        help="Total simulation runs per seed (default: 500)")
    parser.add_argument("--param-samples", type=int, default=10,
                        help="Parameter combinations to sample via LHS (default: 10)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute predictions but do not submit")
    args = parser.parse_args()

    # Fetch round data (free — no observe query budget consumed)
    if args.round_id:
        round_data = get_round(args.round_id)
    else:
        active = get_active_round()
        if active is None:
            print("No active round found. Pass --round-id explicitly if needed.")
            return
        round_data = get_round(active["id"])

    round_id = round_data["id"]

    # Defensive field access
    if "initial_states" not in round_data:
        print(f"ERROR: 'initial_states' missing from round response. Keys: {list(round_data.keys())}")
        return

    initial_states = round_data["initial_states"]
    n_seeds = round_data.get("seeds_count", len(initial_states))

    print(f"Round {round_data['round_number']} ({round_id})")
    print(f"Map: {round_data['map_width']}×{round_data['map_height']}, {n_seeds} seeds")
    print(f"Settings: {args.n_runs} runs, {args.param_samples} param samples")
    if args.dry_run:
        print("[DRY RUN — will not submit]")
    print()

    for seed_index in range(n_seeds):
        print(f"[Seed {seed_index}]")
        initial_state = initial_states[seed_index]

        probs = predict_seed(
            initial_state,
            n_runs=args.n_runs,
            param_samples=args.param_samples,
            seed=seed_index * 1000,  # decorrelated seeds per map-seed; 0 for seed 0 is intentional
        )

        print(f"  Shape: {probs.shape}")
        print(f"  Min prob: {probs.min():.4f}  Max: {probs.max():.4f}")
        print(f"  Sums to 1: {np.allclose(probs.sum(axis=2), 1.0, atol=1e-4)}")

        if not args.dry_run:
            print(f"  Submitting...")
            result = submit_prediction(round_id, seed_index, probs)
            print(f"  Response: {result}")
        else:
            print(f"  [dry-run] Skipping submit for seed {seed_index}")

        print()

    print("Done.")


if __name__ == "__main__":
    main()
