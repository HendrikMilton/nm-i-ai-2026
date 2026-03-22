"""
Validate combined approaches on R22 (trained R1-R21):
1. Our V3 GBM baseline
2. V3 + Bayesian Dirichlet observation update (Elias's approach)
3. V3 + ABC simulator blend + Bayesian obs
4. Sweep equiv_samples for Bayesian update

All methods use V3 checkpoints (trained R1-R21).
"""

import json, sys, os, time, math
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent / "elias" / "astar"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent / "elias" / "astar" / "offline"))

import solve
import importlib
importlib.reload(solve)
from solve import (predict_grid, score_prediction, _load_distance_priors,
    GRID_SIZE, N_CLASSES, CLASS_FLOORS)

from simulator import Simulator, DEFAULT_PARAMS
import importlib
_abc_mod = importlib.import_module("offline.abc")
run_abc_fit = _abc_mod.run_abc_fit
weighted_mc_from_fitted = _abc_mod.weighted_mc_from_fitted
abc_params_to_sim_params = _abc_mod.abc_params_to_sim_params

LOG_FILE = Path(__file__).parent / "combined_results.txt"

def log(msg):
    print(msg, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(msg + "\n")


def bayesian_dirichlet_update(prior_pred, obs_counts, equiv_samples):
    """Bayesian Dirichlet update: prior as pseudo-counts, obs as real counts.

    prior_pred: (40, 40, 6) model prediction (probabilities)
    obs_counts: (40, 40, 6) observation counts per class
    equiv_samples: how much to trust the prior (higher = trust prior more)
    """
    h, w = prior_pred.shape[:2]
    result = prior_pred.copy()

    for r in range(h):
        for c in range(w):
            n_obs = obs_counts[r, c].sum()
            if n_obs == 0:
                continue
            # Dirichlet: alpha_k = prior_k * equiv_samples + obs_count_k
            alpha = prior_pred[r, c] * equiv_samples + obs_counts[r, c]
            total = alpha.sum()
            if total > 0:
                result[r, c] = alpha / total

    # Re-floor and normalize
    for k in range(N_CLASSES):
        result[:, :, k] = np.clip(result[:, :, k], CLASS_FLOORS[k], None)
    result = result / result.sum(axis=-1, keepdims=True)
    return result


def _run_one_sim(args):
    """Top-level worker for ProcessPoolExecutor."""
    g, s, p, seed = args
    sim = Simulator(g, s, params=p, seed=seed)
    sim.run()
    cg = sim.get_class_grid()
    return [cg[r][c] for r in range(len(cg)) for c in range(len(cg[0]))]


def run_simulator_mc_simple(grid, settlements, n_sims=30, base_seed=42):
    """Simple MC with default params. Returns (40, 40, 6)."""
    from concurrent.futures import ProcessPoolExecutor

    h, w = len(grid), len(grid[0])
    tasks = [(grid, settlements, DEFAULT_PARAMS, base_seed + i) for i in range(n_sims)]
    counts = np.zeros((h, w, 6), dtype=np.int32)

    with ProcessPoolExecutor(max_workers=min(n_sims, 7)) as pool:
        for flat in pool.map(_run_one_sim, tasks):
            idx = 0
            for r in range(h):
                for c in range(w):
                    counts[r, c, flat[idx]] += 1
                    idx += 1

    probs = counts.astype(np.float64) / n_sims
    for k in range(6):
        probs[:, :, k] = np.clip(probs[:, :, k], CLASS_FLOORS[k], None)
    return probs / probs.sum(axis=-1, keepdims=True)


def extract_settlements_from_grid(grid):
    settlements = []
    oid = 0
    for r in range(len(grid)):
        for c in range(len(grid[0])):
            if grid[r][c] in (1, 2):
                settlements.append({"x": c, "y": r, "has_port": grid[r][c] == 2, "owner_id": oid})
                oid += 1
    return settlements


def obs_probs_to_counts(obs_probs, n_obs):
    """Convert observed_probs + n_observations to observation counts per class."""
    h, w = obs_probs.shape[:2]
    counts = np.zeros((h, w, 6), dtype=np.float32)
    for r in range(h):
        for c in range(w):
            n = n_obs[r, c]
            if n > 0:
                counts[r, c] = obs_probs[r, c] * n
    return counts


def main():
    with open(LOG_FILE, "w") as f:
        f.write("")

    log("=" * 70)
    log("  Combined Approach Validation on R22")
    log("=" * 70)

    # Load models
    solve._ensure_models()
    models = solve._models

    # Load R22 data
    rd = json.load(open(Path(__file__).parent.parent.parent / "round_data" / "round_22.json"))
    sd = json.load(open(Path(__file__).parent.parent.parent / "round_data" / "round_22_submit.json"))
    seeds_gt = rd["seeds"]
    submit_seeds = sd["seeds"]
    actual = [80.2266, 78.4341, 81.6399, 81.3289, 81.5912]

    log(f"  Actual live: 80.64  seeds={actual}")

    # ============================================================
    # Method 1: V3 baseline (no obs)
    # ============================================================
    log(f"\n--- Method 1: V3 GBM baseline ---")
    scores_v3 = []
    preds_v3 = {}
    for sid in range(5):
        sub = submit_seeds[str(sid)]
        grid = np.array(sub["initial_grid"], dtype=np.int32)
        ss = sub.get("settlement_stats")
        gt = np.array(seeds_gt[sid]["ground_truth"])
        pred = predict_grid(models, grid, settlement_stats=ss)
        preds_v3[sid] = pred
        scores_v3.append(score_prediction(pred, gt))
    log(f"  Mean: {np.mean(scores_v3):.2f}  seeds=[{' '.join(f'{s:.1f}' for s in scores_v3)}]")

    # ============================================================
    # Method 2: V3 + Bayesian Dirichlet update (sweep equiv_samples)
    # ============================================================
    log(f"\n--- Method 2: V3 + Bayesian Dirichlet obs update ---")
    for equiv in [5, 10, 15, 20, 30, 50, 75, 100]:
        scores = []
        for sid in range(5):
            sub = submit_seeds[str(sid)]
            gt = np.array(seeds_gt[sid]["ground_truth"])
            obs_probs = np.array(sub.get("observed_probs", []), dtype=np.float32)
            n_obs = np.array(sub.get("n_observations", []), dtype=np.float32)

            if obs_probs.size == 0:
                scores.append(scores_v3[sid])
                continue

            obs_counts = obs_probs_to_counts(obs_probs, n_obs)
            updated = bayesian_dirichlet_update(preds_v3[sid], obs_counts, equiv)

            # Static overrides
            grid = np.array(sub["initial_grid"], dtype=np.int32)
            ocean = grid == 10; mountain = grid == 5
            if ocean.any(): updated[ocean] = 0.0; updated[ocean, 0] = 1.0
            if mountain.any(): updated[mountain] = 0.0; updated[mountain, 5] = 1.0
            updated = np.clip(updated, 0.001, None)
            updated = updated / updated.sum(axis=-1, keepdims=True)

            scores.append(score_prediction(updated, gt))

        mean = np.mean(scores)
        delta = mean - np.mean(scores_v3)
        log(f"  equiv={equiv:3d}: {mean:.2f}  delta={delta:+.2f}  seeds=[{' '.join(f'{s:.1f}' for s in scores)}]")

    # ============================================================
    # Method 3: V3 + MC sim blend + Bayesian obs (Elias-style 3-layer)
    # ============================================================
    log(f"\n--- Method 3: V3 + MC sim (default params) + Bayesian obs ---")
    log(f"  Running 30 MC sims per seed...")

    mc_preds = {}
    t0 = time.time()
    for sid in range(5):
        sub = submit_seeds[str(sid)]
        grid_list = sub["initial_grid"]
        settlements = extract_settlements_from_grid(grid_list)
        mc_pred = run_simulator_mc_simple(grid_list, settlements, n_sims=30, base_seed=sid * 1000)
        mc_preds[sid] = mc_pred
        log(f"    Seed {sid}: MC done ({time.time()-t0:.0f}s)")

    # Try different blending: alpha * MC + (1-alpha) * GBM, then Bayesian obs
    for mc_weight in [0.0, 0.1, 0.2, 0.3]:
        for equiv in [15, 20, 30]:
            scores = []
            for sid in range(5):
                sub = submit_seeds[str(sid)]
                grid = np.array(sub["initial_grid"], dtype=np.int32)
                gt = np.array(seeds_gt[sid]["ground_truth"])
                obs_probs = np.array(sub.get("observed_probs", []), dtype=np.float32)
                n_obs = np.array(sub.get("n_observations", []), dtype=np.float32)

                # Layer 1+2: blend GBM + MC
                blended = (1 - mc_weight) * preds_v3[sid] + mc_weight * mc_preds[sid]
                blended = np.clip(blended, 0.001, None)
                blended = blended / blended.sum(axis=-1, keepdims=True)

                # Layer 3: Bayesian obs update
                if obs_probs.size > 0:
                    obs_counts = obs_probs_to_counts(obs_probs, n_obs)
                    blended = bayesian_dirichlet_update(blended, obs_counts, equiv)

                ocean = grid == 10; mountain = grid == 5
                if ocean.any(): blended[ocean] = 0.0; blended[ocean, 0] = 1.0
                if mountain.any(): blended[mountain] = 0.0; blended[mountain, 5] = 1.0
                blended = np.clip(blended, 0.001, None)
                blended = blended / blended.sum(axis=-1, keepdims=True)

                scores.append(score_prediction(blended, gt))

            mean = np.mean(scores)
            delta = mean - np.mean(scores_v3)
            log(f"  mc={mc_weight:.1f} equiv={equiv:2d}: {mean:.2f}  delta={delta:+.2f}  seeds=[{' '.join(f'{s:.1f}' for s in scores)}]")

    log(f"\n  V3 baseline: {np.mean(scores_v3):.2f}")
    log(f"  Actual live: 80.64")


if __name__ == "__main__":
    main()
