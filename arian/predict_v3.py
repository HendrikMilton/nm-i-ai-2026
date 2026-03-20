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
from multiprocessing import Pool, cpu_count

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
from contextual_prior import build_prior_prediction, classify_round_type, blend_prior_with_mc


# Full-coverage interior tiling: skip 1-cell ocean border, cover all interior cells.
# 3×3 grid of 15×15 viewports starting at row/col 1 (not 0).
# Origins: 1, 14, 25 along each axis → covers cols/rows 1-39 with overlap.
VIEWPORTS_INTERIOR = [
    (x, y, 15, 15)
    for y in (1, 14, 25)
    for x in (1, 14, 25)
]


def _count_dynamic_cells(grid, vx, vy, vw, vh, map_h, map_w):
    """Count non-ocean, non-mountain cells in a viewport. Higher = more valuable."""
    count = 0
    for r in range(vy, min(vy + vh, map_h)):
        for c in range(vx, min(vx + vw, map_w)):
            if grid[r][c] not in (10, 5):  # not ocean, not mountain
                count += 1
    return count


def _count_settlement_adjacent(grid, vx, vy, vw, vh, map_h, map_w):
    """Count cells within dist 1-3 of a settlement in this viewport. These drive the score."""
    # Find settlements
    settlements = set()
    for r in range(map_h):
        for c in range(map_w):
            if grid[r][c] in (1, 2):  # settlement or port
                settlements.add((r, c))

    count = 0
    for r in range(vy, min(vy + vh, map_h)):
        for c in range(vx, min(vx + vw, map_w)):
            if grid[r][c] in (10, 5):
                continue
            # Chebyshev distance to nearest settlement
            min_dist = 999
            for sr, sc in settlements:
                d = max(abs(r - sr), abs(c - sc))
                if d < min_dist:
                    min_dist = d
            if 1 <= min_dist <= 4:
                count += 1
    return count


def plan_viewports_for_seed(grid, map_h=40, map_w=40):
    """
    Plan viewports for one seed, prioritized by information value.

    Returns list of (vx, vy, vw, vh) sorted by value (highest first).
    Always includes the full interior tiling (9 VPs), sorted so the most
    informative viewports come first in case budget runs out mid-seed.
    """
    scored = []
    for (vx, vy, vw, vh) in VIEWPORTS_INTERIOR:
        # Score by settlement-adjacent cells (most valuable for ABC + expansion estimation)
        sa = _count_settlement_adjacent(grid, vx, vy, vw, vh, map_h, map_w)
        dyn = _count_dynamic_cells(grid, vx, vy, vw, vh, map_h, map_w)
        # Primary: settlement-adjacent, secondary: dynamic cells
        score = sa * 10 + dyn
        scored.append((score, vx, vy, vw, vh))

    scored.sort(reverse=True)
    return [(vx, vy, vw, vh) for (_, vx, vy, vw, vh) in scored]


def plan_all_queries(seed_grids, total_budget=50, map_h=40, map_w=40):
    """
    Allocate all 50 queries across 5 seeds optimally.

    Strategy:
    1. Each seed gets its 9 interior-tiling VPs, sorted by value
    2. Phase 1: Give each seed its top VPs, round-robin, most-valuable-first
    3. Phase 2: With remaining budget, give extra sweeps to highest-value seeds

    Returns:
        phase1_plan: {seed_idx: [(vx,vy,vw,vh), ...]}  — one sweep
        phase2_plan: {seed_idx: [(vx,vy,vw,vh), ...]}  — extra observations
    """
    n_seeds = len(seed_grids)

    # Get per-seed viewport priority lists
    seed_vps = {}
    seed_total_value = {}
    for s in range(n_seeds):
        grid = seed_grids.get(s)
        if grid is None:
            seed_vps[s] = list(VIEWPORTS_INTERIOR)
            seed_total_value[s] = 0
            continue
        vps = plan_viewports_for_seed(grid, map_h, map_w)
        seed_vps[s] = vps
        # Total value = sum of settlement-adjacent cells across all VPs
        seed_total_value[s] = sum(
            _count_settlement_adjacent(grid, vx, vy, vw, vh, map_h, map_w)
            for (vx, vy, vw, vh) in vps
        )

    # Phase 1: 9 VPs per seed = 45 queries, allocated round-robin by value
    phase1_plan = {s: [] for s in range(n_seeds)}
    budget_used = 0

    # Round-robin: give each seed one VP at a time, cycling through seeds
    # ordered by total value (most dynamic seed gets queried first)
    seed_order = sorted(range(n_seeds), key=lambda s: seed_total_value.get(s, 0), reverse=True)
    vp_idx = {s: 0 for s in range(n_seeds)}

    while budget_used < min(total_budget, 9 * n_seeds):
        allocated_this_round = False
        for s in seed_order:
            if budget_used >= total_budget:
                break
            idx = vp_idx[s]
            if idx < len(seed_vps[s]):
                phase1_plan[s].append(seed_vps[s][idx])
                vp_idx[s] += 1
                budget_used += 1
                allocated_this_round = True
        if not allocated_this_round:
            break

    # Phase 2: remaining budget → extra sweeps on highest-value seeds
    # Re-query the MOST VALUABLE viewports (near settlements) for 2nd observations
    remaining = total_budget - budget_used
    phase2_plan = {s: [] for s in range(n_seeds)}

    if remaining > 0:
        # Build a global priority list: (value, seed, vp)
        phase2_candidates = []
        for s in seed_order:
            grid = seed_grids.get(s)
            if grid is None:
                continue
            # Only re-query viewports that have settlement-adjacent cells
            for (vx, vy, vw, vh) in seed_vps[s][:5]:  # top 5 VPs per seed
                sa = _count_settlement_adjacent(grid, vx, vy, vw, vh, map_h, map_w)
                if sa > 0:
                    phase2_candidates.append((sa, s, vx, vy, vw, vh))

        phase2_candidates.sort(reverse=True)

        for i, (_, s, vx, vy, vw, vh) in enumerate(phase2_candidates):
            if i >= remaining:
                break
            phase2_plan[s].append((vx, vy, vw, vh))

    return phase1_plan, phase2_plan


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

def _query_viewport(round_id, seed_index, vx, vy, vw, vh, total_queries_ref):
    """Execute one viewport query, return observations dict {(x,y): class}."""
    result = simulate_viewport(round_id, seed_index, vx, vy, vw, vh)
    total_queries_ref[0] += 1
    obs = {}
    obs_grid = result["grid"]
    vp = result["viewport"]
    ax, ay = vp["x"], vp["y"]
    for row_i, row in enumerate(obs_grid):
        for col_i, api_val in enumerate(row):
            cx, cy = ax + col_i, ay + row_i
            if 0 <= cx < 40 and 0 <= cy < 40:
                obs[(cx, cy)] = API_TO_CLASS.get(api_val, 0)

    budget_remaining = result.get("queries_max", 50) - result.get("queries_used", total_queries_ref[0])
    log_query(
        round_id, seed_index,
        viewport={"x": ax, "y": ay, "w": vw, "h": vh},
        grid=obs_grid,
        budget_remaining=budget_remaining,
        settlements=result.get("settlements"),
    )
    return obs, budget_remaining


def observe_all_seeds(round_id: str, n_seeds: int = 5, n_sweeps: int = 1,
                      seed_grids: dict = None, total_budget: int = 50) -> tuple[dict, dict]:
    """
    Observe all seeds using optimized query placement.

    Phase 1: Full interior tiling, round-robin across seeds (most valuable first)
    Phase 2: Extra sweeps on highest-value viewports with remaining budget

    Returns:
        all_obs_single: {seed_idx: {(x,y): class}}  — first sweep observations, for ABC
        all_obs_multi:  {seed_idx: list[{(x,y): class}]}  — all sweeps, for empirical dist
    """
    total_queries = [0]  # mutable ref for nested function

    # Plan queries
    if seed_grids is not None:
        phase1_plan, phase2_plan = plan_all_queries(seed_grids, total_budget=total_budget)
    else:
        # Fallback: equal allocation with interior tiling
        phase1_plan = {s: list(VIEWPORTS_INTERIOR) for s in range(n_seeds)}
        phase2_plan = {s: [] for s in range(n_seeds)}

    phase1_total = sum(len(vps) for vps in phase1_plan.values())
    phase2_total = sum(len(vps) for vps in phase2_plan.values())
    print(f"  Query plan: Phase 1 = {phase1_total} queries, Phase 2 = {phase2_total} queries")
    print(f"  Per seed (Phase 1): {[len(phase1_plan[s]) for s in range(n_seeds)]}")
    if phase2_total > 0:
        print(f"  Per seed (Phase 2): {[len(phase2_plan[s]) for s in range(n_seeds)]}")

    all_obs_single = {}
    all_obs_multi = {}

    # --- Phase 1: main coverage sweep ---
    for seed_index in range(n_seeds):
        vps = phase1_plan[seed_index]
        if not vps:
            all_obs_single[seed_index] = {}
            all_obs_multi[seed_index] = [{}]
            continue

        print(f"  Phase 1 seed {seed_index}: {len(vps)} viewports")
        sweep_obs = {}
        for (vx, vy, vw, vh) in vps:
            try:
                obs, budget = _query_viewport(round_id, seed_index, vx, vy, vw, vh, total_queries)
                sweep_obs.update(obs)
                print(f"    VP ({vx:2d},{vy:2d}) | budget={budget}")
                time.sleep(0.22)
            except Exception as e:
                print(f"    VP ({vx},{vy}) FAILED: {e}")
                log_action(round_id, "query_error",
                           {"seed": seed_index, "vp": [vx, vy], "error": str(e)})

        all_obs_single[seed_index] = sweep_obs
        all_obs_multi[seed_index] = [sweep_obs]
        print(f"    → {len(sweep_obs)} cells observed")

    # --- Phase 2: extra sweeps on high-value viewports ---
    for seed_index in range(n_seeds):
        vps = phase2_plan[seed_index]
        if not vps:
            continue

        print(f"  Phase 2 seed {seed_index}: {len(vps)} extra viewports (2nd observations)")
        sweep_obs = {}
        for (vx, vy, vw, vh) in vps:
            try:
                obs, budget = _query_viewport(round_id, seed_index, vx, vy, vw, vh, total_queries)
                sweep_obs.update(obs)
                print(f"    VP ({vx:2d},{vy:2d}) | budget={budget}")
                time.sleep(0.22)
            except Exception as e:
                print(f"    VP ({vx},{vy}) P2 FAILED: {e}")
                log_action(round_id, "query_error",
                           {"seed": seed_index, "vp": [vx, vy], "phase": 2, "error": str(e)})

        all_obs_multi[seed_index].append(sweep_obs)
        print(f"    → {len(sweep_obs)} extra cells (2nd sweep)")

    print(f"  Total queries used: {total_queries[0]}/{total_budget}")
    return all_obs_single, all_obs_multi


def build_empirical_distribution(all_obs_multi: dict, H: int, W: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Build H×W×6 empirical distribution from multi-sweep observations.
    Each sweep of each seed is one independent sample from the true distribution.

    Returns:
        emp: H×W×6 empirical probabilities (uniform 1/6 for unobserved cells)
        n_obs: H×W count of observations per cell
    """
    counts = np.zeros((H, W, 6), dtype=np.float32)
    n_obs = np.zeros((H, W), dtype=np.float32)

    for sweeps in all_obs_multi.values():
        for sweep_obs in sweeps:
            for (x, y), cls in sweep_obs.items():
                if 0 <= cls <= 5 and 0 <= y < H and 0 <= x < W:
                    counts[y, x, cls] += 1
                    n_obs[y, x] += 1

    total = np.maximum(n_obs[:, :, np.newaxis], 1.0)
    emp = counts / total
    emp[n_obs == 0] = 1.0 / 6  # uniform prior for unobserved cells

    n_sweeps_total = sum(len(s) for s in all_obs_multi.values())
    print(f"  Empirical: {n_sweeps_total} sweeps, {int((n_obs > 0).sum())} cells observed")
    return emp, n_obs


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


def _stage1_worker(args):
    """Top-level worker for parallel Stage 1 ABC scoring (required for multiprocessing pickling)."""
    params, grid_list, settlements_data, obs_grids, dynamic_mask, seed, n_sims = args
    rng = np.random.default_rng(seed)
    return _score_params_match_rate(
        params, grid_list, settlements_data, obs_grids, dynamic_mask, rng, n_sims
    )


def _stage2_worker(args):
    """Top-level worker for parallel Stage 2 ABC scoring (required for multiprocessing pickling)."""
    params, grid_list, settlements_data, obs_grids, dynamic_mask, seed, n_mc = args
    rng = np.random.default_rng(seed)
    return _score_params_likelihood(
        params, grid_list, settlements_data, obs_grids, dynamic_mask, rng, n_mc
    )


def _mc_worker(args):
    """Top-level worker: runs all MC simulations for one param set, returns class count grid."""
    params, grid_list, settlements_data, seeds = args
    from simulator import run_simulation
    import numpy as np
    H, W = len(grid_list), len(grid_list[0])
    counts = np.zeros((H, W, 6), dtype=np.float32)
    for seed in seeds:
        rng = np.random.default_rng(seed)
        result = run_simulation(grid_list, settlements_data, params, rng)
        for cls in range(6):
            counts[:, :, cls] += (result == cls).astype(np.float32)
    return counts


def abc_fit_params(
    grid_list: list[list[int]],
    settlements_data: list[dict],
    all_observations: dict,
    n_stage1: int = 500,
    n_stage2_refine: int = 200,
    stage2_mc: int = 50,
    top_k: int = 15,
    seed: int = 42,
    n_workers: int = None,
) -> list[tuple[SimParams, float]]:
    """
    Two-stage ABC parameter fitting:

    Stage 1 (fast filter): Test many candidates with few sims each.
             Score by match rate. Keep top 50.
    Stage 2 (precise): Refine around top candidates with more MC runs.
             Score by log-likelihood. Keep top_k.

    This is 5-10x faster than single-stage log-likelihood for same quality.
    Parallelized with multiprocessing — each candidate scores independently.
    """
    from scipy.stats import qmc

    H, W = len(grid_list), len(grid_list[0])
    rng = np.random.default_rng(seed)
    n_workers = n_workers or cpu_count()

    # Tightened ranges aligned to known simulator param distribution
    # (true params drawn from these ranges in evaluation — narrower = more LHS samples on target)
    param_ranges = {
        "expansion_rate":      (0.05, 0.65),
        "conflict_prob":       (0.05, 0.55),
        "winter_severity":     (0.08, 0.75),
        "trade_range":         (3, 14),
        "ruin_reclaim_rate":   (0.08, 0.65),
        "forest_reclaim_rate": (0.01, 0.30),
        "longship_prob":       (0.04, 0.45),
        "longship_range":      (4, 17),
    }
    keys = list(param_ranges.keys())
    int_keys = {"trade_range", "longship_range"}

    obs_grids = _build_obs_grids(all_observations, H, W)
    initial_grid = parse_initial_grid(grid_list)
    dynamic_mask = (initial_grid != OCEAN) & (initial_grid != MOUNTAIN)

    # --- Stage 1: parallel match rate filter ---
    print(f"    Stage 1: {n_stage1} candidates, {n_workers} workers (match rate)...")
    t0 = time.time()

    sampler = qmc.LatinHypercube(d=len(keys), seed=int(rng.integers(2**31)))
    lhs = sampler.random(n=n_stage1)
    all_params_s1 = [_sample_params(lhs[i], keys, param_ranges, int_keys) for i in range(n_stage1)]

    worker_args_s1 = [
        (p, grid_list, settlements_data, obs_grids, dynamic_mask, int(rng.integers(2**31)), 2)
        for p in all_params_s1
    ]
    if n_workers == 1:
        scores_s1 = [_stage1_worker(a) for a in worker_args_s1]
    else:
        with Pool(n_workers) as pool:
            scores_s1 = pool.map(_stage1_worker, worker_args_s1)

    stage1_results = sorted(zip(all_params_s1, scores_s1), key=lambda x: x[1], reverse=True)
    stage1_top = stage1_results[:50]
    print(f"    Stage 1 done: top match = {stage1_top[0][1]:.3f} ({time.time()-t0:.1f}s)")

    # --- Stage 2: parallel log-likelihood refinement ---
    print(f"    Stage 2: {n_stage2_refine} candidates, {n_workers} workers (log-likelihood)...")
    t0 = time.time()

    stage2_candidates = [p for p, _ in stage1_top[:20]]
    for _ in range(n_stage2_refine - 20):
        base_params, _ = stage1_top[rng.integers(len(stage1_top))]
        new_vals = {}
        for key in keys:
            lo, hi = param_ranges[key]
            current = getattr(base_params, key)
            noise = rng.uniform(-0.2, 0.2) * (hi - lo)
            new_val = np.clip(current + noise, lo, hi)
            new_vals[key] = int(round(new_val)) if key in int_keys else float(new_val)
        stage2_candidates.append(SimParams(**new_vals))

    worker_args_s2 = [
        (p, grid_list, settlements_data, obs_grids, dynamic_mask, int(rng.integers(2**31)), stage2_mc)
        for p in stage2_candidates
    ]
    if n_workers == 1:
        lls = [_stage2_worker(a) for a in worker_args_s2]
    else:
        with Pool(n_workers) as pool:
            lls = pool.map(_stage2_worker, worker_args_s2)

    stage2_results = sorted(zip(stage2_candidates, lls), key=lambda x: x[1], reverse=True)
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
    n_workers: int = None,
) -> np.ndarray:
    """
    Run MC using ABC-fitted params, weighted by their log-likelihood.
    Better-fitting params get proportionally more simulation runs.
    Parallelized — all runs dispatched to worker pool simultaneously.
    """
    H, W = len(grid_list), len(grid_list[0])
    counts = np.zeros((H, W, 6), dtype=np.float32)
    rng = np.random.default_rng(seed)
    n_workers = n_workers or cpu_count()

    # Convert log-likelihoods to run weights via softmax
    lls = np.array([ll for _, ll in fitted_params])
    weights = np.exp(lls - lls.max())
    weights = weights / weights.sum()

    run_counts = np.maximum(1, (weights * total_runs).astype(int))
    actual_total = run_counts.sum()

    print(f"  MC: {len(fitted_params)} param sets, {actual_total} total runs, {n_workers} workers")

    # One task per param set — each task runs all its assigned simulations
    # This minimises IPC overhead vs one task per simulation
    all_args = [
        (params, grid_list, settlements_data,
         [int(rng.integers(2**31)) for _ in range(int(n_runs))])
        for (params, _), n_runs in zip(fitted_params, run_counts)
    ]

    if n_workers == 1:
        count_list = [_mc_worker(a) for a in all_args]
    else:
        with Pool(min(n_workers, len(all_args))) as pool:
            count_list = pool.map(_mc_worker, all_args)

    for c in count_list:
        counts += c

    total = np.maximum(counts.sum(axis=2, keepdims=True), 1.0)
    probs = counts / total
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
    Bayesian correction: treat MC prediction as a Dirichlet prior worth
    mc_equiv_samples pseudo-observations, then update with real observations.

    Works with both single-sweep ({seed_idx: {(x,y): class}}) and
    multi-sweep ({seed_idx: [{(x,y): class}, ...]}) observations.
    """
    alpha = mc_prediction * mc_equiv_samples  # (H, W, 6)

    obs_counts = np.zeros((H, W, 6), dtype=np.float32)
    for seed_idx, seed_obs in all_observations.items():
        # Support both single dict and list of sweep dicts
        sweeps = seed_obs if isinstance(seed_obs, list) else [seed_obs]
        for sweep in sweeps:
            for (x, y), cls in sweep.items():
                if 0 <= cls <= 5 and 0 <= y < H and 0 <= x < W:
                    obs_counts[y, x, cls] += 1.0

    total_obs = int(obs_counts.sum())
    posterior = alpha + obs_counts
    posterior = np.maximum(posterior, 0.002)
    posterior = posterior / posterior.sum(axis=2, keepdims=True)

    n_cells = int((obs_counts.sum(axis=2) > 0).sum())
    mc_weight = mc_equiv_samples / (mc_equiv_samples + total_obs / max(n_cells, 1))
    print(f"  Bayesian: {total_obs} obs across {n_cells} cells, MC weight ≈ {mc_weight:.0%}")

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
    parser.add_argument("--n-sweeps", type=int, default=1,
                        help="Full map sweeps per seed (default: 1). Use 5 to use full 50-query budget.")
    parser.add_argument("--workers", type=int, default=0,
                        help="CPU workers for parallel ABC (default: 0 = all cores)")
    parser.add_argument("--prior-weight", type=float, default=4.0,
                        help="How much to weight contextual prior vs MC (default: 4.0)")
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
        "n_sweeps": args.n_sweeps,
        "from_cache": args.from_cache,
    }, map_width=map_w, map_height=map_h)

    # --- Step 1: Observe ---
    all_obs_multi = None
    if args.from_cache:
        print(f"Loading observations from {args.from_cache}...")
        with open(args.from_cache) as f:
            cache = json.load(f)
        all_observations = {}
        all_obs_multi = {}
        for k, v in cache["seeds"].items():
            sid = int(k)
            # New format: list of sweeps (each sweep is a list of [x, y, c])
            if v and isinstance(v[0], list) and v[0] and isinstance(v[0][0], list):
                sweeps = []
                for sweep_items in v:
                    sweep_obs = {(item[0], item[1]): item[2] for item in sweep_items}
                    sweeps.append(sweep_obs)
                all_obs_multi[sid] = sweeps
                all_observations[sid] = sweeps[0]
            else:
                # Legacy format: flat list of [x, y, c]
                seed_obs = {(item[0], item[1]): item[2] for item in v if len(item) == 3}
                all_observations[sid] = seed_obs
                all_obs_multi[sid] = [seed_obs]
        total_sweeps = sum(len(s) for s in all_obs_multi.values())
        print(f"  Loaded {total_sweeps} sweeps across {len(all_observations)} seeds")
    else:
        # Parse seed grids for smart viewport planning
        initial_states = round_data.get("initial_states", [])
        seed_grids_for_planning = {}
        for i, state in enumerate(initial_states):
            grid = state.get("grid") or state.get("terrain")
            if grid:
                seed_grids_for_planning[i] = grid

        print(f"Step 1: Smart observation allocation across {n_seeds} seeds...")
        try:
            budget = get_budget()
            print(f"  Budget: {budget['queries_used']}/{budget['queries_max']} used")
            available = budget['queries_max'] - budget['queries_used']
            if available <= 0:
                print("  WARNING: Budget exhausted! Use --from-cache.")
                return
        except Exception as e:
            print(f"  Could not check budget: {e}")
            available = 50

        all_observations, all_obs_multi = observe_all_seeds(
            round_id, n_seeds, n_sweeps=args.n_sweeps,
            seed_grids=seed_grids_for_planning,
            total_budget=available,
        )

        # Save ALL sweeps — not just the first one
        cache_file = args.save_cache or f"observations_r{round_num}.json"
        cache_seeds = {}
        for k, sweeps in all_obs_multi.items():
            cache_seeds[str(k)] = [
                [[x, y, c] for (x, y), c in sweep.items()]
                for sweep in sweeps
            ]
        with open(cache_file, "w") as f:
            json.dump({"round_id": round_id, "n_sweeps": n_sweeps, "seeds": cache_seeds}, f)
        print(f"  Saved {n_sweeps} sweeps per seed to {cache_file}")
    print()

    # --- Steps 2–5: Per-seed ABC + MC + Bayesian + Submit ---
    # IMPORTANT: Each seed has a different map — must run ABC+MC independently per seed.
    class_names = ["Empty", "Settle", "Port", "Ruin", "Forest", "Mountain"]

    if all_obs_multi is not None:
        n_sweeps_done = sum(len(s) for s in all_obs_multi.values()) // n_seeds
        effective_mc_equiv = max(10.0, args.mc_equiv / (n_sweeps_done * n_seeds / 5))
    else:
        effective_mc_equiv = args.mc_equiv

    for seed_index in range(n_seeds):
        print(f"\n{'='*50}")
        print(f"Seed {seed_index}/{n_seeds-1}")
        print(f"{'='*50}")

        initial_state = round_data["initial_states"][seed_index]
        grid_list = initial_state["grid"]
        settlements_data = initial_state["settlements"]
        seed_initial_grid = parse_initial_grid(grid_list)

        # Build ABC observations for this seed only
        if all_obs_multi is not None:
            seed_sweeps = all_obs_multi[seed_index]
            abc_observations = {i: sweep for i, sweep in enumerate(seed_sweeps)}
            print(f"  Using {len(seed_sweeps)} sweeps for ABC")
        else:
            abc_observations = {0: all_observations[seed_index]}

        # Step 2: ABC per seed
        print(f"  Step 2: ABC (stage1={args.abc_stage1}, stage2={args.abc_stage2})...")
        t0 = time.time()
        fitted_params = abc_fit_params(
            grid_list, settlements_data, abc_observations,
            n_stage1=args.abc_stage1,
            n_stage2_refine=args.abc_stage2,
            stage2_mc=args.abc_mc,
            top_k=args.abc_top_k,
            seed=42 + seed_index,
            n_workers=args.workers or None,
        )
        abc_elapsed = time.time() - t0
        best_p = fitted_params[0][0]
        print(f"  ABC {abc_elapsed:.1f}s — exp={best_p.expansion_rate:.3f} "
              f"conf={best_p.conflict_prob:.3f} win={best_p.winter_severity:.3f} "
              f"ruin={best_p.ruin_reclaim_rate:.3f}")
        log_action(round_id, "abc_complete", {
            "seed_index": seed_index,
            "elapsed_s": float(round(abc_elapsed, 1)),
            "best_ll": float(round(fitted_params[0][1], 4)),
            "best_params": {
                "expansion_rate": float(round(best_p.expansion_rate, 3)),
                "conflict_prob": float(round(best_p.conflict_prob, 3)),
                "winter_severity": float(round(best_p.winter_severity, 3)),
                "ruin_reclaim_rate": float(round(best_p.ruin_reclaim_rate, 3)),
            },
        }, map_width=map_w, map_height=map_h)

        # Step 3: MC per seed
        print(f"  Step 3: MC ({args.mc_runs} runs)...")
        t0 = time.time()
        mc_prediction = mc_with_fitted_params(
            grid_list, settlements_data, fitted_params,
            total_runs=args.mc_runs, seed=123 + seed_index,
            n_workers=args.workers or None,
        )
        mc_prediction = apply_static_overrides(mc_prediction, seed_initial_grid)
        print(f"  MC {time.time()-t0:.1f}s")

        # Step 4: Contextual prior + blend with MC
        ig_api = np.array(initial_state["grid"])  # raw API values for prior lookup
        round_type = classify_round_type(all_observations[seed_index], ig_api)
        prior_pred = build_prior_prediction(ig_api, round_type)
        print(f"  Round type: {round_type}")

        # Blend: prior provides the baseline, MC refines it
        mc_blended = blend_prior_with_mc(prior_pred, mc_prediction, prior_weight=args.prior_weight)

        # Bayesian correction with real observations on top of blended prediction
        if all_obs_multi is not None:
            bayes_obs = {i: sweep for i, sweep in enumerate(all_obs_multi[seed_index])}
        else:
            bayes_obs = {0: all_observations[seed_index]}

        seed_pred = bayesian_correct(
            mc_blended, bayes_obs,
            mc_equiv_samples=effective_mc_equiv,
            H=map_h, W=map_w,
        )

        # Static overrides for ocean/mountain
        seed_pred[seed_initial_grid == OCEAN, :] = 0.002
        seed_pred[seed_initial_grid == OCEAN, 0] = 0.99
        seed_pred[seed_initial_grid == MOUNTAIN, :] = 0.002
        seed_pred[seed_initial_grid == MOUNTAIN, 5] = 0.99
        seed_pred = seed_pred / seed_pred.sum(axis=2, keepdims=True)

        argmax = seed_pred.argmax(axis=2)
        parts = [f"{class_names[c]}={(argmax==c).sum()}" for c in range(6) if (argmax==c).sum() > 0]
        print(f"  Classes: {', '.join(parts)}")

        log_prediction(round_id, seed_index, seed_pred, map_width=map_w, map_height=map_h)

        # Step 5: Submit
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
