"""
Local evaluation for predict_v3 pipeline — all 5 seeds, pushing for 100.

Each map:
1. Simulate 5 independent seed observations (same params, different RNG)
2. ABC parameter fitting using all 5 seeds' observations
3. MC with fitted params → shared prior
4. Per-seed Bayesian correction (each seed gets its OWN observation nudge)
5. Score all 5 seeds separately, log to elias/logs/offline/

Usage:
    python3 evaluate_v3.py                           # 1 map, max settings
    python3 evaluate_v3.py --maps 3 --compare        # 3 maps vs v1
    python3 evaluate_v3.py --maps 1 --gt-runs 500 --mc-runs 1000  # high quality
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
from predict_v3 import (
    abc_fit_params,
    mc_with_fitted_params,
    bayesian_correct,
)
from dashboard_logger import log_offline_backtest


def simulate_observations(grid_list, settlements_data, true_params, n_seeds=5, n_sweeps=1, rng=None):
    """
    Simulate API observations: run true simulator n_sweeps times per seed.
    Returns:
        all_obs_single: {seed_idx: {(x,y): class}} — first sweep
        all_obs_multi:  {seed_idx: list[{(x,y): class}]} — all sweeps
    """
    if rng is None:
        rng = np.random.default_rng(0)
    H, W = len(grid_list), len(grid_list[0])
    all_obs_single = {}
    all_obs_multi = {}

    for seed_idx in range(n_seeds):
        sweeps = []
        for _ in range(n_sweeps):
            run_rng = np.random.default_rng(int(rng.integers(2**31)))
            final_grid = run_simulation(grid_list, settlements_data, true_params, run_rng)
            seed_obs = {}
            for y in range(H):
                for x in range(W):
                    seed_obs[(x, y)] = int(final_grid[y, x])
            sweeps.append(seed_obs)
        all_obs_single[seed_idx] = sweeps[0]
        all_obs_multi[seed_idx] = sweeps

    return all_obs_single, all_obs_multi


def make_per_seed_prediction(mc_prior, seed_obs, initial_grid, mc_equiv=50.0):
    """Apply per-seed Bayesian correction to the shared MC prior.
    seed_obs can be a single dict {(x,y): class} or a list of sweep dicts.
    """
    H, W = initial_grid.shape
    # Wrap in dict keyed by 0 for bayesian_correct (supports both single and multi-sweep)
    obs_input = {0: seed_obs}
    pred = bayesian_correct(mc_prior, obs_input, mc_equiv_samples=mc_equiv, H=H, W=W)
    pred[initial_grid == OCEAN, :] = 0.002
    pred[initial_grid == OCEAN, 0] = 0.99
    pred[initial_grid == MOUNTAIN, :] = 0.002
    pred[initial_grid == MOUNTAIN, 5] = 0.99
    pred = pred / pred.sum(axis=2, keepdims=True)
    return pred


def evaluate_v1(grid_list, settlements_data, ground_truth, initial_grid):
    """V1 baseline: blind MC over broad param ranges."""
    prediction = monte_carlo_predict(
        grid_list, settlements_data, n_runs=200, param_samples=15, seed=42,
    )
    prediction = apply_static_overrides(prediction, initial_grid)
    wkl = entropy_weighted_kl(ground_truth, prediction)
    return kl_to_score(wkl), wkl, prediction


def main():
    parser = argparse.ArgumentParser(description="Local evaluation — all 5 seeds")
    parser.add_argument("--maps", type=int, default=1)
    parser.add_argument("--n-seeds", type=int, default=5, help="Seeds per map (default: 5)")
    parser.add_argument("--n-sweeps", type=int, default=1, help="Sweeps per seed (default: 1, use 5 to simulate full budget)")
    parser.add_argument("--gt-runs", type=int, default=500)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--abc-stage1", type=int, default=500)
    parser.add_argument("--abc-stage2", type=int, default=250)
    parser.add_argument("--abc-mc", type=int, default=60)
    parser.add_argument("--abc-top-k", type=int, default=20)
    parser.add_argument("--mc-runs", type=int, default=1000)
    parser.add_argument("--mc-equiv", type=float, default=50.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    run_id = str(uuid.uuid4())[:8]
    all_v3_scores = []
    all_v1_scores = []

    for map_idx in range(args.maps):
        print(f"\n{'='*60}")
        print(f"Map {map_idx + 1}/{args.maps}")
        print(f"{'='*60}")

        map_rng = np.random.default_rng(int(rng.integers(2**31)))
        grid_list, settlements_data = generate_synthetic_map(map_rng)
        initial_grid = parse_initial_grid(grid_list)
        dynamic_mask = (initial_grid != OCEAN) & (initial_grid != MOUNTAIN)
        dynamic_cells = int(dynamic_mask.sum())

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
              f"conf={true_params.conflict_prob:.3f} win={true_params.winter_severity:.3f} "
              f"ruin={true_params.ruin_reclaim_rate:.3f}")

        # Ground truth (shared — same params for all seeds)
        print(f"  Computing ground truth ({args.gt_runs} runs)...")
        t0 = time.time()
        gt_rng = np.random.default_rng(int(rng.integers(2**31)))
        ground_truth = compute_ground_truth(
            grid_list, settlements_data, true_params, args.gt_runs, gt_rng
        )
        print(f"  Ground truth done in {time.time()-t0:.1f}s")

        # Simulate all seed observations (with multiple sweeps if requested)
        obs_rng = np.random.default_rng(int(rng.integers(2**31)))
        all_observations, all_obs_multi = simulate_observations(
            grid_list, settlements_data, true_params,
            n_seeds=args.n_seeds, n_sweeps=args.n_sweeps, rng=obs_rng,
        )
        print(f"  Simulated {args.n_seeds} seeds × {args.n_sweeps} sweeps = {args.n_seeds * args.n_sweeps} total observations")

        # ---- V3 pipeline ----
        print(f"\n  --- V3: ABC + per-seed predictions ---")

        # Step 1: ABC using ALL seeds' observations (all sweeps if multi-sweep)
        t0 = time.time()
        if args.n_sweeps > 1:
            abc_observations = {}
            obs_counter = 0
            for sweeps in all_obs_multi.values():
                for sweep_obs in sweeps:
                    abc_observations[obs_counter] = sweep_obs
                    obs_counter += 1
            print(f"  ABC fitting ({obs_counter} sweep obs, stage1={args.abc_stage1}, stage2={args.abc_stage2}, mc={args.abc_mc})...")
        else:
            abc_observations = all_observations
            print(f"  ABC fitting (stage1={args.abc_stage1}, stage2={args.abc_stage2}, mc={args.abc_mc} per candidate)...")

        fitted_params = abc_fit_params(
            grid_list, settlements_data, abc_observations,
            n_stage1=args.abc_stage1,
            n_stage2_refine=args.abc_stage2,
            stage2_mc=args.abc_mc,
            top_k=args.abc_top_k,
            seed=42,
        )
        best_p = fitted_params[0][0]
        print(f"  Best fitted: exp={best_p.expansion_rate:.3f} "
              f"conf={best_p.conflict_prob:.3f} win={best_p.winter_severity:.3f} "
              f"ruin={best_p.ruin_reclaim_rate:.3f}")

        # Step 2: Shared MC prior with fitted params
        print(f"  Running MC ({args.mc_runs} runs)...")
        mc_prior = mc_with_fitted_params(
            grid_list, settlements_data, fitted_params,
            total_runs=args.mc_runs, seed=123,
        )
        mc_prior = apply_static_overrides(mc_prior, initial_grid)
        abc_mc_elapsed = time.time() - t0
        print(f"  ABC + MC done in {abc_mc_elapsed:.1f}s")

        # Step 3: Per-seed predictions and scoring
        seed_scores = []
        seed_log_entries = {}
        print(f"\n  Per-seed scores:")

        # With multi-sweep, lower mc_equiv so real observations have more weight
        if args.n_sweeps > 1:
            n_sweeps_total = args.n_seeds * args.n_sweeps
            effective_mc_equiv = max(10.0, args.mc_equiv / (n_sweeps_total / 5))
        else:
            effective_mc_equiv = args.mc_equiv

        for seed_idx in range(args.n_seeds):
            # Use all sweeps for this seed (richer Bayesian update)
            seed_obs = all_obs_multi[seed_idx] if args.n_sweeps > 1 else all_observations[seed_idx]
            pred = make_per_seed_prediction(
                mc_prior, seed_obs, initial_grid, mc_equiv=effective_mc_equiv
            )
            wkl = entropy_weighted_kl(ground_truth, pred)
            score = kl_to_score(wkl)
            seed_scores.append(score)
            print(f"    Seed {seed_idx}: score={score:.1f}  wkl={wkl:.4f}")

            seed_log_entries[str(seed_idx)] = {
                "sim_score": round(score, 2),
                "prior_score": round(score, 2),
                "weighted_kl": round(wkl, 4),
                "scored_cells": dynamic_cells,
                "elapsed_s": round(abc_mc_elapsed / args.n_seeds, 1),
                "prediction": pred.tolist(),
                "ground_truth": ground_truth.tolist(),
            }

        round_score = float(np.mean(seed_scores))
        print(f"\n  V3 round score: {round_score:.2f}/100  "
              f"(range: {min(seed_scores):.1f} – {max(seed_scores):.1f})")
        all_v3_scores.append(round_score)

        # Log to dashboard
        bt_id = f"v3_{run_id}_map{map_idx+1}"
        log_offline_backtest(
            round_id=bt_id,
            round_number=map_idx + 1,
            round_score=round(round_score, 2),
            n_sims=args.mc_runs,
            seeds=seed_log_entries,
            config={
                "pipeline": "v3",
                "label": f"v3 map{map_idx+1} ({args.n_seeds} seeds)",
                "abc_stage1": args.abc_stage1,
                "abc_stage2": args.abc_stage2,
                "abc_mc": args.abc_mc,
                "mc_runs": args.mc_runs,
                "n_seeds": args.n_seeds,
                "true_params": {
                    "expansion_rate": round(true_params.expansion_rate, 3),
                    "conflict_prob": round(true_params.conflict_prob, 3),
                    "winter_severity": round(true_params.winter_severity, 3),
                },
            },
            label=bt_id,
        )

        # ---- V1 baseline ----
        if args.compare:
            print(f"\n  --- V1 baseline (blind MC) ---")
            t0 = time.time()
            v1_score, v1_wkl, v1_pred = evaluate_v1(
                grid_list, settlements_data, ground_truth, initial_grid
            )
            print(f"  V1: score={v1_score:.1f}/100  wkl={v1_wkl:.4f}  ({time.time()-t0:.1f}s)")
            all_v1_scores.append(v1_score)

            v1_seed_entries = {
                str(i): {
                    "sim_score": round(v1_score, 2),
                    "prior_score": round(v1_score, 2),
                    "weighted_kl": round(v1_wkl, 4),
                    "scored_cells": dynamic_cells,
                    "elapsed_s": round(time.time() - t0, 1),
                    "prediction": v1_pred.tolist(),
                    "ground_truth": ground_truth.tolist(),
                }
                for i in range(args.n_seeds)
            }
            log_offline_backtest(
                round_id=f"v1_{run_id}_map{map_idx+1}",
                round_number=map_idx + 1,
                round_score=round(v1_score, 2),
                n_sims=200,
                seeds=v1_seed_entries,
                config={
                    "pipeline": "v1",
                    "label": f"v1-blind map{map_idx+1}",
                    "wkl": round(v1_wkl, 4),
                },
                label=f"v1_{run_id}_map{map_idx+1}",
            )
            print(f"  Delta: +{round_score - v1_score:.1f} points")

    # ---- Summary ----
    print(f"\n{'='*60}")
    print(f"FINAL SUMMARY ({args.maps} maps × {args.n_seeds} seeds)")
    print(f"{'='*60}")
    print(f"V3 mean: {np.mean(all_v3_scores):.2f}/100")
    if args.compare:
        print(f"V1 mean: {np.mean(all_v1_scores):.2f}/100")
        print(f"Improvement: +{np.mean(all_v3_scores) - np.mean(all_v1_scores):.2f} pts")


if __name__ == "__main__":
    main()
