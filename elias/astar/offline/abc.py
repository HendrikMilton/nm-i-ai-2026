"""
Astar Island — ABC (Approximate Bayesian Computation) Parameter Fitting

Two-stage ABC that pools observations across all 5 seeds to fit the 8 key
hidden parameters of the simulator. Produces weighted parameter sets for
Monte Carlo prediction.
"""

import math
import random
from concurrent.futures import ProcessPoolExecutor
import os

from offline.simulator import Simulator, DEFAULT_PARAMS, TERRAIN_TO_CLASS

# --- ABC parameter ranges ---

ABC_PARAM_RANGES = {
    "expansion_rate":      (0.05, 0.65),
    "conflict_prob":       (0.05, 0.55),
    "winter_severity":     (0.08, 0.75),
    "trade_range":         (3, 14),
    "ruin_reclaim_rate":   (0.08, 0.65),
    "forest_reclaim_rate": (0.01, 0.30),
    "longship_prob":       (0.04, 0.45),
    "longship_range":      (4, 17),
}

COLD_OVERRIDES = {
    "expansion_rate":  (0.01, 0.15),
    "winter_severity": (0.40, 0.75),
}

INTEGER_PARAMS = {"trade_range", "longship_range"}


def abc_params_to_sim_params(abc_vec):
    """Map 8 ABC parameters to full simulator params dict."""
    p = DEFAULT_PARAMS.copy()

    er = abc_vec["expansion_rate"]
    p["expansion_chance"] = er * 0.15
    p["expansion_threshold"] = max(0.5, 2.0 - er)

    cp = abc_vec["conflict_prob"]
    p["raid_chance"] = cp
    p["conquest_chance"] = cp * 0.25

    ws = abc_vec["winter_severity"]
    p["winter_severity_mean"] = ws
    p["collapse_chance_base"] = ws * 0.5

    p["trade_range"] = int(abc_vec["trade_range"])

    rr = abc_vec["ruin_reclaim_rate"]
    p["settlement_reclaim_chance"] = rr
    p["reclaim_resource_fraction"] = min(0.5, rr * 0.5)

    fr = abc_vec["forest_reclaim_rate"]
    p["ruin_forest_reclaim_chance"] = fr
    p["ruin_plains_reclaim_chance"] = fr * 1.5

    lp = abc_vec["longship_prob"]
    p["longship_build_chance"] = lp
    p["longship_build_threshold"] = max(0.2, 1.0 - lp)

    p["longship_raid_range"] = int(abc_vec["longship_range"])

    return p


# --- LHS Sampling ---

def latin_hypercube_sample(n, ranges, rng):
    """Generate n Latin Hypercube samples across parameter ranges."""
    param_names = list(ranges.keys())
    k = len(param_names)

    # Create permuted indices for each dimension
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
            # Sample uniformly within bin
            bin_idx = indices[j][i]
            u = rng.random()
            val = lo + (bin_idx + u) / n * (hi - lo)
            if name in INTEGER_PARAMS:
                val = int(round(val))
            sample[name] = val
        samples.append(sample)

    return samples


# --- Scoring workers (module-level for pickling) ---

def _run_sim_get_classes(grid, settlements_data, params, seed, h, w):
    """Run one sim, return flat class grid."""
    sim = Simulator(grid, settlements_data, params=params, seed=seed)
    sim.run()
    cg = sim.get_class_grid()
    return [cg[r][c] for r in range(h) for c in range(w)]


def _score_stage1_worker(args):
    """Score one candidate by match rate across all seeds."""
    abc_vec, seed_data_list, n_sims_per_seed = args
    sim_params = abc_params_to_sim_params(abc_vec)

    total_match = 0
    total_obs = 0

    for grid, settlements, obs_counts, h, w in seed_data_list:
        for sim_i in range(n_sims_per_seed):
            seed = hash((str(abc_vec), sim_i)) & 0x7FFFFFFF
            flat = _run_sim_get_classes(grid, settlements, sim_params, seed, h, w)

            idx = 0
            for r in range(h):
                for c in range(w):
                    n_obs = sum(obs_counts[r][c])
                    if n_obs > 0:
                        obs_argmax = max(range(6), key=lambda k: obs_counts[r][c][k])
                        sim_class = flat[idx]
                        if sim_class == obs_argmax:
                            total_match += 1
                        total_obs += 1
                    idx += 1

    match_rate = total_match / max(total_obs, 1)
    return abc_vec, match_rate


def _score_stage2_worker(args):
    """Score one candidate by log-likelihood across all seeds."""
    abc_vec, seed_data_list, n_sims = args
    sim_params = abc_params_to_sim_params(abc_vec)

    total_ll = 0.0

    for grid, settlements, obs_counts, h, w in seed_data_list:
        # Run MC to get probability distribution
        counts = [[0] * 6 for _ in range(h * w)]

        for sim_i in range(n_sims):
            seed = hash((str(abc_vec), "s2", sim_i)) & 0x7FFFFFFF
            flat = _run_sim_get_classes(grid, settlements, sim_params, seed, h, w)
            for idx in range(h * w):
                counts[idx][flat[idx]] += 1

        # Compute log-likelihood of observations
        idx = 0
        for r in range(h):
            for c in range(w):
                n_obs = sum(obs_counts[r][c])
                if n_obs > 0:
                    for k in range(6):
                        if obs_counts[r][c][k] > 0:
                            # MC probability for class k
                            mc_prob = max(counts[idx][k] / n_sims, 0.001)
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
                stage1_candidates=500, stage1_sims=2, stage1_keep=50,
                stage2_perturbations=180, stage2_sims=50, stage2_keep=15,
                print_fn=print):
    """Run two-stage ABC parameter fitting pooled across all seeds.

    Returns: list of (sim_params_dict, log_likelihood) tuples, sorted best-first.
    """
    rng = random.Random(rng_seed)
    n_workers = max(1, os.cpu_count() - 1)

    # Build ranges (narrow for cold rounds)
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


def _mc_worker(args):
    """Worker for weighted MC. Returns flat class grid."""
    grid, settlements_data, params, seed = args
    sim = Simulator(grid, settlements_data, params=params, seed=seed)
    sim.run()
    cg = sim.get_class_grid()
    h = len(cg)
    w = len(cg[0]) if h > 0 else 0
    return [cg[r][c] for r in range(h) for c in range(w)]


# --- Weighted MC ---

def weighted_mc_from_fitted(fitted_params, grid, settlements_data, total_runs=500,
                             base_seed=None, map_h=40, map_w=40):
    """Run weighted MC using fitted parameter sets.

    Args:
        fitted_params: list of (sim_params_dict, log_likelihood) from run_abc_fit
        total_runs: total simulations to distribute across param sets

    Returns: H x W x 6 probability tensor as nested lists
    """
    if not fitted_params:
        return None

    n_workers = max(1, os.cpu_count() - 1)

    # Compute softmax weights from log-likelihoods
    lls = [ll for _, ll in fitted_params]
    max_ll = max(lls)
    exp_lls = [math.exp(ll - max_ll) for ll in lls]
    total_exp = sum(exp_lls)
    weights = [e / total_exp for e in exp_lls]

    # Distribute runs proportionally (at least 1 per param set)
    runs_per = [max(1, int(w * total_runs)) for w in weights]
    # Adjust to match total
    diff = total_runs - sum(runs_per)
    if diff > 0:
        # Add remaining to highest-weight param sets
        for i in range(diff):
            runs_per[i % len(runs_per)] += 1
    elif diff < 0:
        # Remove from lowest-weight param sets
        for i in range(-diff):
            idx = len(runs_per) - 1 - (i % len(runs_per))
            runs_per[idx] = max(1, runs_per[idx] - 1)

    # Build all sim tasks
    h, w = map_h, map_w
    tasks = []
    for pi, (params, _) in enumerate(fitted_params):
        for si in range(runs_per[pi]):
            seed = ((base_seed or 0) + pi * 10000 + si) if base_seed is not None else None
            tasks.append((grid, settlements_data, params, seed))

    # Run all sims in parallel
    counts = [[[0] * 6 for _ in range(w)] for _ in range(h)]
    actual_total = len(tasks)

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        for flat in pool.map(_mc_worker, tasks):
            idx = 0
            for r in range(h):
                for c in range(w):
                    counts[r][c][flat[idx]] += 1
                    idx += 1

    # Convert to probabilities
    class_floors = [0.005, 0.005, 0.001, 0.002, 0.005, 0.001]
    prediction = [[[0.0] * 6 for _ in range(w)] for _ in range(h)]
    for r in range(h):
        for c in range(w):
            for k in range(6):
                prediction[r][c][k] = max(counts[r][c][k] / actual_total, class_floors[k])
            total = sum(prediction[r][c])
            for k in range(6):
                prediction[r][c][k] /= total

    return prediction
