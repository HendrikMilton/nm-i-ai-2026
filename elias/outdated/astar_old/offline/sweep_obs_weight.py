"""Sweep MC_EQUIV_SAMPLES to find the optimal observation influence.

Lower equiv_samples = observations contribute more relative to priors.
Current default: 60 (adaptive: 20-100 based on MC agreement).

Runs 20 iterations on round 9 with different equiv_samples values.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.utils import get_rounds, get_round, get_analysis, floor_and_normalize
from offline.simulator import run_monte_carlo, DEFAULT_PARAMS
from offline.score import score_prediction
from offline.abc import run_abc_fit, weighted_mc_from_fitted
from run import (
    N_CLASSES, N_SEEDS, VIEWPORT, WARM_COLD_THRESHOLD,
    ABC_MC_WEIGHT, MC_TOTAL_RUNS,
    parse_initial_grid, extract_map_dimensions,
    get_distance_aware_prior, compute_settlement_distances,
    get_contextual_prior,
    extract_grid_and_settlements,
    build_tiling, run_observation_phases,
    TERRAIN_TO_CLASS,
)
from offline.run_local import observe_seed_local

import random


def generate_prediction_with_equiv(grid, mc_pred, map_w, map_h,
                                    obs_counts, expansion_rate,
                                    dist_multipliers, port_ratio, ruin_ratio,
                                    prior_table, equiv_samples_override):
    """Same as generate_prediction_abc but with a fixed equiv_samples."""
    dist_map = compute_settlement_distances(grid, map_h, map_w)

    mc_w = ABC_MC_WEIGHT if mc_pred is not None else 0.0
    prior_w = 1.0 - mc_w

    prediction = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
    for r in range(map_h):
        for c in range(map_w):
            if dist_map is not None:
                prior = get_distance_aware_prior(grid, r, c, map_h, map_w, dist_map,
                                                  expansion_rate,
                                                  dist_multipliers=dist_multipliers,
                                                  port_ratio=port_ratio,
                                                  ruin_ratio=ruin_ratio,
                                                  prior_table=prior_table)
            else:
                prior = get_contextual_prior(grid, r, c, map_h, map_w, prior_table=prior_table)

            blended = [0.0] * N_CLASSES
            for k in range(N_CLASSES):
                blended[k] = prior_w * prior[k]
                if mc_pred is not None:
                    blended[k] += mc_w * mc_pred[r][c][k]
            total = sum(blended)
            if total > 0:
                blended = [v / total for v in blended]

            n_obs = sum(obs_counts[r][c]) if obs_counts else 0
            if n_obs > 0:
                alpha = [blended[k] * equiv_samples_override for k in range(N_CLASSES)]
                posterior = [alpha[k] + obs_counts[r][c][k] for k in range(N_CLASSES)]
                total = sum(posterior)
                prediction[r][c] = [p / total for p in posterior]
            else:
                prediction[r][c] = blended

    return floor_and_normalize(prediction, obs_counts=obs_counts)


def run_sweep(target_round_num):
    rounds = get_rounds()
    completed = [r for r in rounds if r["status"] == "completed"]
    target = next((r for r in completed if r["round_number"] == target_round_num), None)
    if not target:
        print(f"Round {target_round_num} not found or not completed.")
        return

    round_id = target["id"]
    round_num = target["round_number"]
    budget = 50

    print(f"=== Sweep equiv_samples on Round {round_num} ({round_id[:8]}...) ===\n")

    rd = get_round(round_id)
    map_w, map_h = extract_map_dimensions(rd)

    initial_states = rd.get("initial_states") or []
    seed_grids = {}
    for i, state in enumerate(initial_states):
        grid = state.get("grid") or state.get("terrain") or []
        if grid:
            seed_grids[i] = grid

    # Load ground truth
    seed_gt = {}
    for seed in range(N_SEEDS):
        analysis = get_analysis(round_id, seed)
        seed_gt[seed] = analysis["ground_truth"]

    # Run observation phase once (same observations for all iterations)
    tiling = build_tiling(map_w, map_h)
    seed_viewports = {s: tiling for s in range(N_SEEDS)}
    rng = random.Random(round_num * 7919)
    seed_queries = {s: [] for s in range(N_SEEDS)}

    def local_observe(seed_idx, viewports):
        counts, qlog = observe_seed_local(
            seed_gt[seed_idx], seed_idx, viewports, map_w, map_h, rng)
        seed_queries[seed_idx].extend(qlog)
        return counts

    seed_counts, avg_expansion, dist_multipliers, prior_table, port_ratio, ruin_ratio = run_observation_phases(
        seed_grids, seed_viewports, budget, map_w, map_h,
        observe_fn=local_observe, print_fn=lambda *a: None,
    )

    # ABC parameter fitting (once)
    seed_settlements = {}
    for s in range(N_SEEDS):
        _, sett = extract_grid_and_settlements(rd, s)
        seed_settlements[s] = sett

    is_cold = avg_expansion < WARM_COLD_THRESHOLD
    fitted_params = run_abc_fit(
        seed_grids, seed_settlements, seed_counts,
        map_h, map_w, is_cold=is_cold, rng_seed=round_num * 7919,
        print_fn=lambda *a: None,
    )

    # Pre-compute MC predictions per seed (once)
    print("Pre-computing MC predictions...", flush=True)
    seed_mc = {}
    for seed in range(N_SEEDS):
        grid, settlements = extract_grid_and_settlements(rd, seed)
        seed_mc[seed] = weighted_mc_from_fitted(
            fitted_params, grid, settlements,
            total_runs=MC_TOTAL_RUNS, base_seed=seed * 10000,
            map_h=map_h, map_w=map_w)
    print("Done.\n")

    # Sweep equiv_samples values: 20 iterations
    test_values = [1, 2, 3, 4, 5, 7, 10, 12, 15, 18, 20, 25, 30, 35, 40, 50, 60, 80, 100, 150]

    print(f"{'equiv_samples':>13}  {'round_score':>11}  {'per-seed scores'}")
    print("-" * 70)

    results = []
    for equiv in test_values:
        seed_scores = []
        for seed in range(N_SEEDS):
            grid, _ = extract_grid_and_settlements(rd, seed)
            pred = generate_prediction_with_equiv(
                grid, seed_mc[seed], map_w, map_h,
                obs_counts=seed_counts[seed],
                expansion_rate=avg_expansion,
                dist_multipliers=dist_multipliers,
                port_ratio=port_ratio, ruin_ratio=ruin_ratio,
                prior_table=prior_table,
                equiv_samples_override=equiv)
            result = score_prediction(pred, seed_gt[seed])
            seed_scores.append(result["score"])

        round_score = sum(seed_scores) / len(seed_scores)
        seed_str = "  ".join(f"{s:.1f}" for s in seed_scores)
        print(f"{equiv:>13}  {round_score:>11.2f}  {seed_str}")
        results.append((equiv, round_score, seed_scores))

    print()
    best = max(results, key=lambda x: x[1])
    print(f"Best: equiv_samples={best[0]}, round_score={best[1]:.2f}")
    print(f"Current default (adaptive 20-100, base 60): see equiv_samples=60 row above")


def main():
    import sys
    target_rounds = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [9]
    for rn in target_rounds:
        run_sweep(rn)
        print("\n")


if __name__ == "__main__":
    main()
