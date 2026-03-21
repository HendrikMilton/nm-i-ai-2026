"""
V3 hyperparameter optimizer — searches for best ABC + MC budget settings.

Unlike optimize.py (which tuned MC param ranges), this optimizer treats the
simulator params as a black box and instead finds the best budget allocation:
  - How many ABC stage-1 candidates?
  - How many stage-2 refinements?
  - How many MC runs per stage-2 candidate?
  - How many top-K params to keep?
  - How many final MC runs?
  - What mc_equiv weight for Bayesian correction?

Uses multiprocessing for parallel trial evaluation.
Logs results to results_v3.jsonl, best config to best_config_v3.json.

Usage:
    python optimize_v3.py                         # run forever, all cores
    python optimize_v3.py --trials 100
    python optimize_v3.py --workers 8 --eval-maps 3
"""
import argparse
import json
import os
import time
import numpy as np
from multiprocessing import Pool, cpu_count


# ---------------------------------------------------------------------------
# Search space over v3 hyperparams
# ---------------------------------------------------------------------------

SEARCH_SPACE = {
    "abc_stage1":  (200,  1500),    # Stage 1 candidate count
    "abc_stage2":  (50,   400),     # Stage 2 refinement count
    "abc_mc":      (10,   60),      # MC runs per stage-2 candidate (capped for GCP speed)
    "abc_top_k":   (5,    25),      # Top K params to keep
    "mc_runs":     (200,  2000),    # Final MC runs
    "mc_equiv":    (5.0,  150.0),   # Bayesian correction weight
}

INT_KEYS = {"abc_stage1", "abc_stage2", "abc_mc", "abc_top_k", "mc_runs"}


def sample_config(rng: np.random.Generator) -> dict:
    config = {}
    for key, (lo, hi) in SEARCH_SPACE.items():
        val = rng.uniform(lo, hi)
        config[key] = int(round(val)) if key in INT_KEYS else float(val)
    return config


def mutate_config(config: dict, rng: np.random.Generator, strength: float = 0.25) -> dict:
    new_config = {}
    for key, (lo, hi) in SEARCH_SPACE.items():
        current = config[key]
        noise = rng.normal(0, strength * (hi - lo))
        new_val = float(np.clip(current + noise, lo, hi))
        new_config[key] = int(round(new_val)) if key in INT_KEYS else new_val
    return new_config


# ---------------------------------------------------------------------------
# Evaluation worker
# ---------------------------------------------------------------------------

def evaluate_config(config: dict, n_maps: int, gt_runs: int, worker_seed: int, n_workers: int = None) -> dict:
    """
    Evaluate one v3 hyperparameter config on n_maps synthetic maps.
    Runs ABC with full parallelism — call from main process only (not inside a Pool).
    """
    from simulator import SimParams, run_simulation, parse_initial_grid, apply_static_overrides, OCEAN, MOUNTAIN
    from evaluate import generate_synthetic_map, compute_ground_truth, entropy_weighted_kl, kl_to_score
    from predict_v3 import abc_fit_params, mc_with_fitted_params, bayesian_correct

    rng = np.random.default_rng(worker_seed)
    scores = []

    for map_i in range(n_maps):
        try:
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

            gt_rng = np.random.default_rng(int(rng.integers(2**31)))
            ground_truth = compute_ground_truth(grid_list, settlements_data, true_params, gt_runs, gt_rng)

            all_observations = {}
            H, W = len(grid_list), len(grid_list[0])
            for seed_idx in range(5):
                obs_rng = np.random.default_rng(int(rng.integers(2**31)))
                final_grid = run_simulation(grid_list, settlements_data, true_params, obs_rng)
                all_observations[seed_idx] = {(x, y): int(final_grid[y, x]) for y in range(H) for x in range(W)}

            # Run v3 pipeline with full parallelism on ABC
            fitted_params = abc_fit_params(
                grid_list, settlements_data, all_observations,
                n_stage1=config["abc_stage1"],
                n_stage2_refine=config["abc_stage2"],
                stage2_mc=config["abc_mc"],
                top_k=config["abc_top_k"],
                seed=int(rng.integers(2**31)),
                n_workers=n_workers,
            )

            mc_prior = mc_with_fitted_params(
                grid_list, settlements_data, fitted_params,
                total_runs=config["mc_runs"],
                seed=int(rng.integers(2**31)),
                n_workers=n_workers,
            )
            mc_prior = apply_static_overrides(mc_prior, initial_grid)

            seed_scores = []
            for seed_idx in range(5):
                obs_input = {0: all_observations[seed_idx]}
                pred = bayesian_correct(mc_prior, obs_input,
                                        mc_equiv_samples=config["mc_equiv"], H=H, W=W)
                pred[initial_grid == OCEAN, :] = 0.002
                pred[initial_grid == OCEAN, 0] = 0.99
                pred[initial_grid == MOUNTAIN, :] = 0.002
                pred[initial_grid == MOUNTAIN, 5] = 0.99
                pred = pred / pred.sum(axis=2, keepdims=True)
                wkl = entropy_weighted_kl(ground_truth, pred)
                seed_scores.append(kl_to_score(wkl))

            map_score = float(np.mean(seed_scores))
            scores.append(map_score)
            print(f"    map {map_i+1}/{n_maps}: score={map_score:.2f}")

        except Exception as e:
            import traceback
            print(f"  [eval error] {e}")
            traceback.print_exc()
            scores.append(0.0)

    return {
        "score": float(np.mean(scores)) if scores else 0.0,
        "config": config,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Main optimizer loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="V3 hyperparameter optimizer")
    parser.add_argument("--trials", type=int, default=0, help="Max trials (0 = run forever)")
    parser.add_argument("--workers", type=int, default=0, help="ABC workers per trial (0 = all cores)")
    parser.add_argument("--eval-maps", type=int, default=2, help="Maps per trial (default: 2)")
    parser.add_argument("--gt-runs", type=int, default=100, help="Ground truth runs per map (default: 100)")
    parser.add_argument("--results-file", default="results_v3.jsonl")
    parser.add_argument("--best-file", default="best_config_v3.json")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    # Sequential trials with parallel ABC — avoids nested Pool issues, same throughput
    n_abc_workers = args.workers if args.workers > 0 else cpu_count()
    print(f"V3 optimizer — sequential trials, {n_abc_workers} ABC workers each, "
          f"{args.eval_maps} maps × {args.gt_runs} GT runs/map")
    print(f"Results → {args.results_file}  |  Best → {args.best_file}")
    print(f"Search space: {list(SEARCH_SPACE.keys())}\n")

    rng = np.random.default_rng(args.seed)
    best_score = 0.0
    best_config = None
    trial = 0
    top_configs = []

    if os.path.exists(args.results_file):
        with open(args.results_file) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r["score"] > best_score:
                        best_score = r["score"]
                        best_config = r["config"]
                    top_configs.append(r)
                except Exception:
                    pass
        top_configs.sort(key=lambda x: x["score"], reverse=True)
        top_configs = top_configs[:10]
        print(f"Resumed: {len(top_configs)} results, best so far = {best_score:.2f}")

    results_f = open(args.results_file, "a")

    try:
        while args.trials == 0 or trial < args.trials:
            trial += 1

            if top_configs and rng.random() < 0.35:
                parent = top_configs[rng.integers(min(5, len(top_configs)))]["config"]
                cfg = mutate_config(parent, rng)
            else:
                cfg = sample_config(rng)

            print(f"\nTrial {trial}: stage1={cfg['abc_stage1']} stage2={cfg['abc_stage2']} "
                  f"mc={cfg['abc_mc']} top_k={cfg['abc_top_k']} "
                  f"mc_runs={cfg['mc_runs']} mc_equiv={cfg['mc_equiv']:.1f}")

            t0 = time.time()
            result = evaluate_config(cfg, args.eval_maps, args.gt_runs,
                                     int(rng.integers(2**31)), n_workers=n_abc_workers)
            elapsed = time.time() - t0

            score = result["score"]
            results_f.write(json.dumps(result) + "\n")
            results_f.flush()

            if score > best_score:
                best_score = score
                best_config = result["config"]
                with open(args.best_file, "w") as f:
                    json.dump({"score": best_score, "config": best_config}, f, indent=2)
                print(f"  *** NEW BEST: {score:.2f} ***")

            top_configs.append(result)
            top_configs.sort(key=lambda x: x["score"], reverse=True)
            top_configs = top_configs[:10]

            print(f"  → score={score:.2f} | best={best_score:.2f} | {elapsed:.1f}s")

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        results_f.close()

    print(f"\nBest score: {best_score:.2f}")
    if best_config:
        print(json.dumps(best_config, indent=2))


if __name__ == "__main__":
    main()
