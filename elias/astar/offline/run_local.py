"""
Astar Island v2 — Offline backtest runner.

Usage:
  python offline/run_local.py --backtest-full         # Backtest latest completed round
  python offline/run_local.py --backtest-full 3       # Backtest round 3
  python offline/run_local.py --backtest-full -1 --no-abc  # Without ABC fitting
  python offline/run_local.py --backtest-full -1 --budget 30

Key difference from v1: ABC is the default prediction path.
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.utils import get_round, get_rounds, get_analysis
from run import (
    N_CLASSES, N_SEEDS, VIEWPORT, MAP_W, MAP_H,
    TERRAIN_TO_CLASS, WARM_COLD_THRESHOLD,
    MC_TOTAL_RUNS,
    build_tiling, extract_map_dimensions, extract_grid_and_settlements,
    compute_settlement_distances, get_distance_aware_prior,
    generate_prediction, generate_prediction_abc, validate_mc_against_obs,
    SIM_SAFETY_THRESHOLD,
    run_observation_phases, floor_and_normalize,
    aggregate_expansion_stats, pool_observations,
)
from offline.score import score_prediction
from offline.abc import run_abc_fit, weighted_mc_from_fitted


# --- Log storage (same dir + index as v1 for frontend compat) ---
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


def save_backtest(round_id, round_num, seed_results, round_score,
                  iteration_id=None, config=None):
    """Save backtest result in v1-compatible format (full tensors for frontend)."""
    os.makedirs(OFFLINE_DIR, exist_ok=True)

    file_id = iteration_id or f"v2_R{round_num}"

    result = {
        "id": file_id,
        "round_id": round_id,
        "round_number": round_num,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_sims": MC_TOTAL_RUNS,
        "round_score": round_score,
        "config": config or {},
        "seeds": {str(k): v for k, v in seed_results.items()},
    }

    path = os.path.join(OFFLINE_DIR, f"{file_id}.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)

    # Update shared index
    index = _load_offline_index()
    index["backtests"] = [b for b in index["backtests"] if b.get("id", b.get("round_id")) != file_id]
    index["backtests"].append({
        "id": file_id,
        "round_id": round_id,
        "round_number": round_num,
        "timestamp": result["timestamp"],
        "round_score": round_score,
        "n_sims": MC_TOTAL_RUNS,
        "config": config or {},
    })
    index["backtests"].sort(key=lambda b: (b.get("round_number", 0), b.get("timestamp", "")))
    _save_offline_index(index)

    return path


# --- GT-based observation simulation ---

CLASS_TO_TERRAIN_CODE = {0: 11, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}


def simulate_from_gt(ground_truth, rng, vx, vy, vw, vh):
    """Sample a stochastic terrain grid from ground truth probabilities."""
    grid = []
    for r in range(vh):
        row = []
        for c in range(vw):
            map_r, map_c = vy + r, vx + c
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
                row.append(11)
        grid.append(row)
    return {"grid": grid}


def observe_seed_local(ground_truth, seed_index, viewports, map_w, map_h, rng,
                       query_log=None):
    """Local observation using GT sampling. Appends to query_log if provided."""
    counts = [[[0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
    for vx, vy in viewports:
        result = simulate_from_gt(ground_truth, rng, vx, vy, VIEWPORT, VIEWPORT)
        grid = result["grid"]

        if query_log is not None:
            query_log.append({
                "viewport": {"x": vx, "y": vy, "w": VIEWPORT, "h": VIEWPORT},
                "grid": grid,
            })

        for r, row in enumerate(grid):
            for c, val in enumerate(row):
                map_r, map_c = vy + r, vx + c
                if 0 <= map_r < map_h and 0 <= map_c < map_w:
                    cls = TERRAIN_TO_CLASS.get(val, 0)
                    counts[map_r][map_c][cls] += 1
    return counts


# --- Full pipeline backtest ---

def backtest_full_pipeline(round_id, round_num, budget=50,
                           use_abc=True, rng_seed=None, quiet=False,
                           iteration_id=None):
    """Full pipeline backtest with GT-sampled queries.

    With use_abc=True (default), runs the ABC parameter fitting path.
    This is the primary pipeline — not an afterthought like in v1.
    """
    if not quiet:
        print(f"\n{'='*60}")
        print(f"  v2 Backtest — Round {round_num} ({round_id[:8]}...)")
        print(f"  Budget: {budget}, ABC: {use_abc}")
        if iteration_id:
            print(f"  Name: {iteration_id}")
        print(f"{'='*60}")

    rd = get_round(round_id)
    map_w, map_h = extract_map_dimensions(rd)

    if not quiet:
        print(f"  Map: {map_w}x{map_h}")

    # Parse per-seed grids
    initial_states = rd.get("initial_states") or []
    seed_grids = {}
    for i, state in enumerate(initial_states):
        grid = state.get("grid") or state.get("terrain") or []
        if grid:
            seed_grids[i] = grid

    if not quiet:
        for si in sorted(seed_grids.keys()):
            g = seed_grids[si]
            n_settle = sum(1 for r in g for c in r if c in (1, 2))
            n_forest = sum(1 for r in g for c in r if c == 4)
            print(f"  Seed {si}: {n_settle} settlements/ports, {n_forest} forests")

    # Load ground truth
    seed_gt = {}
    for seed in range(N_SEEDS):
        analysis = get_analysis(round_id, seed)
        seed_gt[seed] = analysis["ground_truth"]

    # Build tiling
    if not quiet:
        tiling = build_tiling(map_w, map_h)
        print(f"  Tiling: {len(tiling)} viewports per seed")

    rng = random.Random(rng_seed if rng_seed is not None else round_num * 7919)
    seed_queries = {s: [] for s in range(N_SEEDS)}

    def local_observe(seed_idx, viewports):
        return observe_seed_local(seed_gt[seed_idx], seed_idx, viewports, map_w, map_h, rng,
                                   query_log=seed_queries[seed_idx])

    print_fn = (lambda *a: None) if quiet else print

    # Run observations
    (seed_counts, avg_expansion, dist_multipliers, prior_table,
     port_ratio, ruin_ratio, warmth, survival_rate, forest_change_rate, coastal_pref) = \
        run_observation_phases(
            seed_grids, budget, map_w, map_h,
            observe_fn=local_observe, print_fn=print_fn,
        )

    # ABC parameter fitting (default ON)
    fitted_params = None
    if use_abc:
        seed_settlements = {}
        for s in range(N_SEEDS):
            _, sett = extract_grid_and_settlements(rd, s)
            seed_settlements[s] = sett

        is_cold = avg_expansion < WARM_COLD_THRESHOLD
        fitted_params = run_abc_fit(
            seed_grids, seed_settlements, seed_counts,
            map_h, map_w, is_cold=is_cold, rng_seed=round_num * 7919,
            print_fn=print_fn,
        )

    # Each seed has a different procedurally generated map (~700 cells differ).
    # On cold rounds, pool observations across seeds — noisy but better than
    # near-zero per-seed data. The Bayesian update with high equiv_samples
    # naturally downweights the noise.
    is_cold = warmth == "cold"
    if is_cold:
        pooled_counts = pool_observations(seed_counts, map_w, map_h)
        print_fn(f"  Cold round: using pooled observations across all seeds")

    # Generate predictions and score
    seed_results = {}
    for seed in range(N_SEEDS):
        if not quiet:
            print(f"  Seed {seed}: ", end="", flush=True)

        grid, settlements = extract_grid_and_settlements(rd, seed)
        ground_truth = seed_gt[seed]

        effective_obs = pooled_counts if is_cold else seed_counts[seed]

        t0 = time.time()

        if use_abc and fitted_params:
            # ABC path: weighted MC + three-layer blend
            mc_pred = weighted_mc_from_fitted(
                fitted_params, grid, settlements,
                total_runs=MC_TOTAL_RUNS, base_seed=seed * 10000,
                map_h=map_h, map_w=map_w)

            # Log MC validation
            if mc_pred is not None and not quiet:
                mc_agree, mc_compared = validate_mc_against_obs(
                    mc_pred, effective_obs, map_h, map_w)
                if mc_compared == 0:
                    mc_status = "USED (no obs)"
                elif mc_agree >= SIM_SAFETY_THRESHOLD:
                    mc_status = "USED"
                else:
                    mc_status = "SKIPPED"
                print(f"MC agree={mc_agree:.1%} ({mc_compared} cells) → {mc_status}  ", end="", flush=True)

            obs_pred = generate_prediction_abc(
                grid, mc_pred, map_w, map_h,
                obs_counts=effective_obs,
                expansion_rate=avg_expansion, dist_multipliers=dist_multipliers,
                port_ratio=port_ratio, ruin_ratio=ruin_ratio,
                prior_table=prior_table, warmth=warmth,
                survival_rate=survival_rate, forest_change_rate=forest_change_rate,
                coastal_preference=coastal_pref)
        else:
            # Non-ABC path: obs + sim + prior (with warm/cold sim weight)
            from offline.simulator import run_monte_carlo, DEFAULT_PARAMS
            sim_pred = run_monte_carlo(grid, settlements, n_sims=200,
                                        params=DEFAULT_PARAMS, base_seed=seed * 10000)
            obs_pred = generate_prediction(
                grid, settlements, map_w, map_h,
                obs_counts=effective_obs, sim_pred=sim_pred,
                expansion_rate=avg_expansion, dist_multipliers=dist_multipliers,
                port_ratio=port_ratio, ruin_ratio=ruin_ratio,
                prior_table=prior_table, warmth=warmth,
                survival_rate=survival_rate, forest_change_rate=forest_change_rate,
                coastal_preference=coastal_pref)

        elapsed = time.time() - t0

        # Prior-only baseline for comparison
        dist_map = compute_settlement_distances(grid, map_h, map_w)
        prior_pred = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
        for r in range(map_h):
            for c in range(map_w):
                prior_pred[r][c] = get_distance_aware_prior(
                    grid, r, c, map_h, map_w, dist_map, avg_expansion,
                    dist_multipliers=dist_multipliers,
                    port_ratio=port_ratio, ruin_ratio=ruin_ratio,
                    prior_table=prior_table, survival_rate=survival_rate,
                    forest_change_rate=forest_change_rate,
                    coastal_preference=coastal_pref)
        prior_pred = floor_and_normalize(prior_pred)

        obs_result = score_prediction(obs_pred, ground_truth)
        prior_result = score_prediction(prior_pred, ground_truth)

        # Count observations per cell for this seed
        n_observed = sum(1 for r in range(map_h) for c in range(map_w)
                         if sum(effective_obs[r][c]) > 0)
        total_obs = sum(sum(effective_obs[r][c]) for r in range(map_h) for c in range(map_w))

        # Count initial settlements for this seed
        n_initial_settle = sum(1 for r in grid for c in r if c in (1, 2))

        seed_results[seed] = {
            "obs_score": obs_result["score"],
            "prior_score": prior_result["score"],
            "weighted_kl": obs_result["weighted_kl"],
            "prior_weighted_kl": prior_result["weighted_kl"],
            "scored_cells": obs_result["scored_cells"],
            "n_initial_settlements": n_initial_settle,
            "n_observed_cells": n_observed,
            "total_observations": total_obs,
            "elapsed_s": round(elapsed, 1),
            "n_queries": len(seed_queries.get(seed, [])),
            "worst_cells": [(r, c, round(ekl, 4), round(kl, 4), round(ent, 4))
                            for r, c, ekl, kl, ent in obs_result["worst_cells"][:10]],
            "queries": seed_queries.get(seed, []),
            "initial_grid": grid,
            "prediction": obs_pred,
            "ground_truth": ground_truth,
        }

        if not quiet:
            delta = obs_result['score'] - prior_result['score']
            print(f"pipeline={obs_result['score']:.1f}  "
                  f"prior={prior_result['score']:.1f}  "
                  f"delta={delta:+.1f}  "
                  f"kl={obs_result['weighted_kl']:.4f}  "
                  f"cells={obs_result['scored_cells']}  "
                  f"obs={n_observed}/{map_w*map_h}  "
                  f"({elapsed:.1f}s)")

    # Round score
    scores = [s["obs_score"] for s in seed_results.values()]
    round_score = round(sum(scores) / len(scores), 4) if scores else 0

    config = {
        "mode": "abc" if use_abc else "legacy",
        "budget": budget,
        "warmth": warmth,
        "expansion_rate": round(avg_expansion, 4),
    }
    saved_path = save_backtest(round_id, round_num, seed_results, round_score,
                               iteration_id=iteration_id, config=config)

    if not quiet:
        prior_avg = sum(s["prior_score"] for s in seed_results.values()) / N_SEEDS
        print(f"\n  {'─'*50}")
        print(f"  Round score: {round_score:.1f}  (prior baseline: {prior_avg:.1f})")
        print(f"  Pipeline improvement: {round_score - prior_avg:+.1f}")

        # Per-seed summary table
        worst_seed = min(seed_results, key=lambda s: seed_results[s]["obs_score"])
        best_seed = max(seed_results, key=lambda s: seed_results[s]["obs_score"])
        print(f"  Best seed: {best_seed} ({seed_results[best_seed]['obs_score']:.1f})")
        print(f"  Worst seed: {worst_seed} ({seed_results[worst_seed]['obs_score']:.1f})")
        spread = seed_results[best_seed]["obs_score"] - seed_results[worst_seed]["obs_score"]
        print(f"  Spread: {spread:.1f}")

        # Show top 5 worst cells from the worst seed
        worst_cells = seed_results[worst_seed].get("worst_cells", [])
        if worst_cells:
            print(f"\n  Worst cells (seed {worst_seed}):")
            print(f"  {'(r,c)':<10} {'ent*kl':<10} {'kl':<10} {'entropy':<10}")
            for r, c, ekl, kl, ent in worst_cells[:5]:
                print(f"  ({r},{c}){'':<5} {ekl:<10.4f} {kl:<10.4f} {ent:<10.4f}")

        print(f"\n  Saved to: {saved_path}")

    return seed_results, round_score


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(description="Astar Island v2 — offline backtest")
    parser.add_argument("--backtest-full", type=int, default=None, nargs="?", const=-1,
                        help="Full pipeline backtest (round number, or -1 for latest)")
    parser.add_argument("--budget", type=int, default=50,
                        help="Query budget (default: 50)")
    parser.add_argument("--no-abc", action="store_true",
                        help="Disable ABC fitting (use legacy obs+sim+prior)")
    parser.add_argument("--all-rounds", action="store_true",
                        help="Backtest all completed rounds")
    parser.add_argument("--name", type=str, default=None,
                        help="Name for this backtest run (used as file ID)")
    args = parser.parse_args()

    if args.all_rounds:
        rounds = get_rounds()
        completed = [r for r in rounds if r["status"] == "completed"]
        all_scores = []
        for target in completed:
            _, score = backtest_full_pipeline(
                target["id"], target["round_number"],
                budget=args.budget, use_abc=not args.no_abc)
            all_scores.append((target["round_number"], score))

        print(f"\n{'='*40}")
        print("  ALL ROUNDS SUMMARY")
        print(f"{'='*40}")
        for rn, score in all_scores:
            print(f"  Round {rn}: {score:.1f}")
        avg = sum(s for _, s in all_scores) / len(all_scores) if all_scores else 0
        print(f"  Average: {avg:.1f}")
        return

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
        backtest_full_pipeline(
            target["id"], target["round_number"],
            budget=args.budget, use_abc=not args.no_abc,
            iteration_id=args.name)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
