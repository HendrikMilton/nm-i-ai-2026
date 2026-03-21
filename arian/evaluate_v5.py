"""
Local evaluation for V5 hybrid pipeline.
Simulates API observations to calibrate priors, then uses MC + KT floors.

Usage:
    python evaluate_v5.py --maps 3 --gt-runs 100
    python evaluate_v5.py --maps 3 --gt-runs 100 --compare
"""
import argparse
import time
import numpy as np

from simulator import (
    SimParams, run_simulation, parse_initial_grid,
    apply_static_overrides, monte_carlo_predict,
    OCEAN, MOUNTAIN,
)
from evaluate import (
    generate_synthetic_map, compute_ground_truth,
    entropy_weighted_kl, kl_to_score,
)
from predict_v5 import (
    run_mc_simulations, build_hybrid_prediction, empty_counts,
    predict_seed_v5_offline,
)
from predict_v4 import (
    compute_settlement_distances, estimate_expansion_rate,
    estimate_port_ruin_ratios, DIST_DECAY_DEFAULT,
)


def simulate_observations(grid_list, settlements_data, true_params, map_h, map_w,
                          n_obs_per_seed=1, n_seeds=5, rng=None):
    """Simulate API observations: run simulator n_obs_per_seed times per seed."""
    if rng is None:
        rng = np.random.default_rng(0)

    seed_counts = {}
    for s in range(n_seeds):
        counts = empty_counts(map_h, map_w)
        for _ in range(n_obs_per_seed):
            run_rng = np.random.default_rng(int(rng.integers(2**31)))
            final = run_simulation(grid_list, settlements_data, true_params, run_rng)
            for r in range(map_h):
                for c in range(map_w):
                    cls = int(final[r, c])
                    counts[r][c][cls] += 1
        seed_counts[s] = counts
    return seed_counts


def eval_v5(grid_list, settlements_data, ground_truth, true_params,
            n_obs_per_seed=1, n_seeds=5,
            n_mc_params=100, mc_runs_per_param=8,
            mc_weight=0.6, prior_weight=0.4,
            temperature=0.95, dirichlet_equiv=40,
            rng=None):
    """Run V5 evaluation with simulated observations."""
    if rng is None:
        rng = np.random.default_rng(0)

    H, W = len(grid_list), len(grid_list[0])
    grid = [[int(grid_list[r][c]) for c in range(W)] for r in range(H)]

    # Simulate observations
    seed_counts = simulate_observations(
        grid_list, settlements_data, true_params, H, W,
        n_obs_per_seed=n_obs_per_seed, n_seeds=n_seeds, rng=rng,
    )

    # Estimate expansion rate from observations
    dist_map = compute_settlement_distances(grid, H, W)
    expansion_rates = []
    agg_dist_stats = {}

    for s in range(n_seeds):
        rate, n_samp = estimate_expansion_rate(seed_counts[s], grid, dist_map, H, W)
        if n_samp > 0:
            expansion_rates.append((rate, n_samp))
        for r in range(H):
            for c in range(W):
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
    d13_total = sum(agg_dist_stats.get(d, [0, 0])[1] for d in [1, 2, 3])
    base_rate = d13_settle / d13_total if d13_total > 0 else avg_expansion

    dist_multipliers = {}
    for d in range(1, 8):
        if d in agg_dist_stats and agg_dist_stats[d][1] >= 10 and base_rate > 0.001:
            dist_multipliers[d] = (agg_dist_stats[d][0] / agg_dist_stats[d][1]) / base_rate
        else:
            dist_multipliers[d] = DIST_DECAY_DEFAULT.get(d, 0.0)

    port_ratio, ruin_ratio = estimate_port_ruin_ratios(
        {s: grid for s in range(n_seeds)}, seed_counts, H, W
    )

    # Run MC
    mc_counts, mc_total = run_mc_simulations(
        grid_list, settlements_data,
        n_params=n_mc_params, runs_per_param=mc_runs_per_param,
        seed=42, workers=1,
    )

    # Build hybrid prediction
    pred = build_hybrid_prediction(
        grid_list, settlements_data,
        mc_counts, mc_total,
        seed_counts,
        expansion_rate=avg_expansion,
        dist_multipliers=dist_multipliers,
        port_ratio=port_ratio, ruin_ratio=ruin_ratio,
        mc_weight=mc_weight, prior_weight=prior_weight,
        temperature=temperature,
        dirichlet_equiv=dirichlet_equiv,
    )

    wkl = entropy_weighted_kl(ground_truth, pred)
    score = kl_to_score(wkl)
    return score, wkl, avg_expansion


def main():
    parser = argparse.ArgumentParser(description="V5 local evaluation")
    parser.add_argument("--maps", type=int, default=3)
    parser.add_argument("--gt-runs", type=int, default=100)
    parser.add_argument("--obs-per-seed", type=int, default=1)
    parser.add_argument("--n-seeds", type=int, default=5)
    parser.add_argument("--mc-params", type=int, default=100)
    parser.add_argument("--mc-runs", type=int, default=8)
    parser.add_argument("--mc-weight", type=float, default=0.6)
    parser.add_argument("--prior-weight", type=float, default=0.4)
    parser.add_argument("--temperature", type=float, default=0.95)
    parser.add_argument("--dirichlet-equiv", type=int, default=40)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    all_v5 = []
    all_v3 = []

    print(f"V5 Evaluation: {args.maps} maps, {args.gt_runs} GT runs, "
          f"{args.obs_per_seed} obs/seed, MC={args.mc_params}×{args.mc_runs}")
    print(f"mc_w={args.mc_weight}, prior_w={args.prior_weight}, T={args.temperature}, "
          f"dirichlet={args.dirichlet_equiv}")
    print()

    for map_idx in range(args.maps):
        print(f"[Map {map_idx+1}/{args.maps}]")
        map_rng = np.random.default_rng(int(rng.integers(2**31)))
        grid_list, settlements_data = generate_synthetic_map(map_rng)

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
        print(f"  True: exp={true_params.expansion_rate:.3f} "
              f"conf={true_params.conflict_prob:.3f} win={true_params.winter_severity:.3f}")

        t0 = time.time()
        gt_rng = np.random.default_rng(int(rng.integers(2**31)))
        ground_truth = compute_ground_truth(grid_list, settlements_data, true_params, args.gt_runs, gt_rng)
        print(f"  GT: {time.time()-t0:.1f}s")

        obs_rng = np.random.default_rng(int(rng.integers(2**31)))
        t0 = time.time()
        v5_score, v5_wkl, est_exp = eval_v5(
            grid_list, settlements_data, ground_truth, true_params,
            n_obs_per_seed=args.obs_per_seed, n_seeds=args.n_seeds,
            n_mc_params=args.mc_params, mc_runs_per_param=args.mc_runs,
            mc_weight=args.mc_weight, prior_weight=args.prior_weight,
            temperature=args.temperature, dirichlet_equiv=args.dirichlet_equiv,
            rng=obs_rng,
        )
        print(f"  V5: score={v5_score:.1f}  wkl={v5_wkl:.4f}  exp_est={est_exp:.3f} ({time.time()-t0:.1f}s)")
        all_v5.append(v5_score)

        if args.compare:
            # V1 baseline (MC only, no observations, flat floor)
            t0 = time.time()
            v1_pred = monte_carlo_predict(grid_list, settlements_data,
                                          n_runs=800, param_samples=100, seed=42)
            initial_grid = parse_initial_grid(grid_list)
            v1_pred = apply_static_overrides(v1_pred, initial_grid)
            v1_wkl = entropy_weighted_kl(ground_truth, v1_pred)
            v1_score = kl_to_score(v1_wkl)
            print(f"  V1: score={v1_score:.1f}  wkl={v1_wkl:.4f} ({time.time()-t0:.1f}s)")
            print(f"  Delta V5 vs V1: {v5_score - v1_score:+.1f}")
            all_v3.append(v1_score)

    print(f"\nV5 mean: {np.mean(all_v5):.2f}/100  (range {min(all_v5):.1f}–{max(all_v5):.1f})")
    if args.compare:
        print(f"V3 mean: {np.mean(all_v3):.2f}/100")
        print(f"V5 improvement: {np.mean(all_v5)-np.mean(all_v3):+.2f} pts")
    print(f"score: {np.mean(all_v5):.2f}")


if __name__ == "__main__":
    main()
