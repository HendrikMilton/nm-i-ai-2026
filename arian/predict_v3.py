"""
Astar Island v3 prediction pipeline — targeting 90+ scores.

Key insight: The MC approach is fundamentally sound (same simulator = same distributions).
The bottleneck is parameter uncertainty. Solution:
1. Use observations to NARROW parameter ranges via ABC
2. Run MC with fitted params → much better distributions
3. Use empirical observations as a LIGHT Bayesian correction (not replacement)

Usage:
    AINM_TOKEN=<token> python predict_v3.py
    AINM_TOKEN=<token> python predict_v3.py --from-cache observations_r3.json
    AINM_TOKEN=<token> python predict_v3.py --dry-run
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
    SimParams, run_simulation,
    parse_initial_grid, apply_static_overrides,
    API_TO_CLASS, OCEAN, MOUNTAIN,
)
from dashboard_logger import log_action, log_query, log_submission, log_prediction


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


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

def observe_all_seeds(round_id: str, n_seeds: int = 5) -> dict:
    """Observe full map for all seeds. Returns {seed_index: {(x,y): class}}."""
    all_obs = {}
    queries_used = 0

    for seed_index in range(n_seeds):
        print(f"  Observing seed {seed_index}...")
        seed_obs = {}

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
                            seed_obs[(cx, cy)] = API_TO_CLASS.get(api_val, 0)

                budget_remaining = result.get("queries_max", 50) - result.get("queries_used", queries_used)
                print(f"    VP ({vx:2d},{vy:2d}) | q: {result.get('queries_used','?')}/{result.get('queries_max','?')}")
                log_query(
                    round_id, seed_index,
                    viewport={"x": ax, "y": ay, "w": vw, "h": vh},
                    grid=obs_grid,
                    budget_remaining=budget_remaining,
                    settlements=result.get("settlements"),
                )
                time.sleep(0.22)

            except Exception as e:
                print(f"    VP ({vx},{vy}) FAILED: {e}")
                log_action(round_id, "query_error", {"seed": seed_index, "vp": [vx, vy], "error": str(e)})

        all_obs[seed_index] = seed_obs
        print(f"    Seed {seed_index}: {len(seed_obs)} cells observed")

    print(f"  Total queries used: {queries_used}")
    return all_obs


# ---------------------------------------------------------------------------
# ABC Parameter Fitting — likelihood-based scoring
# ---------------------------------------------------------------------------

def _build_obs_grids(all_observations, H, W):
    """Convert observations dict to numpy grids."""
    obs_grids = {}
    for seed_idx, seed_obs in all_observations.items():
        grid = np.full((H, W), -1, dtype=np.int32)
        for (x, y), cls in seed_obs.items():
            if 0 <= y < H and 0 <= x < W:
                grid[y, x] = cls
        obs_grids[seed_idx] = grid
    return obs_grids


def _sample_params(lhs_row, keys, param_ranges, int_keys):
    """Convert one LHS row to SimParams."""
    param_vals = {}
    for j, key in enumerate(keys):
        lo, hi = param_ranges[key]
        val = lo + lhs_row[j] * (hi - lo)
        param_vals[key] = int(round(val)) if key in int_keys else float(val)
    return SimParams(**param_vals)


def _score_params_match_rate(params, grid_list, settlements_data, obs_grids, dynamic_mask, rng, n_sims=3):
    """Quick scoring: fraction of dynamic cells matching observations."""
    total_score = 0.0
    n_comparisons = 0
    for _ in range(n_sims):
        run_rng = np.random.default_rng(int(rng.integers(2**31)))
        result = run_simulation(grid_list, settlements_data, params, run_rng)
        for obs_grid in obs_grids.values():
            match_mask = (obs_grid >= 0) & dynamic_mask
            if match_mask.sum() == 0:
                continue
            matches = (result[match_mask] == obs_grid[match_mask]).sum()
            total_score += matches / match_mask.sum()
            n_comparisons += 1
    return total_score / max(n_comparisons, 1)


def _score_params_likelihood(params, grid_list, settlements_data, obs_grids, dynamic_mask, rng, n_mc=50):
    """Precise scoring: mean log-likelihood of observations under MC distribution."""
    H, W = len(grid_list), len(grid_list[0])
    counts = np.zeros((H, W, 6), dtype=np.float32)
    for _ in range(n_mc):
        run_rng = np.random.default_rng(int(rng.integers(2**31)))
        result = run_simulation(grid_list, settlements_data, params, run_rng)
        for cls in range(6):
            counts[:, :, cls] += (result == cls).astype(np.float32)

    total = np.maximum(counts.sum(axis=2, keepdims=True), 1.0)
    probs = counts / total
    probs = np.maximum(probs, 0.002)
    probs = probs / probs.sum(axis=2, keepdims=True)

    total_ll = 0.0
    n_cells = 0
    for obs_grid in obs_grids.values():
        mask = (obs_grid >= 0) & dynamic_mask
        ys, xs = np.where(mask)
        for y, x in zip(ys, xs):
            total_ll += np.log(probs[y, x, obs_grid[y, x]])
            n_cells += 1

    return total_ll / max(n_cells, 1)


def abc_fit_params(
    grid_list: list[list[int]],
    settlements_data: list[dict],
    all_observations: dict,
    n_stage1: int = 500,
    n_stage2_refine: int = 200,
    stage2_mc: int = 50,
    top_k: int = 15,
    seed: int = 42,
) -> list[tuple[SimParams, float]]:
    """
    Two-stage ABC parameter fitting:

    Stage 1 (fast filter): Test many candidates with few sims each.
             Score by match rate. Keep top 50.
    Stage 2 (precise): Refine around top candidates with more MC runs.
             Score by log-likelihood. Keep top_k.

    This is 5-10x faster than single-stage log-likelihood for same quality.
    """
    from scipy.stats import qmc

    H, W = len(grid_list), len(grid_list[0])
    rng = np.random.default_rng(seed)

    param_ranges = {
        "expansion_rate":      (0.02, 0.90),
        "conflict_prob":       (0.02, 0.60),
        "winter_severity":     (0.05, 0.80),
        "trade_range":         (2, 15),
        "ruin_reclaim_rate":   (0.05, 0.90),
        "forest_reclaim_rate": (0.01, 0.50),
        "longship_prob":       (0.02, 0.70),
        "longship_range":      (3, 20),
    }
    keys = list(param_ranges.keys())
    int_keys = {"trade_range", "longship_range"}

    obs_grids = _build_obs_grids(all_observations, H, W)
    initial_grid = parse_initial_grid(grid_list)
    dynamic_mask = (initial_grid != OCEAN) & (initial_grid != MOUNTAIN)

    # --- Stage 1: fast filter with match rate ---
    print(f"    Stage 1: {n_stage1} candidates (match rate filter)...")
    t0 = time.time()

    sampler = qmc.LatinHypercube(d=len(keys), seed=int(rng.integers(2**31)))
    lhs = sampler.random(n=n_stage1)

    stage1_results = []
    for i in range(n_stage1):
        params = _sample_params(lhs[i], keys, param_ranges, int_keys)
        score = _score_params_match_rate(
            params, grid_list, settlements_data, obs_grids, dynamic_mask, rng, n_sims=2
        )
        stage1_results.append((params, score))

        if (i + 1) % 100 == 0:
            best = max(r[1] for r in stage1_results)
            print(f"      {i+1}/{n_stage1}, best match: {best:.3f}, {time.time()-t0:.1f}s")

    stage1_results.sort(key=lambda x: x[1], reverse=True)
    stage1_top = stage1_results[:50]
    print(f"    Stage 1 done: top match = {stage1_top[0][1]:.3f} ({time.time()-t0:.1f}s)")

    # --- Stage 2: refine with log-likelihood ---
    # Generate new candidates around the top stage-1 results (local search)
    print(f"    Stage 2: {n_stage2_refine} refinements (log-likelihood)...")
    t0 = time.time()

    stage2_candidates = []

    # Keep top stage-1 params as-is
    for params, _ in stage1_top[:20]:
        stage2_candidates.append(params)

    # Perturb top params to explore nearby
    for _ in range(n_stage2_refine - 20):
        base_params, _ = stage1_top[rng.integers(len(stage1_top))]
        # Small perturbation (±20% of range)
        new_vals = {}
        for key in keys:
            lo, hi = param_ranges[key]
            current = getattr(base_params, key)
            noise = rng.uniform(-0.2, 0.2) * (hi - lo)
            new_val = np.clip(current + noise, lo, hi)
            new_vals[key] = int(round(new_val)) if key in int_keys else float(new_val)
        stage2_candidates.append(SimParams(**new_vals))

    stage2_results = []
    for i, params in enumerate(stage2_candidates):
        ll = _score_params_likelihood(
            params, grid_list, settlements_data, obs_grids, dynamic_mask, rng, n_mc=stage2_mc
        )
        stage2_results.append((params, ll))

        if (i + 1) % 50 == 0:
            best = max(r[1] for r in stage2_results)
            print(f"      {i+1}/{len(stage2_candidates)}, best LL: {best:.4f}, {time.time()-t0:.1f}s")

    stage2_results.sort(key=lambda x: x[1], reverse=True)
    top = stage2_results[:top_k]

    print(f"    Stage 2 done: best LL = {top[0][1]:.4f} ({time.time()-t0:.1f}s)")
    p = top[0][0]
    print(f"  Best params: exp={p.expansion_rate:.3f} conf={p.conflict_prob:.3f} "
          f"win={p.winter_severity:.3f} ruin={p.ruin_reclaim_rate:.3f} "
          f"forest={p.forest_reclaim_rate:.3f}")

    return top


# ---------------------------------------------------------------------------
# MC with fitted params (weighted by likelihood)
# ---------------------------------------------------------------------------

def mc_with_fitted_params(
    grid_list: list[list[int]],
    settlements_data: list[dict],
    fitted_params: list[tuple[SimParams, float]],
    total_runs: int = 500,
    seed: int = 0,
) -> np.ndarray:
    """
    Run MC using ABC-fitted params, weighted by their log-likelihood.
    Better-fitting params get proportionally more simulation runs.
    """
    H, W = len(grid_list), len(grid_list[0])
    counts = np.zeros((H, W, 6), dtype=np.float32)
    rng = np.random.default_rng(seed)

    # Convert log-likelihoods to run weights via softmax
    lls = np.array([ll for _, ll in fitted_params])
    weights = np.exp(lls - lls.max())  # softmax with temperature=1
    weights = weights / weights.sum()

    run_counts = np.maximum(1, (weights * total_runs).astype(int))
    actual_total = run_counts.sum()

    print(f"  MC: {len(fitted_params)} param sets, {actual_total} total runs")
    print(f"  Top param gets {run_counts[0]} runs, bottom gets {run_counts[-1]} runs")

    for (params, _), n_runs in zip(fitted_params, run_counts):
        for _ in range(int(n_runs)):
            run_rng = np.random.default_rng(int(rng.integers(2**31)))
            result = run_simulation(grid_list, settlements_data, params, run_rng)
            for cls in range(6):
                counts[:, :, cls] += (result == cls).astype(np.float32)

    total = np.maximum(counts.sum(axis=2, keepdims=True), 1.0)
    probs = counts / total
    # Low floor: 0.5/total_runs. With 500 runs, floor ≈ 0.001
    # This is critical: 0.01 floor caps score at ~89, but 0.002 allows 95+
    actual_runs = int(total.max())
    floor = max(0.002, 0.5 / max(actual_runs, 1))
    probs = np.maximum(probs, floor)
    probs = probs / probs.sum(axis=2, keepdims=True)
    return probs


# ---------------------------------------------------------------------------
# Light Bayesian correction with empirical observations
# ---------------------------------------------------------------------------

def bayesian_correct(
    mc_prediction: np.ndarray,
    all_observations: dict,
    mc_equiv_samples: float = 50.0,
    H: int = 40,
    W: int = 40,
) -> np.ndarray:
    """
    Light Bayesian correction: treat MC prediction as a Dirichlet prior
    worth mc_equiv_samples pseudo-observations, then update with real observations.

    With mc_equiv_samples=50 and 5 real observations, the MC gets ~91% weight.
    This is the right balance: MC has the right distribution shape,
    observations provide a small nudge.
    """
    # Convert MC probs to Dirichlet pseudo-counts
    alpha = mc_prediction * mc_equiv_samples  # (H, W, 6)

    # Add observation counts
    obs_counts = np.zeros((H, W, 6), dtype=np.float32)
    for seed_idx, seed_obs in all_observations.items():
        for (x, y), cls in seed_obs.items():
            if 0 <= cls <= 5 and 0 <= y < H and 0 <= x < W:
                obs_counts[y, x, cls] += 1.0

    posterior = alpha + obs_counts
    posterior = posterior / posterior.sum(axis=2, keepdims=True)

    # Low safety floor (matching MC floor)
    posterior = np.maximum(posterior, 0.002)
    posterior = posterior / posterior.sum(axis=2, keepdims=True)

    n_observed = (obs_counts.sum(axis=2) > 0).sum()
    print(f"  Bayesian correction: {n_observed} cells nudged (MC weight ≈ {mc_equiv_samples/(mc_equiv_samples+5):.0%})")

    return posterior


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Astar Island v3 — ABC + fitted MC")
    parser.add_argument("--round-id", help="Round UUID (auto-detects active)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--from-cache", help="Load observations from JSON file")
    parser.add_argument("--save-cache", help="Save observations to JSON file")
    parser.add_argument("--abc-stage1", type=int, default=500,
                        help="Stage 1 ABC candidates (default: 500)")
    parser.add_argument("--abc-stage2", type=int, default=200,
                        help="Stage 2 refinements (default: 200)")
    parser.add_argument("--abc-mc", type=int, default=50,
                        help="MC runs per stage-2 candidate (default: 50)")
    parser.add_argument("--abc-top-k", type=int, default=15,
                        help="Top K param sets to keep (default: 15)")
    parser.add_argument("--mc-runs", type=int, default=500,
                        help="Total MC runs with fitted params (default: 500)")
    parser.add_argument("--mc-equiv", type=float, default=50.0,
                        help="MC equivalent samples for Bayesian correction (default: 50)")
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
    round_num = round_data.get("round_number", "?")
    map_w = round_data.get("map_width", 40)
    map_h = round_data.get("map_height", 40)

    print(f"Round {round_num} ({round_id})")
    print(f"Map: {map_w}x{map_h}, {n_seeds} seeds")
    print()

    log_action(round_id, "start_pipeline", {
        "round_number": round_num,
        "map_width": map_w,
        "map_height": map_h,
        "n_seeds": n_seeds,
        "pipeline": "v3",
        "abc_stage1": args.abc_stage1,
        "abc_stage2": args.abc_stage2,
        "abc_mc": args.abc_mc,
        "mc_runs": args.mc_runs,
        "mc_equiv": args.mc_equiv,
        "from_cache": args.from_cache,
    }, map_width=map_w, map_height=map_h)

    # --- Step 1: Observe ---
    if args.from_cache:
        print(f"Loading observations from {args.from_cache}...")
        with open(args.from_cache) as f:
            cache = json.load(f)
        all_observations = {}
        for k, v in cache["seeds"].items():
            seed_obs = {}
            for item in v:
                if len(item) == 3:
                    x, y, c = item
                    seed_obs[(x, y)] = c
            all_observations[int(k)] = seed_obs
        print(f"  Loaded {sum(len(v) for v in all_observations.values())} cell observations")
    else:
        print("Step 1: Observing all seeds (9 viewports x 5 seeds = 45 queries)...")
        try:
            budget = get_budget()
            print(f"  Budget: {budget['queries_used']}/{budget['queries_max']} used")
            if budget['queries_used'] >= budget['queries_max']:
                print("  WARNING: Budget exhausted! Use --from-cache.")
                return
        except Exception as e:
            print(f"  Could not check budget: {e}")

        all_observations = observe_all_seeds(round_id, n_seeds)

        cache_file = args.save_cache or f"observations_r{round_num}.json"
        cache_seeds = {}
        for k, v in all_observations.items():
            cache_seeds[str(k)] = [[x, y, c] for (x, y), c in v.items()]
        with open(cache_file, "w") as f:
            json.dump({"round_id": round_id, "seeds": cache_seeds}, f)
        print(f"  Saved to {cache_file}")
    print()

    # --- Step 2: ABC parameter fitting ---
    initial_state_0 = round_data["initial_states"][0]
    grid_list = initial_state_0["grid"]
    settlements_data = initial_state_0["settlements"]

    print(f"Step 2: ABC parameter fitting (stage1={args.abc_stage1}, stage2={args.abc_stage2})...")
    t0 = time.time()
    fitted_params = abc_fit_params(
        grid_list, settlements_data, all_observations,
        n_stage1=args.abc_stage1,
        n_stage2_refine=args.abc_stage2,
        stage2_mc=args.abc_mc,
        top_k=args.abc_top_k,
        seed=42,
    )
    abc_elapsed = time.time() - t0
    best_p = fitted_params[0][0]
    log_action(round_id, "abc_complete", {
        "elapsed_s": round(abc_elapsed, 1),
        "best_ll": round(fitted_params[0][1], 4),
        "worst_ll": round(fitted_params[-1][1], 4),
        "best_params": {
            "expansion_rate": round(best_p.expansion_rate, 3),
            "conflict_prob": round(best_p.conflict_prob, 3),
            "winter_severity": round(best_p.winter_severity, 3),
            "ruin_reclaim_rate": round(best_p.ruin_reclaim_rate, 3),
            "forest_reclaim_rate": round(best_p.forest_reclaim_rate, 3),
            "trade_range": best_p.trade_range,
            "longship_prob": round(best_p.longship_prob, 3),
            "longship_range": best_p.longship_range,
        },
    }, map_width=map_w, map_height=map_h)
    print(f"  ABC took {abc_elapsed:.1f}s")
    print()

    # --- Step 3: MC with fitted params ---
    print(f"Step 3: Running MC with top {args.abc_top_k} fitted param sets ({args.mc_runs} runs)...")
    t0 = time.time()
    mc_prediction = mc_with_fitted_params(
        grid_list, settlements_data, fitted_params,
        total_runs=args.mc_runs,
        seed=123,
    )
    initial_grid = parse_initial_grid(grid_list)
    mc_prediction = apply_static_overrides(mc_prediction, initial_grid)
    mc_elapsed = time.time() - t0
    log_action(round_id, "mc_complete", {
        "elapsed_s": round(mc_elapsed, 1),
        "total_runs": args.mc_runs,
        "top_k_params": args.abc_top_k,
    }, map_width=map_w, map_height=map_h)
    print(f"  MC took {mc_elapsed:.1f}s")
    print()

    # --- Step 4: Bayesian correction ---
    print("Step 4: Bayesian correction with observations...")
    prediction = bayesian_correct(
        mc_prediction, all_observations,
        mc_equiv_samples=args.mc_equiv,
    )
    print()

    # --- Step 5: Submit per-seed ---
    print("Step 5: Submitting predictions...")
    class_names = ["Empty", "Settle", "Port", "Ruin", "Forest", "Mountain"]

    for seed_index in range(n_seeds):
        print(f"\n=== Seed {seed_index} ===")
        initial_state = round_data["initial_states"][seed_index]
        seed_initial_grid = parse_initial_grid(initial_state["grid"])

        # Apply per-seed static overrides (seeds may differ in ocean/mountain)
        seed_pred = prediction.copy()
        ocean_mask = (seed_initial_grid == OCEAN)
        mountain_mask = (seed_initial_grid == MOUNTAIN)
        seed_pred[ocean_mask, :] = 0.002
        seed_pred[ocean_mask, 0] = 0.99
        seed_pred[mountain_mask, :] = 0.002
        seed_pred[mountain_mask, 5] = 0.99
        seed_pred = seed_pred / seed_pred.sum(axis=2, keepdims=True)

        # Stats
        argmax = seed_pred.argmax(axis=2)
        parts = [f"{class_names[c]}={(argmax == c).sum()}" for c in range(6) if (argmax == c).sum() > 0]
        print(f"  Classes: {', '.join(parts)}")

        dynamic = (seed_initial_grid != OCEAN) & (seed_initial_grid != MOUNTAIN)
        if dynamic.sum() > 0:
            mean_conf = seed_pred.max(axis=2)[dynamic].mean()
            print(f"  Mean confidence (dynamic): {mean_conf:.3f}")

        log_prediction(round_id, seed_index, seed_pred, map_width=map_w, map_height=map_h)

        if not args.dry_run:
            result = submit_prediction(round_id, seed_index, seed_pred)
            print(f"  Submitted: {result}")
            log_submission(round_id, seed_index, result, map_width=map_w, map_height=map_h)
        else:
            print(f"  [dry-run] Skipped.")

    log_action(round_id, "pipeline_complete", {"dry_run": args.dry_run}, map_width=map_w, map_height=map_h)
    print("\nDone!")


if __name__ == "__main__":
    main()
