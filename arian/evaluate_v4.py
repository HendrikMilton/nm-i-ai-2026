"""
Local evaluation for predict_v4 (distance-aware prior) vs predict_v3 (ABC+MC).

Usage:
    python evaluate_v4.py                  # 1 map, 5 seeds
    python evaluate_v4.py --maps 5 --compare
"""
import argparse
import time
import uuid
import numpy as np

from simulator import (
    SimParams, run_simulation,
    parse_initial_grid, apply_static_overrides,
    monte_carlo_predict,
    OCEAN, MOUNTAIN,
)
from evaluate import (
    generate_synthetic_map,
    compute_ground_truth,
    entropy_weighted_kl,
    kl_to_score,
)
from predict_v4 import (
    compute_settlement_distances,
    estimate_expansion_rate,
    estimate_dist_decay,
    estimate_port_ruin_ratios,
    build_prediction,
    empty_counts,
    DIST_DECAY_DEFAULT,
)
from dashboard_logger import log_offline_backtest


def simulate_obs_counts(grid_list, settlements_data, true_params, map_h, map_w, n_seeds=5, rng=None):
    """Simulate API observations as H×W×6 counts per seed."""
    if rng is None:
        rng = np.random.default_rng(0)
    grid = [[int(v) for v in row] for row in grid_list]

    seed_counts = {}
    for s in range(n_seeds):
        counts = empty_counts(map_h, map_w)
        run_rng = np.random.default_rng(int(rng.integers(2**31)))
        final = run_simulation(grid_list, settlements_data, true_params, run_rng)
        for r in range(map_h):
            for c in range(map_w):
                cls = int(final[r, c])
                counts[r][c][cls] += 1
        seed_counts[s] = counts
    return seed_counts


def eval_v4(grid_list, settlements_data, ground_truth, initial_grid, true_params,
            n_seeds=5, rng=None):
    """V4: distance-aware prior with expansion rate from observations."""
    if rng is None:
        rng = np.random.default_rng(0)

    map_h, map_w = initial_grid.shape
    # Convert numpy grid to list-of-lists for distance functions
    grid = [[int(initial_grid[r, c]) for c in range(map_w)] for r in range(map_h)]

    seed_counts = simulate_obs_counts(
        grid_list, settlements_data, true_params,
        map_h, map_w, n_seeds=n_seeds, rng=rng
    )

    # Aggregate across seeds for expansion rate + decay estimation
    dist_map = compute_settlement_distances(grid, map_h, map_w)
    expansion_rates = []
    agg_dist_stats = {}

    for s in range(n_seeds):
        rate, n_samp = estimate_expansion_rate(seed_counts[s], grid, dist_map, map_h, map_w)
        if n_samp > 0:
            expansion_rates.append((rate, n_samp))
        for r in range(map_h):
            for c in range(map_w):
                n = sum(seed_counts[s][r][c])
                if n == 0 or grid[r][c] in (10, 5, 1, 2):
                    continue
                d = dist_map[r][c]
                if 1 <= d <= 7:
                    if d not in agg_dist_stats:
                        agg_dist_stats[d] = [0, 0]
                    agg_dist_stats[d][0] += seed_counts[s][r][c][1]
                    agg_dist_stats[d][1] += n

    if expansion_rates:
        total_samp = sum(n for _, n in expansion_rates)
        avg_expansion = sum(r * n for r, n in expansion_rates) / total_samp
    else:
        avg_expansion = 0.10

    d13_settle = sum(agg_dist_stats.get(d, [0, 0])[0] for d in [1, 2, 3])
    d13_total  = sum(agg_dist_stats.get(d, [0, 0])[1] for d in [1, 2, 3])
    base_rate  = d13_settle / d13_total if d13_total > 0 else avg_expansion

    dist_multipliers = {}
    for d in range(1, 8):
        if d in agg_dist_stats and agg_dist_stats[d][1] >= 10 and base_rate > 0.001:
            dist_multipliers[d] = (agg_dist_stats[d][0] / agg_dist_stats[d][1]) / base_rate
        else:
            dist_multipliers[d] = DIST_DECAY_DEFAULT.get(d, 0.0)

    port_ratio, ruin_ratio = estimate_port_ruin_ratios(
        {s: grid for s in range(n_seeds)}, seed_counts, map_h, map_w
    )

    # Build prediction (same for all seeds — same map, same params)
    pred = build_prediction(
        grid, map_h, map_w, dist_map, avg_expansion,
        dist_multipliers=dist_multipliers,
        port_ratio=port_ratio, ruin_ratio=ruin_ratio,
    )

    wkl = entropy_weighted_kl(ground_truth, pred)
    score = kl_to_score(wkl)
    return score, wkl, pred, avg_expansion


def eval_v1_baseline(grid_list, settlements_data, ground_truth, initial_grid):
    """V1 baseline: blind MC over broad param ranges."""
    pred = monte_carlo_predict(grid_list, settlements_data, n_runs=200, param_samples=15, seed=42)
    pred = apply_static_overrides(pred, initial_grid)
    wkl = entropy_weighted_kl(ground_truth, pred)
    return kl_to_score(wkl), wkl, pred


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--maps",    type=int, default=1)
    parser.add_argument("--seeds",   type=int, default=5)
    parser.add_argument("--gt-runs", type=int, default=500)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--seed",    type=int, default=42)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    run_id = str(uuid.uuid4())[:8]
    all_v4 = []
    all_v1 = []

    for map_idx in range(args.maps):
        print(f"\n{'='*60}")
        print(f"Map {map_idx+1}/{args.maps}")
        print(f"{'='*60}")

        map_rng = np.random.default_rng(int(rng.integers(2**31)))
        grid_list, settlements_data = generate_synthetic_map(map_rng)
        initial_grid = parse_initial_grid(grid_list)
        dynamic_cells = int(((initial_grid != OCEAN) & (initial_grid != MOUNTAIN)).sum())

        true_params = SimParams(
            expansion_rate=float(rng.uniform(0.05, 0.60)),
            conflict_prob=float(rng.uniform(0.05, 0.50)),
            winter_severity=float(rng.uniform(0.10, 0.70)),
            trade_range=int(rng.integers(4, 13)),
            ruin_reclaim_rate=float(rng.uniform(0.10, 0.60)),
            forest_reclaim_rate=float(rng.uniform(0.02, 0.25)),
            longship_prob=float(rng.uniform(0.05, 0.40)),
            longship_range=int(rng.integers(5, 16)),
        )
        print(f"  True params: exp={true_params.expansion_rate:.3f} "
              f"conf={true_params.conflict_prob:.3f} win={true_params.winter_severity:.3f}")

        # Ground truth
        print(f"  Ground truth ({args.gt_runs} runs)...")
        t0 = time.time()
        gt_rng = np.random.default_rng(int(rng.integers(2**31)))
        ground_truth = compute_ground_truth(grid_list, settlements_data, true_params, args.gt_runs, gt_rng)
        print(f"  GT done in {time.time()-t0:.1f}s")

        # V4
        obs_rng = np.random.default_rng(int(rng.integers(2**31)))
        t0 = time.time()
        v4_score, v4_wkl, v4_pred, est_exp = eval_v4(
            grid_list, settlements_data, ground_truth, initial_grid, true_params,
            n_seeds=args.seeds, rng=obs_rng,
        )
        elapsed = time.time() - t0
        print(f"  V4: score={v4_score:.1f}  wkl={v4_wkl:.4f}  exp_est={est_exp:.3f} ({elapsed:.1f}s)")
        all_v4.append(v4_score)

        log_offline_backtest(
            round_id=f"v4_{run_id}_map{map_idx+1}",
            round_number=map_idx+1,
            round_score=round(v4_score, 2),
            n_sims=0,
            seeds={str(i): {"sim_score": round(v4_score, 2), "prior_score": round(v4_score, 2),
                             "weighted_kl": round(v4_wkl, 4), "scored_cells": dynamic_cells,
                             "elapsed_s": round(elapsed, 1),
                             "prediction": v4_pred.tolist(), "ground_truth": ground_truth.tolist()}
                   for i in range(args.seeds)},
            config={"pipeline": "v4", "label": f"v4 dist-prior map{map_idx+1}",
                    "true_expansion": round(true_params.expansion_rate, 3)},
            label=f"v4_{run_id}_map{map_idx+1}",
        )

        if args.compare:
            t0 = time.time()
            v1_score, v1_wkl, _ = eval_v1_baseline(grid_list, settlements_data, ground_truth, initial_grid)
            print(f"  V1: score={v1_score:.1f}  wkl={v1_wkl:.4f}  ({time.time()-t0:.1f}s)")
            print(f"  Delta V4 vs V1: {v4_score - v1_score:+.1f}")
            all_v1.append(v1_score)

    print(f"\n{'='*60}")
    print(f"FINAL: {args.maps} maps × {args.seeds} seeds")
    print(f"V4 mean: {np.mean(all_v4):.2f}/100  "
          f"(range {min(all_v4):.1f} – {max(all_v4):.1f})")
    if args.compare:
        print(f"V1 mean: {np.mean(all_v1):.2f}/100")
        print(f"Improvement: {np.mean(all_v4)-np.mean(all_v1):+.2f} pts")


if __name__ == "__main__":
    main()
