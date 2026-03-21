"""
Astar Island v2 — ABC Parameter Fitting

Key improvements over v1:
  - Comprehensive cold overrides for ALL 8 parameters (not just 2)
  - Expansion rate lower bound covers R3-style cold rounds (0.005 vs 0.05)
  - Uses deterministic RNG seeding (not Python hash())
"""

import math
import random
from concurrent.futures import ProcessPoolExecutor
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from offline.simulator import Simulator, DEFAULT_PARAMS, TERRAIN_TO_CLASS
from run import CLASS_FLOORS

# --- ABC parameter ranges (direct 1:1 mapping to simulator params) ---

ABC_PARAM_RANGES = {
    # Growth
    "expansion_chance":        (0.01, 0.20),
    "expansion_threshold":     (0.5, 2.5),
    "base_food_production":    (0.1, 0.6),
    "population_growth_rate":  (0.03, 0.25),
    # Conflict
    "raid_chance":             (0.05, 0.55),
    "conquest_chance":         (0.02, 0.20),
    # Winter
    "winter_severity_mean":    (0.08, 1.5),
    "winter_food_loss_base":   (0.1, 0.8),
    "collapse_chance_base":    (0.1, 0.7),
    # Trade
    "trade_range":             (3, 14),
    # Environment
    "settlement_reclaim_chance": (0.03, 0.65),
    "ruin_forest_reclaim_chance": (0.01, 0.30),
    # Longships
    "longship_build_chance":   (0.04, 0.45),
    "longship_raid_range":     (4, 17),
}

COLD_OVERRIDES = {
    "expansion_chance":        (0.002, 0.05),
    "expansion_threshold":     (1.0, 3.0),
    "base_food_production":    (0.05, 0.35),
    "population_growth_rate":  (0.02, 0.15),
    "raid_chance":             (0.10, 0.55),
    "conquest_chance":         (0.02, 0.20),
    "winter_severity_mean":    (0.40, 1.5),
    "winter_food_loss_base":   (0.3, 0.8),
    "collapse_chance_base":    (0.3, 0.7),
    "trade_range":             (3, 10),
    "settlement_reclaim_chance": (0.03, 0.30),
    "ruin_forest_reclaim_chance": (0.02, 0.35),
    "longship_build_chance":   (0.02, 0.25),
    "longship_raid_range":     (4, 12),
}

INTEGER_PARAMS = {"trade_range", "longship_raid_range"}


def abc_params_to_sim_params(abc_vec):
    """Direct 1:1 mapping — ABC params ARE simulator params."""
    p = DEFAULT_PARAMS.copy()
    for key, val in abc_vec.items():
        if key in INTEGER_PARAMS:
            p[key] = int(val)
        else:
            p[key] = val
    # Derived params that aren't directly fitted
    p["ruin_plains_reclaim_chance"] = p.get("ruin_forest_reclaim_chance", 0.05) * 1.5
    p["reclaim_resource_fraction"] = min(0.5, p.get("settlement_reclaim_chance", 0.1) * 0.5)
    p["longship_build_threshold"] = max(0.2, 1.0 - p.get("longship_build_chance", 0.1))
    return p


# --- LHS Sampling ---

def latin_hypercube_sample(n, ranges, rng):
    """Generate n Latin Hypercube samples across parameter ranges."""
    param_names = list(ranges.keys())
    k = len(param_names)

    indices = []
    for _ in range(k):
        perm = list(range(n))
        rng.shuffle(perm)
        indices.append(perm)

    samples = []
    for i in range(n):
        sample = {}
        for j, name in enumerate(param_names):
            lo, hi = ranges[name]
            bin_idx = indices[j][i]
            u = rng.random()
            val = lo + (bin_idx + u) / n * (hi - lo)
            if name in INTEGER_PARAMS:
                val = int(round(val))
            sample[name] = val
        samples.append(sample)

    return samples


# --- Scoring workers ---

def _run_sim_get_classes(grid, settlements_data, params, seed, h, w):
    """Run one sim, return flat class grid."""
    sim = Simulator(grid, settlements_data, params=params, seed=seed)
    sim.run()
    cg = sim.get_class_grid()
    return [cg[r][c] for r in range(h) for c in range(w)]


def _deterministic_seed(abc_vec, sim_i, stage="s1"):
    """Deterministic RNG seed (v2 fix: v1 used Python hash() which is randomized)."""
    # Create a stable hash from parameter values
    vals = tuple(round(v * 10000) for v in abc_vec.values() if isinstance(v, float))
    seed = 0
    for v in vals:
        seed = (seed * 31 + int(v)) & 0x7FFFFFFF
    seed = (seed * 31 + sim_i + (1 if stage == "s2" else 0)) & 0x7FFFFFFF
    return seed


def _score_stage1_worker(args):
    """Score one candidate by match rate across all seeds."""
    abc_vec, seed_data_list, n_sims_per_seed = args
    sim_params = abc_params_to_sim_params(abc_vec)

    total_match = 0
    total_obs = 0

    for grid, settlements, obs_counts, h, w in seed_data_list:
        for sim_i in range(n_sims_per_seed):
            seed = _deterministic_seed(abc_vec, sim_i, "s1")
            flat = _run_sim_get_classes(grid, settlements, sim_params, seed, h, w)

            idx = 0
            for r in range(h):
                for c in range(w):
                    n_obs = sum(obs_counts[r][c])
                    if n_obs > 0:
                        obs_argmax = max(range(6), key=lambda k: obs_counts[r][c][k])
                        if flat[idx] == obs_argmax:
                            total_match += 1
                        total_obs += 1
                    idx += 1

    return abc_vec, total_match / max(total_obs, 1)


def _score_stage2_worker(args):
    """Score one candidate by log-likelihood across all seeds."""
    abc_vec, seed_data_list, n_sims = args
    sim_params = abc_params_to_sim_params(abc_vec)

    total_ll = 0.0

    for grid, settlements, obs_counts, h, w in seed_data_list:
        counts = [[0] * 6 for _ in range(h * w)]

        for sim_i in range(n_sims):
            seed = _deterministic_seed(abc_vec, sim_i, "s2")
            flat = _run_sim_get_classes(grid, settlements, sim_params, seed, h, w)
            for idx in range(h * w):
                counts[idx][flat[idx]] += 1

        idx = 0
        for r in range(h):
            for c in range(w):
                n_obs = sum(obs_counts[r][c])
                if n_obs > 0:
                    for k in range(6):
                        if obs_counts[r][c][k] > 0:
                            mc_prob = max(counts[idx][k] / n_sims, CLASS_FLOORS[k])
                            total_ll += obs_counts[r][c][k] * math.log(mc_prob)
                idx += 1

    return abc_vec, total_ll


# --- Perturbation ---

def perturb_candidates(top_candidates, n_perturbations, ranges, rng, sigma=0.1):
    """Generate perturbations of top candidates."""
    perturbed = []
    n_top = len(top_candidates)

    for i in range(n_perturbations):
        base = top_candidates[i % n_top]
        new = {}
        for name, (lo, hi) in ranges.items():
            width = hi - lo
            noise = rng.gauss(0, sigma * width)
            val = base[name] + noise
            val = max(lo, min(hi, val))
            if name in INTEGER_PARAMS:
                val = int(round(val))
            new[name] = val
        perturbed.append(new)

    return perturbed


# --- Main ABC entry point ---

def run_abc_fit(seed_grids, seed_settlements, seed_obs_counts,
                map_h, map_w, is_cold=False, rng_seed=42,
                stage1_candidates=50, stage1_sims=2, stage1_keep=15,
                stage2_perturbations=40, stage2_sims=20, stage2_keep=8,
                print_fn=print):
    """Run two-stage ABC parameter fitting pooled across all seeds.

    Returns: list of (sim_params_dict, log_likelihood) tuples, sorted best-first.
    """
    rng = random.Random(rng_seed)
    n_workers = max(1, os.cpu_count() - 1)

    # Use comprehensive cold overrides (v2 fix: all 8 params, not just 2)
    ranges = dict(ABC_PARAM_RANGES)
    if is_cold:
        ranges.update(COLD_OVERRIDES)

    # Pack seed data for workers
    seed_data_list = []
    for s in sorted(seed_grids.keys()):
        grid = seed_grids[s]
        settlements = seed_settlements.get(s, [])
        obs = seed_obs_counts.get(s)
        if obs is None:
            continue
        seed_data_list.append((grid, settlements, obs, map_h, map_w))

    if not seed_data_list:
        print_fn("  ABC: no observation data, skipping")
        return []

    # --- Stage 1: LHS + match rate ---
    print_fn(f"  ABC Stage 1: {stage1_candidates} candidates × {stage1_sims} sims × {len(seed_data_list)} seeds")
    candidates = latin_hypercube_sample(stage1_candidates, ranges, rng)

    tasks = [(c, seed_data_list, stage1_sims) for c in candidates]
    results = []
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        for abc_vec, score in pool.map(_score_stage1_worker, tasks):
            results.append((abc_vec, score))

    results.sort(key=lambda x: -x[1])
    top_stage1 = [r[0] for r in results[:stage1_keep]]
    print_fn(f"  ABC Stage 1 done: best match={results[0][1]:.3f}, worst kept={results[stage1_keep-1][1]:.3f}")

    # --- Stage 2: Perturbation + log-likelihood ---
    top_for_stage2 = top_stage1[:20]
    perturbations = perturb_candidates(top_for_stage2, stage2_perturbations, ranges, rng)
    stage2_candidates = top_for_stage2 + perturbations

    print_fn(f"  ABC Stage 2: {len(stage2_candidates)} candidates × {stage2_sims} sims × {len(seed_data_list)} seeds")

    tasks = [(c, seed_data_list, stage2_sims) for c in stage2_candidates]
    results2 = []
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        for abc_vec, ll in pool.map(_score_stage2_worker, tasks):
            results2.append((abc_vec, ll))

    results2.sort(key=lambda x: -x[1])
    top_fitted = [(abc_params_to_sim_params(r[0]), r[1]) for r in results2[:stage2_keep]]

    print_fn(f"  ABC Stage 2 done: best LL={results2[0][1]:.1f}, worst kept={results2[stage2_keep-1][1]:.1f}")

    return top_fitted


# --- Weighted MC from fitted params ---

def _mc_worker(args):
    """Worker for weighted MC."""
    grid, settlements_data, params, seed = args
    sim = Simulator(grid, settlements_data, params=params, seed=seed)
    sim.run()
    cg = sim.get_class_grid()
    h = len(cg)
    w = len(cg[0]) if h > 0 else 0
    return [cg[r][c] for r in range(h) for c in range(w)]


def weighted_mc_from_fitted(fitted_params, grid, settlements_data, total_runs=500,
                             base_seed=None, map_h=40, map_w=40):
    """Run weighted MC using fitted parameter sets. Uses unified CLASS_FLOORS."""
    if not fitted_params:
        return None

    n_workers = max(1, os.cpu_count() - 1)

    # Softmax weights from log-likelihoods
    lls = [ll for _, ll in fitted_params]
    max_ll = max(lls)
    exp_lls = [math.exp(ll - max_ll) for ll in lls]
    total_exp = sum(exp_lls)
    weights = [e / total_exp for e in exp_lls]

    # Distribute runs proportionally
    runs_per = [max(1, int(w * total_runs)) for w in weights]
    diff = total_runs - sum(runs_per)
    if diff > 0:
        for i in range(diff):
            runs_per[i % len(runs_per)] += 1
    elif diff < 0:
        for i in range(-diff):
            idx = len(runs_per) - 1 - (i % len(runs_per))
            runs_per[idx] = max(1, runs_per[idx] - 1)

    h, w = map_h, map_w
    tasks = []
    for pi, (params, _) in enumerate(fitted_params):
        for si in range(runs_per[pi]):
            seed = ((base_seed or 0) + pi * 10000 + si) if base_seed is not None else None
            tasks.append((grid, settlements_data, params, seed))

    counts = [[[0] * 6 for _ in range(w)] for _ in range(h)]
    actual_total = len(tasks)

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        for flat in pool.map(_mc_worker, tasks):
            idx = 0
            for r in range(h):
                for c in range(w):
                    counts[r][c][flat[idx]] += 1
                    idx += 1

    # Unified floors
    prediction = [[[0.0] * 6 for _ in range(w)] for _ in range(h)]
    for r in range(h):
        for c in range(w):
            for k in range(6):
                prediction[r][c][k] = max(counts[r][c][k] / actual_total, CLASS_FLOORS[k])
            total = sum(prediction[r][c])
            for k in range(6):
                prediction[r][c][k] /= total

    return prediction
