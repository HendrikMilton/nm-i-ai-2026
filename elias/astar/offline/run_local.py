"""
Astar Island — Local simulator pipeline.

Modes:
  python offline/run_local.py                  # Run sim + submit on active round
  python offline/run_local.py --no-submit      # Run sim without submitting
  python offline/run_local.py --backtest       # Score against real ground truth (completed rounds)
  python offline/run_local.py --backtest-all   # Score against all completed rounds
  python offline/run_local.py --backtest-full  # Full pipeline backtest with simulated queries
  python offline/run_local.py --backtest-full 3 --budget 30  # Specific round, reduced budget
  python offline/run_local.py --sims 500       # More simulations for better estimates
"""

import argparse
import json
import math
import os
import random
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
    TERRAIN_PRIORS, N_CLASSES, N_SIMS, SIM_WEIGHT, PRIOR_WEIGHT, OBS_WEIGHT,
    TERRAIN_TO_CLASS, VIEWPORT,
    parse_initial_grid, extract_map_dimensions, get_contextual_prior,
    get_distance_aware_prior, compute_settlement_distances,
    estimate_expansion_rate,
    extract_grid_and_settlements, generate_prediction,
    find_dynamic_viewports, merge_counts,
    run_observation_phases,
    log_action, log_submission, _ensure_round, N_SEEDS,
)


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

def load_custom_params(path=None):
    if path and os.path.exists(path):
        with open(path) as f:
            custom = json.load(f)
        params = {**DEFAULT_PARAMS, **custom}
        print(f"Loaded custom params from {path} ({len(custom)} overrides)")
        return params
    return DEFAULT_PARAMS.copy()


# --- Backtest ---

def _estimate_expansion_from_gt(round_id, rd, map_w, map_h):
    """Estimate expansion rate from ground truth, simulating what live observations would give.

    In the live pipeline, we observe single stochastic sims via the API.
    Here we simulate that by sampling from ground truth distributions
    (which are the average of hundreds of sims — close to what N observations would show).

    We use the GT's settlement probability for cells near initial settlements
    as a proxy for what we'd estimate from real observations.
    """
    expansion_rates = []

    for seed in range(N_SEEDS):
        analysis = get_analysis(round_id, seed)
        gt = analysis["ground_truth"]
        ig = analysis["initial_grid"]

        dist_map = compute_settlement_distances(ig, map_h, map_w)

        # Simulate ~8 observation queries (1 pass of viewports)
        # by sampling from GT for cells in expansion range
        settle_obs = 0
        total_obs = 0
        random.seed(seed * 42)

        for r in range(map_h):
            for c in range(map_w):
                terrain = ig[r][c]
                if terrain in (10, 5, 1, 2):
                    continue
                d = dist_map[r][c]
                if d < 1 or d > 3:
                    continue
                # Sample one observation from GT
                probs = gt[r][c]
                rand = random.random()
                cumsum = 0
                cls = 0
                for k in range(6):
                    cumsum += probs[k]
                    if rand < cumsum:
                        cls = k
                        break
                total_obs += 1
                if cls == 1:  # settlement
                    settle_obs += 1

        if total_obs > 0:
            expansion_rates.append((settle_obs / total_obs, total_obs))

    if expansion_rates:
        total_samples = sum(n for _, n in expansion_rates)
        return sum(r * n for r, n in expansion_rates) / total_samples
    return 0.10


def backtest_round(round_id, round_num, n_sims, params,
                   sim_weight=SIM_WEIGHT, prior_weight=PRIOR_WEIGHT,
                   iteration_id=None, config=None, quiet=False):
    """Score predictions against real ground truth for a completed round.

    Uses the same generate_prediction() from run.py that the live pipeline uses.
    Estimates expansion rate from GT to simulate what observations would provide.
    """
    if not quiet:
        print(f"\n=== Backtest Round {round_num} ({round_id[:8]}...) ===")

    rd = get_round(round_id)
    map_w, map_h = extract_map_dimensions(rd)

    # Estimate expansion rate (simulating live observation analysis)
    expansion_rate = _estimate_expansion_from_gt(round_id, rd, map_w, map_h)
    if not quiet:
        print(f"  Expansion rate: {expansion_rate:.3f}")

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
            map_w, map_h, sim_weight=sim_weight, prior_weight=prior_weight,
            expansion_rate=expansion_rate)
        elapsed = time.time() - t0

        # Distance-aware prior-only for comparison
        dist_map = compute_settlement_distances(grid, map_h, map_w)
        prior_pred = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
        for r in range(map_h):
            for c in range(map_w):
                prior_pred[r][c] = get_distance_aware_prior(
                    grid, r, c, map_h, map_w, dist_map, expansion_rate)
        prior_pred = floor_and_normalize(prior_pred)

        sim_result = score_prediction(pred, ground_truth)
        prior_result = score_prediction(prior_pred, ground_truth)

        seed_results[seed] = {
            "sim_score": sim_result["score"],
            "prior_score": prior_result["score"],
            "weighted_kl": sim_result["weighted_kl"],
            "scored_cells": sim_result["scored_cells"],
            "elapsed_s": round(elapsed, 1),
            "initial_grid": grid,
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


# --- Full pipeline backtest (with simulated queries) ---

# Reverse mapping: prediction class → terrain code for simulated query grids
CLASS_TO_TERRAIN_CODE = {0: 11, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}


def simulate_from_gt(ground_truth, rng, vx, vy, vw, vh):
    """Simulate a query against ground truth — returns stochastic terrain grid.

    For each cell in the viewport, samples one terrain class from the GT
    probability distribution, then converts to a terrain code.
    Returns the same format as the real simulate() API: {"grid": [[code, ...], ...]}.
    """
    grid = []
    for r in range(vh):
        row = []
        for c in range(vw):
            map_r = vy + r
            map_c = vx + c
            if 0 <= map_r < len(ground_truth) and 0 <= map_c < len(ground_truth[0]):
                probs = ground_truth[map_r][map_c]
                rand = rng.random()
                cumsum = 0.0
                cls = 0
                for k in range(6):
                    cumsum += probs[k]
                    if rand < cumsum:
                        cls = k
                        break
                row.append(CLASS_TO_TERRAIN_CODE[cls])
            else:
                row.append(11)  # out of bounds → plains
        grid.append(row)
    return {"grid": grid}


def observe_seed_local(ground_truth, seed_index, viewports, map_w, map_h, rng):
    """Local replacement for observe_seed() — uses GT sampling instead of API.

    Returns (counts, query_log) where:
      - counts: H x W x 6 observation count grid
      - query_log: list of {viewport, grid} dicts for logging
    """
    counts = [[[0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
    query_log = []

    for vx, vy in viewports:
        result = simulate_from_gt(ground_truth, rng, vx, vy, VIEWPORT, VIEWPORT)
        grid = result["grid"]

        query_log.append({
            "viewport": {"x": vx, "y": vy, "w": VIEWPORT, "h": VIEWPORT},
            "grid": grid,
        })

        for r, row in enumerate(grid):
            for c, val in enumerate(row):
                map_r = vy + r
                map_c = vx + c
                if 0 <= map_r < map_h and 0 <= map_c < map_w:
                    cls = TERRAIN_TO_CLASS.get(val, 0)
                    counts[map_r][map_c][cls] += 1

    return counts, query_log


def backtest_full_pipeline(round_id, round_num, n_sims, params, budget=50,
                           quiet=False, iteration_id=None, config=None,
                           obs_weight=None, sim_weight=None, prior_weight=None,
                           rng_seed=None):
    """Full pipeline backtest: replays the live main() flow with GT-sampled queries.

    Mirrors run.py main() steps:
      1. Parse grids, find dynamic viewports per seed
      2. Phase 1: observe every seed once
      3. Phase 2: surprise-based allocation of remaining budget
      4. Estimate expansion rate from observations
      5. generate_prediction() with obs + sim + prior
      6. Score against real ground truth
    """
    # Resolve effective weights (allow per-call overrides)
    eff_obs_w = obs_weight if obs_weight is not None else OBS_WEIGHT
    eff_sim_w = sim_weight if sim_weight is not None else SIM_WEIGHT
    eff_prior_w = prior_weight if prior_weight is not None else PRIOR_WEIGHT

    if not quiet:
        print(f"\n=== Full Pipeline Backtest Round {round_num} ({round_id[:8]}...) ===")
        print(f"  Budget: {budget} queries, weights: obs={eff_obs_w} sim={eff_sim_w} prior={eff_prior_w}")

    rd = get_round(round_id)
    map_w, map_h = extract_map_dimensions(rd)

    # Parse per-seed grids
    initial_states = rd.get("initial_states") or []
    seed_grids = {}
    for i, state in enumerate(initial_states):
        grid = state.get("grid") or state.get("terrain") or []
        if grid:
            seed_grids[i] = grid
    initial_grid = seed_grids.get(0, parse_initial_grid(rd, map_w, map_h))

    # Load ground truth per seed
    seed_gt = {}
    for seed in range(N_SEEDS):
        analysis = get_analysis(round_id, seed)
        seed_gt[seed] = analysis["ground_truth"]

    # Find dynamic viewports per seed (greedy set cover)
    seed_dynamic_vps = {}
    for s in range(N_SEEDS):
        grid = seed_grids.get(s, initial_grid)
        seed_dynamic_vps[s] = find_dynamic_viewports(grid, map_w, map_h)

    phase1_total = sum(len(seed_dynamic_vps[s]) for s in range(N_SEEDS))
    if not quiet:
        print(f"  Per-seed viewports: {[len(seed_dynamic_vps[s]) for s in range(N_SEEDS)]}")
        print(f"  Phase 1: {phase1_total} queries, Phase 2: {max(0, budget - phase1_total)} queries")

    # Seeded RNG for reproducibility
    rng = random.Random(rng_seed if rng_seed is not None else round_num * 7919)
    seed_queries = {s: [] for s in range(N_SEEDS)}

    # Use shared observation logic from run.py
    def local_observe(seed_idx, viewports):
        counts, qlog = observe_seed_local(
            seed_gt[seed_idx], seed_idx, viewports, map_w, map_h, rng)
        seed_queries[seed_idx].extend(qlog)
        return counts

    print_fn = (lambda *a: None) if quiet else print

    seed_counts, avg_expansion, dist_multipliers, port_ratio, ruin_ratio = run_observation_phases(
        seed_grids, seed_dynamic_vps, budget, map_w, map_h,
        observe_fn=local_observe, print_fn=print_fn,
    )

    # Generate predictions and score
    seed_results = {}
    for seed in range(N_SEEDS):
        if not quiet:
            print(f"  Seed {seed}: ", end="", flush=True)

        grid, settlements = extract_grid_and_settlements(rd, seed)
        ground_truth = seed_gt[seed]

        t0 = time.time()
        # Full pipeline prediction: obs + sim + prior
        obs_pred = generate_prediction(
            grid, settlements, n_sims, params, seed * 10000,
            map_w, map_h,
            sim_weight=eff_sim_w, prior_weight=eff_prior_w,
            obs_counts=seed_counts[seed], obs_weight=eff_obs_w,
            expansion_rate=avg_expansion, dist_multipliers=dist_multipliers,
            port_ratio=port_ratio, ruin_ratio=ruin_ratio)
        elapsed = time.time() - t0

        # Sim+prior only (no observations) for comparison
        sim_pred = generate_prediction(
            grid, settlements, n_sims, params, seed * 10000,
            map_w, map_h,
            sim_weight=eff_sim_w, prior_weight=eff_prior_w,
            expansion_rate=avg_expansion, dist_multipliers=dist_multipliers,
            port_ratio=port_ratio, ruin_ratio=ruin_ratio)

        # Prior-only for comparison
        dist_map = compute_settlement_distances(grid, map_h, map_w)
        prior_pred = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
        for r in range(map_h):
            for c in range(map_w):
                prior_pred[r][c] = get_distance_aware_prior(
                    grid, r, c, map_h, map_w, dist_map, avg_expansion,
                    dist_multipliers=dist_multipliers)
        prior_pred = floor_and_normalize(prior_pred)

        obs_result = score_prediction(obs_pred, ground_truth)
        sim_result = score_prediction(sim_pred, ground_truth)
        prior_result = score_prediction(prior_pred, ground_truth)

        seed_results[seed] = {
            "obs_score": obs_result["score"],
            "sim_score": sim_result["score"],
            "prior_score": prior_result["score"],
            "weighted_kl": obs_result["weighted_kl"],
            "scored_cells": obs_result["scored_cells"],
            "elapsed_s": round(elapsed, 1),
            "n_queries": len(seed_queries.get(seed, [])),
            "queries": seed_queries.get(seed, []),
            "initial_grid": grid,
            "prediction": obs_pred,
            "ground_truth": ground_truth,
        }

        if not quiet:
            print(f"obs={obs_result['score']:.1f}  sim={sim_result['score']:.1f}  "
                  f"prior={prior_result['score']:.1f}  ({elapsed:.1f}s, {seed_results[seed]['n_queries']}q)")

    # Round score uses obs_score (the full pipeline score)
    scores = [s["obs_score"] for s in seed_results.values()]
    round_score = round(sum(scores) / len(scores), 4) if scores else 0

    save_config = config or {
        "label": f"full_pipeline_b{budget}", "budget": budget, "mode": "full_pipeline",
        "obs_weight": eff_obs_w, "sim_weight": eff_sim_w, "prior_weight": eff_prior_w,
    }
    save_backtest(round_id, round_num, n_sims, seed_results, round_score,
                  iteration_id=iteration_id, config=save_config)

    if not quiet:
        sim_avg = sum(s["sim_score"] for s in seed_results.values()) / N_SEEDS
        prior_avg = sum(s["prior_score"] for s in seed_results.values()) / N_SEEDS
        print(f"\n  Round scores: obs={round_score:.1f}  sim={sim_avg:.1f}  prior={prior_avg:.1f}")
        print(f"  Obs improvement over sim: {round_score - sim_avg:+.1f}")

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
        print(f"  Running {n_sims} Monte Carlo predictions...")

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
                        help="Monte Carlo predictions per seed (default: 200)")
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
    parser.add_argument("--backtest-full", type=int, default=None, nargs="?", const=-1,
                        help="Full pipeline backtest with simulated queries (round number, or latest)")
    parser.add_argument("--budget", type=int, default=50,
                        help="Query budget for --backtest-full (default: 50)")
    args = parser.parse_args()

    params = load_custom_params(args.params)

    if args.backtest_full is not None:
        rounds = get_rounds()
        completed = [r for r in rounds if r["status"] == "completed"]
        if args.backtest_full == -1:
            target = completed[-1]
        else:
            target = next((r for r in completed if r["round_number"] == args.backtest_full), None)
            if not target:
                print(f"Round {args.backtest_full} not found or not completed.")
                return
        backtest_full_pipeline(target["id"], target["round_number"], args.sims, params,
                               budget=args.budget)
        return

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
