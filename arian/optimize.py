"""
Overnight optimizer for the Astar Island predictor.

Runs a random search over:
  1. SimParams ranges used during Monte Carlo sampling
  2. Aggregation settings (n_runs, temperature scaling)

Uses all available CPU cores via multiprocessing.
Logs results to results.jsonl — one JSON line per trial.
Saves best config to best_config.json continuously.

Usage:
    python optimize.py                    # run forever, all cores
    python optimize.py --trials 200       # stop after 200 trials
    python optimize.py --workers 4        # use 4 cores
    python optimize.py --eval-maps 3      # evaluate on 3 synthetic maps per trial

No API key needed. No git commits. Pure compute.
"""
import argparse
import json
import os
import time
import numpy as np
from multiprocessing import Pool, cpu_count
from dataclasses import dataclass, asdict

from evaluate import evaluate


# ---------------------------------------------------------------------------
# Search space — ranges for the ranges used in monte_carlo_predict
# ---------------------------------------------------------------------------

# For each SimParams field, we search over the LOW and HIGH bounds of the
# sampling range. The optimizer finds which range [lo, hi] gives the best
# predictions when sampling uniformly within that range.
#
# Format: (absolute_min, absolute_max) — the optimizer picks lo and hi within this.
SEARCH_SPACE = {
    "expansion_rate":      (0.01, 0.95),
    "conflict_prob":       (0.01, 0.80),
    "winter_severity":     (0.05, 0.90),
    "trade_range":         (2,    20),
    "ruin_reclaim_rate":   (0.01, 0.90),
    "forest_reclaim_rate": (0.01, 0.50),
    "longship_prob":       (0.01, 0.70),
    "longship_range":      (2,    20),
}

# Aggregation search
PRED_RUNS_OPTIONS = [50, 100, 150, 200]
PARAM_SAMPLES_OPTIONS = [5, 10, 15, 20]
TEMPERATURE_OPTIONS = [0.5, 0.75, 1.0, 1.25, 1.5]  # 1.0 = no change


@dataclass
class Config:
    """One trial configuration."""
    param_ranges: dict        # {field: (lo, hi)} — ranges to sample SimParams from
    n_runs: int
    param_samples: int
    temperature: float        # applied as probs = probs**T / sum, T<1 sharpens


def sample_config(rng: np.random.Generator) -> Config:
    """Sample a random configuration from the search space."""
    param_ranges = {}
    for key, (abs_min, abs_max) in SEARCH_SPACE.items():
        # Pick two random points, use as [lo, hi]
        a = rng.uniform(abs_min, abs_max)
        b = rng.uniform(abs_min, abs_max)
        lo, hi = min(a, b), max(a, b)
        # Ensure minimum width so we're not just point-sampling
        if hi - lo < (abs_max - abs_min) * 0.05:
            hi = min(abs_max, lo + (abs_max - abs_min) * 0.05)
        param_ranges[key] = (float(lo), float(hi))

    return Config(
        param_ranges=param_ranges,
        n_runs=int(rng.choice(PRED_RUNS_OPTIONS)),
        param_samples=int(rng.choice(PARAM_SAMPLES_OPTIONS)),
        temperature=float(rng.choice(TEMPERATURE_OPTIONS)),
    )


def mutate_config(config: Config, rng: np.random.Generator, strength: float = 0.3) -> Config:
    """
    Mutate an existing good config slightly — exploitation around best known configs.
    strength: fraction of search space width to perturb by.
    """
    new_ranges = {}
    for key, (lo, hi) in config.param_ranges.items():
        abs_min, abs_max = SEARCH_SPACE[key]
        width = abs_max - abs_min

        # Perturb lo and hi independently
        new_lo = np.clip(lo + rng.normal(0, strength * width), abs_min, abs_max)
        new_hi = np.clip(hi + rng.normal(0, strength * width), abs_min, abs_max)
        lo2, hi2 = min(new_lo, new_hi), max(new_lo, new_hi)
        if hi2 - lo2 < width * 0.02:
            hi2 = min(abs_max, lo2 + width * 0.05)
        new_ranges[key] = (float(lo2), float(hi2))

    return Config(
        param_ranges=new_ranges,
        n_runs=config.n_runs if rng.random() > 0.2 else int(rng.choice(PRED_RUNS_OPTIONS)),
        param_samples=config.param_samples if rng.random() > 0.2 else int(rng.choice(PARAM_SAMPLES_OPTIONS)),
        temperature=config.temperature if rng.random() > 0.2 else float(rng.choice(TEMPERATURE_OPTIONS)),
    )


# ---------------------------------------------------------------------------
# Evaluation worker (runs in subprocess)
# ---------------------------------------------------------------------------

def eval_worker(args: tuple) -> dict:
    """
    Evaluate one config. Runs in a separate process.
    Returns a result dict with score and config.
    """
    config_dict, n_maps, gt_runs, worker_seed = args

    # Reconstruct config
    config = Config(**config_dict)

    # Temporarily patch monte_carlo_predict's param_ranges and aggregation
    import simulator as sim_module

    original_predict = sim_module.monte_carlo_predict

    def patched_predict(grid_list, settlements_data, n_runs=None, param_samples=None, seed=0):
        from scipy.stats import qmc
        import numpy as np

        H = len(grid_list)
        W = len(grid_list[0])
        counts = np.zeros((H, W, 6), dtype=np.float32)

        rng = np.random.default_rng(seed)
        _n_runs = config.n_runs
        _param_samples = config.param_samples
        runs_per_param = max(1, _n_runs // _param_samples)

        # Use config's param_ranges instead of hardcoded ones
        keys = list(config.param_ranges.keys())
        sampler = qmc.LatinHypercube(d=len(config.param_ranges), seed=int(rng.integers(2**31)))
        lhs_samples = sampler.random(n=_param_samples)

        from simulator import SimParams, run_simulation
        for i in range(_param_samples):
            param_vals = {}
            for j, key in enumerate(keys):
                lo, hi = config.param_ranges[key]
                val = lo + lhs_samples[i, j] * (hi - lo)
                param_vals[key] = int(round(val)) if key in ("trade_range", "longship_range") else float(val)

            params = SimParams(**param_vals)
            for _ in range(runs_per_param):
                run_rng = np.random.default_rng(int(rng.integers(2**31)))
                result = run_simulation(grid_list, settlements_data, params, run_rng)
                for cls in range(6):
                    counts[:, :, cls] += (result == cls).astype(np.float32)

        total = counts.sum(axis=2, keepdims=True)
        total = np.maximum(total, 1.0)
        probs = counts / total

        # Apply temperature scaling
        if config.temperature != 1.0:
            probs = np.power(np.maximum(probs, 1e-10), 1.0 / config.temperature)
            probs = probs / probs.sum(axis=2, keepdims=True)

        # 0.01 floor
        probs = np.maximum(probs, 0.01)
        probs = probs / probs.sum(axis=2, keepdims=True)
        return probs

    # Monkey-patch for this process
    sim_module.monte_carlo_predict = patched_predict

    try:
        score = evaluate(
            n_maps=n_maps,
            n_gt_runs=gt_runs,
            n_pred_runs=config.n_runs,
            param_samples=config.param_samples,
            master_seed=worker_seed,
        )
    except Exception as e:
        score = 0.0
        print(f"  [worker error] {e}")
    finally:
        sim_module.monte_carlo_predict = original_predict

    return {
        "score": score,
        "config": {
            "param_ranges": config.param_ranges,
            "n_runs": config.n_runs,
            "param_samples": config.param_samples,
            "temperature": config.temperature,
        },
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Main optimizer loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Overnight optimizer — no API key needed")
    parser.add_argument("--trials", type=int, default=0, help="Max trials (0 = run forever)")
    parser.add_argument("--workers", type=int, default=0, help="CPU workers (0 = all cores)")
    parser.add_argument("--eval-maps", type=int, default=3, help="Maps per trial (default: 3)")
    parser.add_argument("--gt-runs", type=int, default=50, help="Ground truth runs per map (default: 50)")
    parser.add_argument("--results-file", default="results.jsonl", help="Output log file")
    parser.add_argument("--best-file", default="best_config.json", help="Best config output")
    parser.add_argument("--seed", type=int, default=0, help="Master RNG seed")
    args = parser.parse_args()

    n_workers = args.workers if args.workers > 0 else cpu_count()
    print(f"Optimizer started — {n_workers} workers, eval: {args.eval_maps} maps × {args.gt_runs} GT runs")
    print(f"Results → {args.results_file}  |  Best → {args.best_file}")
    print(f"Press Ctrl+C to stop.\n")

    rng = np.random.default_rng(args.seed)
    best_score = 0.0
    best_config = None
    trial = 0
    top_configs = []  # keep best 5 for mutation

    # Load previous results if resuming
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
        top_configs = top_configs[:5]
        print(f"Resumed from {args.results_file}: best so far = {best_score:.2f}")

    results_f = open(args.results_file, "a")

    try:
        while args.trials == 0 or trial < args.trials:
            # Generate a batch of configs to evaluate in parallel
            batch_size = n_workers
            configs = []

            for _ in range(batch_size):
                # 70% random, 30% mutate from top configs
                if top_configs and rng.random() < 0.30:
                    parent = top_configs[rng.integers(len(top_configs))]
                    parent_cfg = Config(
                        param_ranges=parent["config"]["param_ranges"],
                        n_runs=parent["config"]["n_runs"],
                        param_samples=parent["config"]["param_samples"],
                        temperature=parent["config"]["temperature"],
                    )
                    cfg = mutate_config(parent_cfg, rng)
                else:
                    cfg = sample_config(rng)
                configs.append(cfg)

            # Run batch in parallel
            worker_args = [
                (
                    {
                        "param_ranges": c.param_ranges,
                        "n_runs": c.n_runs,
                        "param_samples": c.param_samples,
                        "temperature": c.temperature,
                    },
                    args.eval_maps,
                    args.gt_runs,
                    int(rng.integers(2**31)),
                )
                for c in configs
            ]

            t0 = time.time()
            with Pool(n_workers) as pool:
                results = pool.map(eval_worker, worker_args)
            elapsed = time.time() - t0

            for result in results:
                trial += 1
                score = result["score"]

                # Log to file
                results_f.write(json.dumps(result) + "\n")
                results_f.flush()

                # Track best
                if score > best_score:
                    best_score = score
                    best_config = result["config"]
                    with open(args.best_file, "w") as f:
                        json.dump({"score": best_score, "config": best_config}, f, indent=2)
                    print(f"  *** NEW BEST: {score:.2f} (trial {trial}) ***")

                # Update top configs
                top_configs.append(result)
                top_configs.sort(key=lambda x: x["score"], reverse=True)
                top_configs = top_configs[:5]

                print(f"  Trial {trial:4d} | score={score:.2f} | best={best_score:.2f} | {elapsed/batch_size:.1f}s/trial")

            if args.trials > 0 and trial >= args.trials:
                break

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        results_f.close()

    print(f"\nBest score: {best_score:.2f}")
    if best_config:
        print(f"Best config saved to {args.best_file}")
        print(json.dumps(best_config, indent=2))


if __name__ == "__main__":
    main()
