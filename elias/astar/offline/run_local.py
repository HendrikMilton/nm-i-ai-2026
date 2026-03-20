"""
Astar Island — Local simulator pipeline.

Modes:
  python run_local.py                  # Run sim + submit on active round
  python run_local.py --no-submit      # Run sim without submitting
  python run_local.py --backtest       # Score against real ground truth (completed rounds)
  python run_local.py --backtest-all   # Score against all completed rounds
  python run_local.py --sims 500       # More simulations for better estimates
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import (
    get_active_round,
    get_round,
    get_rounds,
    get_analysis,
    submit,
    floor_and_normalize,
)
from offline.simulator import run_monte_carlo, DEFAULT_PARAMS
from offline.score import score_prediction, score_all_seeds
from run import (
    TERRAIN_PRIORS, N_CLASSES, parse_initial_grid, extract_map_dimensions,
    counts_to_prediction_v2, log_action, log_submission, _ensure_round,
)

N_SEEDS = 5


def extract_grid_and_settlements(round_data, seed_index):
    """Extract initial grid and settlement data for a specific seed."""
    initial_states = round_data.get("initial_states") or []
    if seed_index >= len(initial_states):
        raise ValueError(
            f"Seed index {seed_index} not found (only {len(initial_states)} seeds)")

    state = initial_states[seed_index]
    grid = state.get("grid") or state.get("terrain") or []
    settlements = state.get("settlements") or []

    # If no settlements in API response, extract from grid
    if not settlements:
        for r in range(len(grid)):
            for c in range(len(grid[0])):
                if grid[r][c] in (1, 2):
                    settlements.append({
                        "x": c, "y": r,
                        "has_port": grid[r][c] == 2,
                        "alive": True,
                        "owner_id": len(settlements),
                    })

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


def generate_prediction(grid, settlements, n_sims, params, base_seed, map_w, map_h):
    """Generate prediction by blending simulator Monte Carlo with learned priors.

    Uses the grid (which is the per-seed initial grid) as the source for priors.
    """
    # Run simulator Monte Carlo
    sim_pred = run_monte_carlo(grid, settlements, n_sims=n_sims, params=params, base_seed=base_seed)

    # Blend with learned priors
    # Simulator is uncalibrated, so priors get heavy weight
    sim_weight = 0.5
    prior_weight = 4.0

    prediction = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
    for r in range(map_h):
        for c in range(map_w):
            prior = TERRAIN_PRIORS.get(grid[r][c], [1/N_CLASSES]*N_CLASSES)
            for k in range(N_CLASSES):
                prediction[r][c][k] = (
                    sim_weight * sim_pred[r][c][k] + prior_weight * prior[k]
                ) / (sim_weight + prior_weight)

    return floor_and_normalize(prediction)


def backtest_round(round_id, round_num, n_sims, params):
    """Score predictions against real ground truth for a completed round."""
    print(f"\n=== Backtest Round {round_num} ({round_id[:8]}...) ===")

    rd = get_round(round_id)
    map_w, map_h = extract_map_dimensions(rd)
    initial_grid = parse_initial_grid(rd, map_w, map_h)

    predictions = {}
    ground_truths = {}

    for seed in range(N_SEEDS):
        print(f"  Seed {seed}: ", end="", flush=True)

        # Get ground truth
        analysis = get_analysis(round_id, seed)
        ground_truths[seed] = analysis["ground_truth"]

        # Generate prediction
        grid, settlements = extract_grid_and_settlements(rd, seed)
        t0 = time.time()
        pred = generate_prediction(
            grid, settlements, n_sims, params, seed * 10000,
            map_w, map_h)
        elapsed = time.time() - t0

        # Also generate prior-only for comparison
        prior_pred = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
        for r in range(map_h):
            for c in range(map_w):
                prior_pred[r][c] = list(TERRAIN_PRIORS.get(grid[r][c], [1/N_CLASSES]*N_CLASSES))
        prior_pred = floor_and_normalize(prior_pred)

        sim_result = score_prediction(pred, ground_truths[seed])
        prior_result = score_prediction(prior_pred, ground_truths[seed])

        predictions[seed] = pred
        print(f"sim={sim_result['score']:.1f}  prior={prior_result['score']:.1f}  ({elapsed:.1f}s)")

    results = score_all_seeds(predictions, ground_truths)
    print(f"\n  Round score: {results['round_score']}")
    return results


def run_active(n_sims, params, no_submit, output_path):
    """Run against the active round."""
    print("Fetching active round...")
    active = get_active_round()
    if not active:
        print("No active round found. Exiting.")
        return

    round_id = active["id"]
    print(f"Active round: {round_id}")

    rd = get_round(round_id)
    map_w, map_h = extract_map_dimensions(rd)
    initial_grid = parse_initial_grid(rd, map_w, map_h)
    _ensure_round(round_id, map_w, map_h)
    log_action(round_id, "run_local_start", {
        "n_sims": n_sims,
        "mode": "no_submit" if no_submit else "submit",
    })

    predictions = {}
    for seed in range(N_SEEDS):
        print(f"\n--- Seed {seed} ---")
        grid, settlements = extract_grid_and_settlements(rd, seed)
        print(f"  Settlements: {len(settlements)}")
        print(f"  Running {n_sims} Monte Carlo simulations...")

        t0 = time.time()
        pred = generate_prediction(
            grid, settlements, n_sims, params, seed * 10000,
            map_w, map_h)
        elapsed = time.time() - t0
        print(f"  Done in {elapsed:.1f}s")

        predictions[seed] = pred
        log_action(round_id, "build_prediction", {
            "seed_index": seed,
            "method": "local_sim",
            "n_sims": n_sims,
            "prediction": pred,
        })

        if not no_submit:
            print(f"  Submitting seed {seed}...")
            try:
                result = submit(round_id, seed, pred)
                log_submission(round_id, seed, result)
                print(f"  Result: {result}")
            except Exception as e:
                print(f"  Submit ERROR: {e}")
                log_action(round_id, "submit_error", {
                    "seed_index": seed, "error": str(e)})
            time.sleep(0.6)

    if output_path:
        out = {str(k): v for k, v in predictions.items()}
        with open(output_path, "w") as f:
            json.dump(out, f)
        print(f"\nPredictions saved to {output_path}")

    log_action(round_id, "run_local_complete", {"seeds": N_SEEDS})
    print("\nDone!")


def main():
    parser = argparse.ArgumentParser(description="Astar Island local sim pipeline")
    parser.add_argument("--sims", type=int, default=200,
                        help="Monte Carlo simulations per seed (default: 200)")
    parser.add_argument("--params", type=str, default=None,
                        help="Path to custom params JSON file")
    parser.add_argument("--no-submit", action="store_true",
                        help="Generate predictions without submitting")
    parser.add_argument("--output", type=str, default=None,
                        help="Save predictions to JSON file")
    parser.add_argument("--backtest", type=int, default=None, nargs="?", const=-1,
                        help="Backtest against a completed round (number, or latest if omitted)")
    parser.add_argument("--backtest-all", action="store_true",
                        help="Backtest against all completed rounds")
    args = parser.parse_args()

    params = load_custom_params(args.params)

    if args.backtest_all:
        rounds = get_rounds()
        completed = [r for r in rounds if r["status"] == "completed"]
        for r in completed:
            backtest_round(r["id"], r["round_number"], args.sims, params)
        return

    if args.backtest is not None:
        rounds = get_rounds()
        completed = [r for r in rounds if r["status"] == "completed"]
        if args.backtest == -1:
            target = completed[-1]
        else:
            target = next((r for r in completed if r["round_number"] == args.backtest), None)
            if not target:
                print(f"Round {args.backtest} not found or not completed.")
                return
        backtest_round(target["id"], target["round_number"], args.sims, params)
        return

    run_active(args.sims, params, args.no_submit, args.output)


if __name__ == "__main__":
    main()
