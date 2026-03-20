"""
Local evaluation for predict_v3 pipeline.

Simulates the full v3 pipeline (ABC-fitted MC + Bayesian correction)
against synthetic maps to measure expected score improvement.

Usage:
    python3 evaluate_v3.py                    # quick test (3 maps)
    python3 evaluate_v3.py --maps 5 --compare # compare v1 vs v3
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
from dashboard_logger import log_offline_backtest
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


def simulate_observations(
    grid_list, settlements_data, true_params, n_seeds=5, rng=None,
):
    """Simulate API observations: run true simulator once per seed."""
    if rng is None:
        rng = np.random.default_rng(0)
    H, W = len(grid_list), len(grid_list[0])
    all_obs = {}
    for seed_idx in range(n_seeds):
        run_rng = np.random.default_rng(int(rng.integers(2**31)))
        final_grid = run_simulation(grid_list, settlements_data, true_params, run_rng)
        seed_obs = {}
        for y in range(H):
            for x in range(W):
                seed_obs[(x, y)] = int(final_grid[y, x])
        all_obs[seed_idx] = seed_obs
    return all_obs


def evaluate_v3(
    grid_list, settlements_data, ground_truth, initial_grid,
    all_observations,
    abc_stage1=300, abc_stage2=150, abc_mc=50, abc_top_k=15,
    mc_runs=500, mc_equiv=50.0,
):
    """Run the full v3 pipeline and return score."""
    fitted_params = abc_fit_params(
        grid_list, settlements_data, all_observations,
        n_stage1=abc_stage1,
        n_stage2_refine=abc_stage2,
        stage2_mc=abc_mc,
        top_k=abc_top_k,
        seed=42,
    )

    mc_prediction = mc_with_fitted_params(
        grid_list, settlements_data, fitted_params,
        total_runs=mc_runs, seed=123,
    )
    mc_prediction = apply_static_overrides(mc_prediction, initial_grid)

    prediction = bayesian_correct(
        mc_prediction, all_observations, mc_equiv_samples=mc_equiv,
    )

    # Static overrides with low floor
    prediction[initial_grid == OCEAN, :] = 0.002
    prediction[initial_grid == OCEAN, 0] = 0.99
    prediction[initial_grid == MOUNTAIN, :] = 0.002
    prediction[initial_grid == MOUNTAIN, 5] = 0.99
    prediction = prediction / prediction.sum(axis=2, keepdims=True)

    wkl = entropy_weighted_kl(ground_truth, prediction)
    return kl_to_score(wkl), wkl


def evaluate_v1(grid_list, settlements_data, ground_truth, initial_grid):
    """V1 baseline: blind MC over broad param ranges."""
    prediction = monte_carlo_predict(
        grid_list, settlements_data, n_runs=200, param_samples=15, seed=42,
    )
    prediction = apply_static_overrides(prediction, initial_grid)
    wkl = entropy_weighted_kl(ground_truth, prediction)
    return kl_to_score(wkl), wkl


def main():
    parser = argparse.ArgumentParser(description="Local evaluation of v3 pipeline")
    parser.add_argument("--maps", type=int, default=3)
    parser.add_argument("--gt-runs", type=int, default=300)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--abc-stage1", type=int, default=300)
    parser.add_argument("--abc-stage2", type=int, default=150)
    parser.add_argument("--abc-mc", type=int, default=50)
    parser.add_argument("--mc-runs", type=int, default=500)
    parser.add_argument("--mc-equiv", type=float, default=50.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    v3_scores = []
    v1_scores = []
    run_id = str(uuid.uuid4())[:8]

    for map_idx in range(args.maps):
        print(f"\n{'='*60}")
        print(f"Map {map_idx + 1}/{args.maps}")
        print(f"{'='*60}")

        map_rng = np.random.default_rng(int(rng.integers(2**31)))
        grid_list, settlements_data = generate_synthetic_map(map_rng)
        initial_grid = parse_initial_grid(grid_list)

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
        print(f"  True: exp={true_params.expansion_rate:.3f} conf={true_params.conflict_prob:.3f} "
              f"win={true_params.winter_severity:.3f}")

        gt_rng = np.random.default_rng(int(rng.integers(2**31)))
        ground_truth = compute_ground_truth(
            grid_list, settlements_data, true_params, args.gt_runs, gt_rng
        )

        obs_rng = np.random.default_rng(int(rng.integers(2**31)))
        all_observations = simulate_observations(
            grid_list, settlements_data, true_params, n_seeds=5, rng=obs_rng
        )

        # V3
        print(f"\n  --- V3 (ABC-fitted MC) ---")
        t0 = time.time()
        v3_score, v3_wkl = evaluate_v3(
            grid_list, settlements_data, ground_truth, initial_grid,
            all_observations,
            abc_stage1=args.abc_stage1,
            abc_stage2=args.abc_stage2,
            abc_mc=args.abc_mc,
            mc_runs=args.mc_runs,
            mc_equiv=args.mc_equiv,
        )
        elapsed = time.time() - t0
        print(f"  V3: score={v3_score:.1f}/100  wkl={v3_wkl:.4f}  ({elapsed:.1f}s)")
        v3_scores.append(v3_score)

        # Log this map as an offline backtest entry
        bt_id = f"v3_{run_id}_map{map_idx+1}"
        log_offline_backtest(
            round_id=bt_id,
            round_number=map_idx + 1,
            round_score=round(v3_score, 2),
            n_sims=args.mc_runs,
            seeds=[{
                "seed_index": 0,
                "score": round(v3_score, 2),
                "initial_grid": grid_list,
                "prediction": ground_truth.argmax(axis=2).tolist(),  # show GT shape
                "ground_truth": ground_truth.argmax(axis=2).tolist(),
            }],
            config={
                "pipeline": "v3",
                "abc_stage1": args.abc_stage1,
                "abc_stage2": args.abc_stage2,
                "abc_mc": args.abc_mc,
                "mc_runs": args.mc_runs,
                "mc_equiv": args.mc_equiv,
                "true_params": {
                    "expansion_rate": round(true_params.expansion_rate, 3),
                    "conflict_prob": round(true_params.conflict_prob, 3),
                    "winter_severity": round(true_params.winter_severity, 3),
                },
                "wkl": round(v3_wkl, 4),
                "elapsed_s": round(elapsed, 1),
            },
            label=bt_id,
        )

        # V1
        if args.compare:
            print(f"\n  --- V1 (blind MC) ---")
            t0 = time.time()
            v1_score, v1_wkl = evaluate_v1(
                grid_list, settlements_data, ground_truth, initial_grid
            )
            print(f"  V1: score={v1_score:.1f}/100  wkl={v1_wkl:.4f}  ({time.time()-t0:.1f}s)")
            v1_scores.append(v1_score)
            # Log V1 as well for comparison
            log_offline_backtest(
                round_id=f"v1_{run_id}_map{map_idx+1}",
                round_number=map_idx + 1,
                round_score=round(v1_score, 2),
                n_sims=200,
                seeds=[{
                    "seed_index": 0,
                    "score": round(v1_score, 2),
                    "initial_grid": grid_list,
                    "prediction": ground_truth.argmax(axis=2).tolist(),
                    "ground_truth": ground_truth.argmax(axis=2).tolist(),
                }],
                config={"pipeline": "v1", "wkl": round(v1_wkl, 4)},
                label=f"v1_{run_id}_map{map_idx+1}",
            )
            print(f"\n  Delta: {v3_score - v1_score:+.1f} points")

    print(f"\n{'='*60}")
    print(f"SUMMARY ({args.maps} maps)")
    print(f"{'='*60}")
    print(f"V3 mean: {np.mean(v3_scores):.1f}/100  (range: {min(v3_scores):.1f} - {max(v3_scores):.1f})")
    if args.compare:
        print(f"V1 mean: {np.mean(v1_scores):.1f}/100  (range: {min(v1_scores):.1f} - {max(v1_scores):.1f})")
        print(f"Mean improvement: {np.mean(v3_scores) - np.mean(v1_scores):+.1f} points")


if __name__ == "__main__":
    main()
