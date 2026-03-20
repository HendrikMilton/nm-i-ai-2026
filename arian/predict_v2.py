"""
Astar Island v2 prediction pipeline.

Key improvements over v1:
- Uses ALL 50 observation queries (9 viewports × 5 seeds = 45 + 5 spare)
- Per-seed predictions: each seed has a DIFFERENT initial grid (mountains, oceans differ!)
- Bayesian update: observations update a weak MC prior (Dirichlet-Multinomial)
- GCP-optimized param_ranges from overnight search
- Static cell hard-override uses each seed's OWN initial grid

Strategy:
1. For each seed: run MC with optimized params → weak prior
2. Observe full map per seed (9 viewports each = 45 queries total)
3. Bayesian update: posterior ∝ Dirichlet(α_prior + obs_counts)
4. Hard-override static cells (ocean/mountain) from that seed's initial grid
5. Submit per-seed predictions

Usage:
    AINM_TOKEN=<token> python predict_v2.py [--round-id <uuid>] [--dry-run]
    AINM_TOKEN=<token> python predict_v2.py --from-cache observations.json
"""
import argparse
import json
import time
import numpy as np

from api_client import (
    get_round, get_active_round, get_budget,
    simulate_viewport, submit_prediction,
)
from simulator import (
    parse_initial_grid, monte_carlo_predict, apply_static_overrides,
    API_TO_CLASS, OCEAN, MOUNTAIN,
)
from dashboard_logger import log_action, log_query, log_submission, log_prediction


# 9 viewports that tile the 40x40 map with 15x15 windows
VIEWPORTS = [
    (0,  0,  15, 15),
    (13, 0,  15, 15),
    (25, 0,  15, 15),
    (0,  13, 15, 15),
    (13, 13, 15, 15),
    (25, 13, 15, 15),
    (0,  25, 15, 15),
    (13, 25, 15, 15),
    (25, 25, 15, 15),
]

# GCP-optimized param_ranges from overnight search (score 85.2 local)
OPTIMIZED_PARAM_RANGES = {
    "expansion_rate":      (0.175, 0.872),
    "conflict_prob":       (0.379, 0.528),
    "winter_severity":     (0.177, 0.220),
    "trade_range":         (2, 6),
    "ruin_reclaim_rate":   (0.583, 0.869),
    "forest_reclaim_rate": (0.377, 0.500),
    "longship_prob":       (0.551, 0.666),
    "longship_range":      (17, 17),
}


def observe_all_seeds(round_id: str, n_seeds: int = 5) -> dict:
    """
    Observe full map for all seeds using 9 viewports each.
    Returns {seed_index: [(x, y, obs_class), ...]} with ~1600 cells per seed.
    """
    all_observations = {}
    queries_used = 0

    for seed_index in range(n_seeds):
        print(f"  Observing seed {seed_index}...")
        seed_obs = []

        for (vx, vy, vw, vh) in VIEWPORTS:
            try:
                result = simulate_viewport(round_id, seed_index, vx, vy, vw, vh)
                queries_used += 1
                obs_grid = result["grid"]
                vp = result["viewport"]
                ax, ay = vp["x"], vp["y"]

                for row_i, row in enumerate(obs_grid):
                    for col_i, api_val in enumerate(row):
                        cx = ax + col_i
                        cy = ay + row_i
                        if 0 <= cx < 40 and 0 <= cy < 40:
                            obs_class = API_TO_CLASS.get(api_val, 0)
                            seed_obs.append((cx, cy, obs_class))

                remaining = result.get("queries_max", 50) - result.get("queries_used", queries_used)
                print(f"    VP ({vx:2d},{vy:2d}) | queries: {result.get('queries_used','?')}/{result.get('queries_max','?')}")

                # Log query for dashboard
                log_query(round_id, seed_index,
                          {"x": ax, "y": ay, "w": vw, "h": vh},
                          obs_grid, remaining)

                time.sleep(0.22)  # rate limit: 5 req/sec

            except Exception as e:
                print(f"    VP ({vx},{vy}) FAILED: {e}")
                log_action(round_id, "simulate_error", {"seed": seed_index, "vx": vx, "vy": vy, "error": str(e)})

        all_observations[seed_index] = seed_obs
        print(f"    Seed {seed_index}: {len(seed_obs)} cells observed")

    print(f"  Total queries used: {queries_used}")
    return all_observations



def bayesian_update(
    mc_prior: np.ndarray,
    obs_counts: np.ndarray,
    prior_strength: float = 2.0,
) -> np.ndarray:
    """
    Bayesian update using Dirichlet-Multinomial model.

    mc_prior: (H, W, 6) — MC simulation probabilities (our weak prior)
    obs_counts: (H, W, 6) — observation counts from real simulator
    prior_strength: how many pseudo-observations the MC prior is worth.
        Low = observations dominate. High = MC dominates.
        Given our MC scored 33.6 (bad), use low value (1-3).

    Returns (H, W, 6) posterior probabilities.
    """
    # Convert MC prior to Dirichlet pseudo-counts
    alpha_prior = mc_prior * prior_strength

    # Posterior = prior counts + observation counts
    alpha_posterior = alpha_prior + obs_counts

    # Normalize to probabilities
    posterior = alpha_posterior / alpha_posterior.sum(axis=2, keepdims=True)

    # Safety floor: prevent zero probabilities (KL blowup)
    posterior = np.maximum(posterior, 0.01)
    posterior = posterior / posterior.sum(axis=2, keepdims=True)

    return posterior


def predict_seed_with_observations(
    initial_state: dict,
    seed_observations: list,
    n_mc_runs: int = 200,
    param_samples: int = 15,
    prior_strength: float = 2.0,
    use_optimized_params: bool = True,
    seed: int = 0,
) -> np.ndarray:
    """
    Build prediction for ONE seed using MC prior + observation Bayesian update.

    IMPORTANT: Each seed may have a different initial grid (different mountains, etc.)
    so we MUST use per-seed initial states. Cross-seed observation aggregation is only
    safe for non-static cells.

    Returns (H, W, 6) prediction.
    """
    grid_list = initial_state["grid"]
    settlements_data = initial_state["settlements"]
    initial_grid = parse_initial_grid(grid_list)
    H, W = initial_grid.shape

    # Step 1: MC prior with optimized params
    if use_optimized_params:
        probs = _mc_with_optimized_params(
            grid_list, settlements_data,
            n_runs=n_mc_runs, param_samples=param_samples,
            seed=seed,
        )
    else:
        probs = monte_carlo_predict(
            grid_list, settlements_data,
            n_runs=n_mc_runs, param_samples=param_samples,
            seed=seed,
        )

    probs = apply_static_overrides(probs, initial_grid)

    # Step 2: Build observation counts for this seed
    obs_counts = np.zeros((H, W, 6), dtype=np.float32)
    for (x, y, obs_class) in seed_observations:
        if 0 <= obs_class <= 5 and 0 <= y < H and 0 <= x < W:
            obs_counts[y, x, obs_class] += 1

    total_obs = obs_counts.sum()
    cells_observed = (obs_counts.sum(axis=2) > 0).sum()

    # Step 3: Bayesian update
    posterior = bayesian_update(probs, obs_counts, prior_strength=prior_strength)

    # Step 4: Hard override for static cells from THIS seed's initial grid
    ocean_mask = (initial_grid == OCEAN)
    mountain_mask = (initial_grid == MOUNTAIN)
    posterior[ocean_mask, :] = 0.01
    posterior[ocean_mask, 0] = 0.95
    posterior[mountain_mask, :] = 0.01
    posterior[mountain_mask, 5] = 0.95
    posterior = posterior / posterior.sum(axis=2, keepdims=True)

    return posterior


def _mc_with_optimized_params(
    grid_list, settlements_data, n_runs=200, param_samples=15, seed=42,
):
    """Run MC with GCP-optimized param ranges."""
    from scipy.stats import qmc
    from simulator import SimParams, run_simulation

    H = len(grid_list)
    W = len(grid_list[0])
    counts = np.zeros((H, W, 6), dtype=np.float32)

    rng = np.random.default_rng(seed)
    runs_per_param = max(1, n_runs // param_samples)

    keys = list(OPTIMIZED_PARAM_RANGES.keys())
    sampler = qmc.LatinHypercube(d=len(keys), seed=int(rng.integers(2**31)))
    lhs_samples = sampler.random(n=param_samples)

    for i in range(param_samples):
        param_vals = {}
        for j, key in enumerate(keys):
            lo, hi = OPTIMIZED_PARAM_RANGES[key]
            val = lo + lhs_samples[i, j] * (hi - lo)
            param_vals[key] = int(round(val)) if key in ("trade_range", "longship_range") else float(val)

        params = SimParams(**param_vals)
        for _ in range(runs_per_param):
            run_rng = np.random.default_rng(int(rng.integers(2**31)))
            result = run_simulation(grid_list, settlements_data, params, run_rng)
            for cls in range(6):
                counts[:, :, cls] += (result == cls).astype(np.float32)

    total = np.maximum(counts.sum(axis=2, keepdims=True), 1.0)
    probs = counts / total
    probs = np.maximum(probs, 0.01)
    probs = probs / probs.sum(axis=2, keepdims=True)
    return probs


def main():
    parser = argparse.ArgumentParser(description="Astar Island v2 predictor")
    parser.add_argument("--round-id", help="Round UUID (auto-detects active)")
    parser.add_argument("--dry-run", action="store_true", help="Don't submit")
    parser.add_argument("--from-cache", help="Load observations from JSON file instead of querying")
    parser.add_argument("--save-cache", help="Save observations to JSON file")
    parser.add_argument("--mc-runs", type=int, default=200, help="MC runs (default: 200)")
    parser.add_argument("--param-samples", type=int, default=15, help="LHS param samples (default: 15)")
    parser.add_argument("--prior-strength", type=float, default=2.0,
                        help="MC prior strength in Bayesian update (default: 2.0, lower = trust observations more)")
    parser.add_argument("--no-optimized-params", action="store_true",
                        help="Use default param ranges instead of GCP-optimized")
    args = parser.parse_args()

    # Resolve round
    if args.round_id:
        round_data = get_round(args.round_id)
    else:
        active = get_active_round()
        if active is None:
            print("No active round. Pass --round-id explicitly.")
            return
        round_data = get_round(active["id"])

    round_id = round_data["id"]
    n_seeds = round_data.get("seeds_count", len(round_data["initial_states"]))
    map_w = round_data.get("map_width", 40)
    map_h = round_data.get("map_height", 40)

    print(f"Round {round_data['round_number']} ({round_id})")
    print(f"Map: {map_w}×{map_h}, {n_seeds} seeds")
    print()

    log_action(round_id, "start_pipeline", {
        "round_number": round_data.get("round_number"),
        "map_size": f"{map_w}x{map_h}",
        "n_seeds": n_seeds,
        "mc_runs": args.mc_runs,
        "param_samples": args.param_samples,
        "prior_strength": args.prior_strength,
        "from_cache": args.from_cache,
    }, map_w, map_h)

    # Get observations: from cache or live queries
    if args.from_cache:
        print(f"Loading observations from {args.from_cache}...")
        with open(args.from_cache) as f:
            cache = json.load(f)
        # Convert string keys to int, and lists back to tuples
        all_observations = {
            int(k): [(x, y, c) for x, y, c in v]
            for k, v in cache["seeds"].items()
        }
        print(f"  Loaded {sum(len(v) for v in all_observations.values())} observations")
    else:
        print("Observing all seeds (9 viewports × 5 seeds = 45 queries)...")
        try:
            budget = get_budget()
            print(f"  Budget: {budget['queries_used']}/{budget['queries_max']} used")
            if budget['queries_used'] >= budget['queries_max']:
                print("  WARNING: Query budget exhausted! Use --from-cache instead.")
                return
        except Exception as e:
            print(f"  Could not check budget: {e}")

        all_observations = observe_all_seeds(round_id, n_seeds)

        # Save cache
        cache_file = args.save_cache or f"observations_r{round_data['round_number']}.json"
        cache = {
            "round_id": round_id,
            "seeds": {str(k): v for k, v in all_observations.items()},
        }
        with open(cache_file, "w") as f:
            json.dump(cache, f)
        print(f"  Observations saved to {cache_file}")

    print()

    # Build and submit per-seed predictions
    class_names = ["Empty", "Settle", "Port", "Ruin", "Forest", "Mountain"]
    t0_total = time.time()

    for seed_index in range(n_seeds):
        print(f"\n=== Seed {seed_index} ===")
        initial_state = round_data["initial_states"][seed_index]
        seed_obs = all_observations.get(seed_index, [])

        t0 = time.time()
        prediction = predict_seed_with_observations(
            initial_state,
            seed_obs,
            n_mc_runs=args.mc_runs,
            param_samples=args.param_samples,
            prior_strength=args.prior_strength,
            use_optimized_params=not args.no_optimized_params,
            seed=seed_index * 1000,
        )
        elapsed = time.time() - t0

        print(f"  Built in {elapsed:.1f}s | obs: {len(seed_obs)} cells")
        print(f"  Min: {prediction.min():.4f}  Max: {prediction.max():.4f}")

        argmax = prediction.argmax(axis=2)
        print(f"  Class distribution: ", end="")
        parts = []
        for c in range(6):
            count = (argmax == c).sum()
            if count > 0:
                parts.append(f"{class_names[c]}={count}")
        print(", ".join(parts))

        # Log prediction for dashboard visualization
        log_prediction(round_id, seed_index, prediction, map_w, map_h)

        if not args.dry_run:
            result = submit_prediction(round_id, seed_index, prediction)
            print(f"  Submitted: {result}")
            log_submission(round_id, seed_index, result, map_w, map_h)
        else:
            print(f"  [dry-run] Skipped.")
            log_action(round_id, "dry_run_skip", {"seed_index": seed_index})

    print(f"\nTotal time: {time.time()-t0_total:.1f}s")
    print("Done!")


if __name__ == "__main__":
    main()
