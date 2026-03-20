"""
Astar Island — Local simulator pipeline.

Modes:
  python offline/run_local.py                  # Run sim + submit on active round
  python offline/run_local.py --no-submit      # Run sim without submitting
  python offline/run_local.py --backtest       # Score against real ground truth (completed rounds)
  python offline/run_local.py --backtest-all   # Score against all completed rounds
  python offline/run_local.py --sims 500       # More simulations for better estimates
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
    TERRAIN_PRIORS, N_CLASSES, MIN_OBS_TO_BLEND,
    parse_initial_grid, extract_map_dimensions, get_contextual_prior,
    counts_to_prediction_v3, log_action, log_submission, _ensure_round,
)

N_SEEDS = 5

# --- Offline log storage ---
OFFLINE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "offline")
OFFLINE_INDEX = os.path.join(OFFLINE_DIR, "index.json")


def _load_offline_index():
    if os.path.exists(OFFLINE_INDEX):
        with open(OFFLINE_INDEX) as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {"backtests": []}


def _save_offline_index(index):
    os.makedirs(OFFLINE_DIR, exist_ok=True)
    with open(OFFLINE_INDEX, "w") as f:
        json.dump(index, f, indent=2)


def save_backtest(round_id, round_num, n_sims, seed_results, round_score,
                  iteration_id=None, config=None):
    """Save a backtest result and update the index.

    If iteration_id is provided, saves as logs/offline/<iteration_id>.json
    Otherwise saves as logs/offline/<round_id>.json (legacy single-run mode).
    """
    os.makedirs(OFFLINE_DIR, exist_ok=True)

    file_id = iteration_id or round_id
    result = {
        "id": file_id,
        "round_id": round_id,
        "round_number": round_num,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_sims": n_sims,
        "round_score": round_score,
        "config": config or {},
        "seeds": seed_results,
    }

    path = os.path.join(OFFLINE_DIR, f"{file_id}.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)

    # Update index
    index = _load_offline_index()
    # Remove existing entry with same id
    index["backtests"] = [b for b in index["backtests"] if b.get("id", b.get("round_id")) != file_id]
    index["backtests"].append({
        "id": file_id,
        "round_id": round_id,
        "round_number": round_num,
        "timestamp": result["timestamp"],
        "round_score": round_score,
        "n_sims": n_sims,
        "config": config or {},
    })
    index["backtests"].sort(key=lambda b: (b.get("round_number", 0), b.get("timestamp", "")))
    _save_offline_index(index)


# --- Prediction generation ---

def extract_grid_and_settlements(round_data, seed_index):
    """Extract initial grid and settlement data for a specific seed."""
    initial_states = round_data.get("initial_states") or []
    if seed_index >= len(initial_states):
        raise ValueError(
            f"Seed index {seed_index} not found (only {len(initial_states)} seeds)")

    state = initial_states[seed_index]
    grid = state.get("grid") or state.get("terrain") or []
    settlements = state.get("settlements") or []

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
    if path and os.path.exists(path):
        with open(path) as f:
            custom = json.load(f)
        params = {**DEFAULT_PARAMS, **custom}
        print(f"Loaded custom params from {path} ({len(custom)} overrides)")
        return params
    return DEFAULT_PARAMS.copy()


def generate_prediction(grid, settlements, n_sims, params, base_seed, map_w, map_h,
                        sim_weight=0.5, prior_weight=4.0):
    """Generate prediction by blending simulator Monte Carlo with learned priors."""
    sim_pred = run_monte_carlo(grid, settlements, n_sims=n_sims, params=params, base_seed=base_seed)

    prediction = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
    for r in range(map_h):
        for c in range(map_w):
            prior = get_contextual_prior(grid, r, c, map_h, map_w)
            for k in range(N_CLASSES):
                prediction[r][c][k] = (
                    sim_weight * sim_pred[r][c][k] + prior_weight * prior[k]
                ) / (sim_weight + prior_weight)

    return floor_and_normalize(prediction)


# --- Backtest ---

def backtest_round(round_id, round_num, n_sims, params,
                   sim_weight=0.5, prior_weight=4.0, min_obs=None,
                   iteration_id=None, config=None, quiet=False):
    """Score predictions against real ground truth for a completed round."""
    if not quiet:
        print(f"\n=== Backtest Round {round_num} ({round_id[:8]}...) ===")

    rd = get_round(round_id)
    map_w, map_h = extract_map_dimensions(rd)

    seed_results = {}

    for seed in range(N_SEEDS):
        if not quiet:
            print(f"  Seed {seed}: ", end="", flush=True)

        analysis = get_analysis(round_id, seed)
        ground_truth = analysis["ground_truth"]

        grid, settlements = extract_grid_and_settlements(rd, seed)
        t0 = time.time()
        pred = generate_prediction(
            grid, settlements, n_sims, params, seed * 10000,
            map_w, map_h, sim_weight=sim_weight, prior_weight=prior_weight)
        elapsed = time.time() - t0

        # If min_obs override, apply v3 logic: only trust cells with enough obs
        if min_obs is not None:
            sim_pred = run_monte_carlo(grid, settlements, n_sims=n_sims,
                                       params=params, base_seed=seed * 10000)
            for r in range(map_h):
                for c in range(map_w):
                    # Check how "dynamic" the sim thinks this cell is
                    max_sim = max(sim_pred[r][c])
                    if max_sim > 0.95:
                        # Sim is confident — trust it at reduced weight
                        pass
                    # The generate_prediction already handles blending

        # Contextual-prior-only for comparison
        prior_pred = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
        for r in range(map_h):
            for c in range(map_w):
                prior_pred[r][c] = get_contextual_prior(grid, r, c, map_h, map_w)
        prior_pred = floor_and_normalize(prior_pred)

        sim_result = score_prediction(pred, ground_truth)
        prior_result = score_prediction(prior_pred, ground_truth)

        seed_results[seed] = {
            "sim_score": sim_result["score"],
            "prior_score": prior_result["score"],
            "weighted_kl": sim_result["weighted_kl"],
            "scored_cells": sim_result["scored_cells"],
            "elapsed_s": round(elapsed, 1),
            "prediction": pred,
            "ground_truth": ground_truth,
        }

        if not quiet:
            print(f"sim={sim_result['score']:.1f}  prior={prior_result['score']:.1f}  ({elapsed:.1f}s)")

    scores = [s["sim_score"] for s in seed_results.values()]
    round_score = round(sum(scores) / len(scores), 4) if scores else 0

    save_backtest(round_id, round_num, n_sims, seed_results, round_score,
                  iteration_id=iteration_id, config=config)

    if not quiet:
        print(f"\n  Round score: {round_score}")
    return seed_results, round_score


# --- Active round ---

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
