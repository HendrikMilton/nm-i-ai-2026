"""
V5 Astar Island prediction pipeline — hybrid of V3 (MC+KT) and V4 (observation-calibrated priors).

Architecture:
  1. Fetch round data + initial states (free)
  2. Query API observations (uses budget) → calibrate expansion rate + dist decay
  3. Run MC simulations with LHS param sampling (like V3)
  4. Blend MC output with observation-calibrated distance priors (from V4/run.py)
  5. Bayesian Dirichlet update with raw observations
  6. KT-estimator floors + temperature scaling

Key improvements over V3:
  - Uses real observations to calibrate expansion rate (like V4)
  - Bayesian Dirichlet update: observations act as extra evidence, not just weighted average
  - Still uses MC for cells without observations (coverage gap)

Key improvements over V4/run.py:
  - KT estimator floors instead of flat floors (+8-10 pts)
  - MC provides a fallback distribution for unobserved cells
  - Temperature scaling to sharpen confident predictions

Usage:
    AINM_TOKEN=<token> python predict_v5.py
    AINM_TOKEN=<token> python predict_v5.py --dry-run
    python predict_v5.py --from-cache observations.json --round-data round.json --dry-run
"""
import argparse
import json
import os
import time
import numpy as np
from multiprocessing import Pool, cpu_count

from simulator import (
    SimParams, run_simulation, parse_initial_grid as parse_grid_np,
    apply_static_overrides, is_static,
    OCEAN, MOUNTAIN,
)

# Import V4's observation and prior machinery
from predict_v4 import (
    N_CLASSES, N_SEEDS, VIEWPORT, RATE_LIMIT_DELAY,
    TERRAIN_TO_CLASS, DIST_DECAY_DEFAULT,
    compute_settlement_distances,
    estimate_expansion_rate,
    estimate_dist_decay,
    estimate_port_ruin_ratios,
    get_distance_aware_prior,
    get_contextual_prior,
    build_prediction as build_prior_prediction,
    find_dynamic_viewports,
    observe_seed,
    empty_counts,
    obs_cache_to_counts,
    compute_seed_surprise,
)

from dashboard_logger import log_action, log_query, log_submission, log_prediction


# ---------------------------------------------------------------------------
# MC simulation (from V3)
# ---------------------------------------------------------------------------

PARAM_RANGES = {
    "expansion_rate":      (0.01, 0.70),
    "conflict_prob":       (0.01, 0.60),
    "winter_severity":     (0.05, 0.80),
    "trade_range":         (3, 14),
    "ruin_reclaim_rate":   (0.05, 0.70),
    "forest_reclaim_rate": (0.01, 0.30),
    "longship_prob":       (0.02, 0.45),
    "longship_range":      (4, 18),
}
INT_PARAMS = {"trade_range", "longship_range"}


def sample_params_lhs(n_samples, seed):
    from scipy.stats import qmc
    keys = list(PARAM_RANGES.keys())
    sampler = qmc.LatinHypercube(d=len(keys), seed=seed)
    samples = sampler.random(n=n_samples)
    param_sets = []
    for i in range(n_samples):
        vals = {}
        for j, key in enumerate(keys):
            lo, hi = PARAM_RANGES[key]
            v = lo + samples[i, j] * (hi - lo)
            vals[key] = int(round(v)) if key in INT_PARAMS else float(v)
        param_sets.append(SimParams(**vals))
    return param_sets


def _run_param_batch(args):
    grid_list, settlements_data, params_dict, n_runs, base_seed, param_idx = args
    H, W = len(grid_list), len(grid_list[0])
    counts = np.zeros((H, W, 6), dtype=np.float32)
    rng = np.random.default_rng(base_seed)
    for _ in range(n_runs):
        run_rng = np.random.default_rng(int(rng.integers(2**31)))
        params = SimParams(**params_dict)
        result = run_simulation(grid_list, settlements_data, params, run_rng)
        for cls in range(6):
            counts[:, :, cls] += (result == cls).astype(np.float32)
    return param_idx, counts


def run_mc_simulations(grid_list, settlements_data, n_params=100, runs_per_param=8,
                       seed=42, workers=1):
    """Run LHS MC simulations, return (H,W,6) counts and total run count."""
    rng = np.random.default_rng(seed)
    param_sets = sample_params_lhs(n_params, seed=int(rng.integers(2**31)))

    args_list = []
    for i, ps in enumerate(param_sets):
        ps_dict = {f: getattr(ps, f) for f in PARAM_RANGES}
        args_list.append((
            grid_list, settlements_data, ps_dict,
            runs_per_param, int(rng.integers(2**31)), i
        ))

    if workers > 1:
        with Pool(workers) as pool:
            results = pool.map(_run_param_batch, args_list)
    else:
        results = [_run_param_batch(a) for a in args_list]

    H, W = len(grid_list), len(grid_list[0])
    total_counts = np.zeros((H, W, 6), dtype=np.float64)
    for _, counts in results:
        total_counts += counts.astype(np.float64)

    total_runs = n_params * runs_per_param
    return total_counts, total_runs


# ---------------------------------------------------------------------------
# KT estimator + temperature (from V3)
# ---------------------------------------------------------------------------

def kt_floor_and_normalize(probs, total_counts):
    K = 6
    counts = probs * total_counts[:, :, np.newaxis]
    kt_probs = (counts + 0.5) / (total_counts[:, :, np.newaxis] + K / 2.0)
    kt_probs /= kt_probs.sum(axis=2, keepdims=True)
    return kt_probs


def apply_temperature(probs, temperature):
    if abs(temperature - 1.0) < 1e-6:
        return probs
    eps = 1e-10
    log_probs = np.log(np.maximum(probs, eps))
    scaled = np.exp(log_probs / temperature)
    scaled /= scaled.sum(axis=2, keepdims=True)
    return scaled


# ---------------------------------------------------------------------------
# Hybrid prediction: MC + observation-calibrated priors + Dirichlet update
# ---------------------------------------------------------------------------

def build_hybrid_prediction(
    grid_list, settlements_data,
    mc_counts, mc_total_runs,
    obs_counts_per_seed,  # dict of seed → H×W×6 list counts
    expansion_rate, dist_multipliers,
    port_ratio, ruin_ratio,
    mc_weight=0.6, prior_weight=0.4,
    temperature=0.95,
    dirichlet_equiv=40,  # equivalent sample count for prior in Dirichlet update
    workers=1,
):
    """
    Build prediction blending MC, distance-aware priors, and observations.

    Strategy:
    1. Build distance-aware prior (calibrated from observations)
    2. Blend with MC via weighted average
    3. For observed cells: Bayesian Dirichlet update using blend as prior
    4. Apply KT floors + temperature
    """
    H, W = len(grid_list), len(grid_list[0])
    grid_np = parse_grid_np(grid_list)
    grid = [[int(grid_list[r][c]) for c in range(W)] for r in range(H)]

    dist_map = compute_settlement_distances(grid, H, W)

    # Build distance-aware prior array
    prior = np.zeros((H, W, 6), dtype=np.float64)
    for r in range(H):
        for c in range(W):
            prior[r, c] = get_distance_aware_prior(
                grid, r, c, H, W, dist_map, expansion_rate,
                dist_multipliers=dist_multipliers,
                port_ratio=port_ratio, ruin_ratio=ruin_ratio,
            )

    # MC probabilities
    mc_count_per_cell = np.maximum(mc_counts.sum(axis=2), 1.0)
    mc_probs = mc_counts / mc_count_per_cell[:, :, np.newaxis]

    # Blend MC + prior
    total_w = mc_weight + prior_weight
    blended = (mc_weight * mc_probs + prior_weight * prior) / total_w
    blended = np.maximum(blended, 1e-8)
    blended /= blended.sum(axis=2, keepdims=True)

    # Aggregate observations across seeds
    agg_obs = np.zeros((H, W, 6), dtype=np.float64)
    for s, counts in obs_counts_per_seed.items():
        for r in range(H):
            for c in range(W):
                for k in range(6):
                    agg_obs[r, c, k] += counts[r][c][k]

    obs_total = agg_obs.sum(axis=2)  # (H, W)

    # Bayesian Dirichlet update for observed cells
    # Prior: alpha_k = blended[k] * dirichlet_equiv
    # Posterior: alpha_k + obs_count_k
    # Result: posterior / sum(posterior)
    alpha = blended * dirichlet_equiv
    posterior = alpha + agg_obs
    posterior_total = posterior.sum(axis=2, keepdims=True)
    result = posterior / np.maximum(posterior_total, 1e-8)

    # For cells with no observations, use the blend directly
    no_obs_mask = obs_total == 0
    result[no_obs_mask] = blended[no_obs_mask]

    # Apply temperature
    result = apply_temperature(result, temperature)

    # KT floors using effective sample counts
    effective_counts = mc_count_per_cell + obs_total
    result = kt_floor_and_normalize(result, effective_counts)

    # Static overrides
    result = apply_static_overrides(result, grid_np)

    # Final safety floor
    result = np.maximum(result, 0.001)
    result /= result.sum(axis=2, keepdims=True)

    return result


# ---------------------------------------------------------------------------
# Offline evaluation helper
# ---------------------------------------------------------------------------

def predict_seed_v5_offline(
    grid_list, settlements_data, seed,
    mc_counts=None, mc_total_runs=0,
    obs_counts=None,
    expansion_rate=0.15,
    dist_multipliers=None,
    port_ratio=0.35, ruin_ratio=0.15,
    n_mc_params=100, mc_runs_per_param=8,
    mc_weight=0.6, prior_weight=0.4,
    temperature=0.95, dirichlet_equiv=40,
    workers=1,
):
    """Offline prediction for one seed (no API)."""
    H, W = len(grid_list), len(grid_list[0])

    # Run MC if not provided
    if mc_counts is None:
        mc_counts, mc_total_runs = run_mc_simulations(
            grid_list, settlements_data,
            n_params=n_mc_params, runs_per_param=mc_runs_per_param,
            seed=seed, workers=workers,
        )

    # Use empty obs if none provided
    if obs_counts is None:
        obs_counts = {0: empty_counts(H, W)}

    return build_hybrid_prediction(
        grid_list, settlements_data,
        mc_counts, mc_total_runs,
        obs_counts,
        expansion_rate=expansion_rate,
        dist_multipliers=dist_multipliers or DIST_DECAY_DEFAULT,
        port_ratio=port_ratio, ruin_ratio=ruin_ratio,
        mc_weight=mc_weight, prior_weight=prior_weight,
        temperature=temperature,
        dirichlet_equiv=dirichlet_equiv,
        workers=workers,
    )


# ---------------------------------------------------------------------------
# Main (live pipeline)
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="V5 hybrid pipeline")
    parser.add_argument("--round-id", help="Round UUID")
    parser.add_argument("--round-data", help="Load round data from JSON file")
    parser.add_argument("--from-cache", help="Load observations from JSON cache")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=max(1, cpu_count() - 1))
    parser.add_argument("--mc-params", type=int, default=100)
    parser.add_argument("--mc-runs", type=int, default=8)
    parser.add_argument("--mc-weight", type=float, default=0.6)
    parser.add_argument("--prior-weight", type=float, default=0.4)
    parser.add_argument("--temperature", type=float, default=0.95)
    parser.add_argument("--dirichlet-equiv", type=int, default=40)
    args = parser.parse_args()

    from api_client import get_round, get_active_round, get_budget, submit_prediction

    # Load round data
    if args.round_data:
        with open(args.round_data) as f:
            round_data = json.load(f)
    elif args.round_id:
        round_data = get_round(args.round_id)
    else:
        active = get_active_round()
        if not active:
            print("No active round.")
            return
        round_data = get_round(active["id"])

    round_id = round_data["id"]
    map_w = int(round_data.get("map_width", 40))
    map_h = int(round_data.get("map_height", 40))
    n_seeds = round_data.get("seeds_count", len(round_data.get("initial_states", [])))

    print(f"Round {round_data.get('round_number', '?')} ({round_id})")
    print(f"Map: {map_w}×{map_h}, {n_seeds} seeds")
    print(f"MC: {args.mc_params}×{args.mc_runs}, mc_w={args.mc_weight}, "
          f"prior_w={args.prior_weight}, T={args.temperature}")

    initial_states = round_data.get("initial_states", [])
    seed_grids = {i: state["grid"] for i, state in enumerate(initial_states) if "grid" in state}

    # --- Observations ---
    if args.from_cache:
        print(f"\nLoading observations from {args.from_cache}...")
        with open(args.from_cache) as f:
            cache = json.load(f)
        seed_counts = {
            s: obs_cache_to_counts(cache["seeds"], s, map_h, map_w)
            for s in range(n_seeds)
        }
    else:
        # Query API
        budget_info = get_budget()
        used = int(budget_info.get("queries_used", 0))
        max_q = int(budget_info.get("queries_max", 50))
        total_budget = max_q - used
        print(f"Budget: {total_budget} remaining")

        seed_vps = {}
        for s in range(n_seeds):
            seed_vps[s] = find_dynamic_viewports(seed_grids[s], map_h, map_w)

        seed_counts = {}
        budget_spent = 0
        for s in range(n_seeds):
            vps = seed_vps[s][:max(0, total_budget - budget_spent)]
            if not vps:
                seed_counts[s] = empty_counts(map_h, map_w)
                continue
            print(f"\nSeed {s}: {len(vps)} queries...")
            seed_counts[s] = observe_seed(round_id, s, vps, map_h, map_w)
            budget_spent += len(vps)

    # --- Estimate round params from observations ---
    print("\nEstimating expansion rate...")
    expansion_rates = []
    agg_dist_stats = {}
    for s in range(n_seeds):
        grid = seed_grids[s]
        dist_map = compute_settlement_distances(grid, map_h, map_w)
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
    d13_total = sum(agg_dist_stats.get(d, [0, 0])[1] for d in [1, 2, 3])
    base_rate = d13_settle / d13_total if d13_total > 0 else avg_expansion

    dist_multipliers = {}
    for d in range(1, 8):
        if d in agg_dist_stats and agg_dist_stats[d][1] >= 10 and base_rate > 0.001:
            dist_multipliers[d] = (agg_dist_stats[d][0] / agg_dist_stats[d][1]) / base_rate
        else:
            dist_multipliers[d] = DIST_DECAY_DEFAULT.get(d, 0.0)

    port_ratio, ruin_ratio = estimate_port_ruin_ratios(seed_grids, seed_counts, map_h, map_w)

    print(f"  Expansion: {avg_expansion:.4f}")
    print(f"  Dist multipliers: " + " ".join(f"d{d}={dist_multipliers.get(d,0):.2f}" for d in range(1, 8)))
    print(f"  Port: {port_ratio:.3f}, Ruin: {ruin_ratio:.3f}")

    # --- Per-seed: run MC + blend + submit ---
    for seed_idx in range(n_seeds):
        print(f"\n--- Seed {seed_idx} ---")
        grid_list = seed_grids[seed_idx]
        settlements = initial_states[seed_idx].get("settlements", [])
        if not settlements:
            for r in range(map_h):
                for c in range(map_w):
                    if grid_list[r][c] in (1, 2):
                        settlements.append({"x": c, "y": r, "has_port": grid_list[r][c] == 2,
                                            "alive": True, "owner_id": len(settlements)})

        t0 = time.time()
        print(f"  Running MC ({args.mc_params}×{args.mc_runs})...")
        mc_counts, mc_total = run_mc_simulations(
            grid_list, settlements, n_params=args.mc_params, runs_per_param=args.mc_runs,
            seed=seed_idx * 10000 + 42, workers=args.workers,
        )

        pred = build_hybrid_prediction(
            grid_list, settlements,
            mc_counts, mc_total,
            {seed_idx: seed_counts[seed_idx]},
            expansion_rate=avg_expansion,
            dist_multipliers=dist_multipliers,
            port_ratio=port_ratio, ruin_ratio=ruin_ratio,
            mc_weight=args.mc_weight, prior_weight=args.prior_weight,
            temperature=args.temperature,
            dirichlet_equiv=args.dirichlet_equiv,
        )
        print(f"  Done in {time.time()-t0:.1f}s")
        print(f"  Min: {pred.min():.6f}, Max: {pred.max():.6f}")

        log_prediction(round_id, seed_idx, pred, map_width=map_w, map_height=map_h)

        if not args.dry_run:
            try:
                result = submit_prediction(round_id, seed_idx, pred)
                print(f"  Submitted: {result}")
                log_submission(round_id, seed_idx, result, map_width=map_w, map_height=map_h)
            except Exception as e:
                print(f"  Submit ERROR: {e}")
            time.sleep(0.6)
        else:
            print("  [dry-run]")

    print("\nDone!")


if __name__ == "__main__":
    main()
