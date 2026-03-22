"""
Experiment 3: Blend Elias's simulator MC predictions with our LightGBM predictions.

For each round/seed with GT:
  1. GBM prediction via solve.py
  2. Simulator MC prediction via Elias's simulator
  3. Blend: final = alpha * sim + (1-alpha) * gbm
  4. Score all three + blend at various alphas
"""

import json
import math
import sys
import os
import time
import numpy as np
from pathlib import Path

# Add paths
CHALLENGE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(CHALLENGE_DIR))
sys.path.insert(0, str(CHALLENGE_DIR / "../../elias/astar"))
sys.path.insert(0, str(CHALLENGE_DIR / "../../elias/astar/offline"))

from solve import (
    load_v2_data, build_training_arrays, train_models, predict_grid,
    score_prediction, GRID_SIZE, N_CLASSES, PROB_FLOOR,
    compute_hidden_params, LGB_PARAMS,
)
from simulator import Simulator, DEFAULT_PARAMS, TERRAIN_TO_CLASS as SIM_TERRAIN_TO_CLASS


# ============================================================
# Helpers
# ============================================================

def extract_settlements_from_grid(grid):
    """Extract settlement positions from initial grid for the simulator."""
    settlements = []
    owner_id = 0
    for r in range(len(grid)):
        for c in range(len(grid[0])):
            cell = grid[r][c]
            if cell == 1:  # settlement
                settlements.append({"x": c, "y": r, "has_port": False, "owner_id": owner_id})
                owner_id += 1
            elif cell == 2:  # port
                settlements.append({"x": c, "y": r, "has_port": True, "owner_id": owner_id})
                owner_id += 1
    return settlements


def run_simulator_mc(grid_list, settlements, n_sims=200, params=None, base_seed=42):
    """Run Monte Carlo simulations and average to get probability predictions.

    Args:
        grid_list: 2D list of terrain codes
        settlements: list of settlement dicts for Simulator
        n_sims: number of MC runs
        params: simulator params dict (defaults to DEFAULT_PARAMS)
        base_seed: RNG seed base

    Returns:
        np.ndarray of shape (H, W, 6) with class probabilities
    """
    params = params or DEFAULT_PARAMS
    h = len(grid_list)
    w = len(grid_list[0])

    counts = np.zeros((h, w, 6), dtype=np.int32)

    for i in range(n_sims):
        seed = base_seed + i
        sim = Simulator(grid_list, settlements, params=params, seed=seed)
        sim.run()
        cg = sim.get_class_grid()
        for r in range(h):
            for c in range(w):
                counts[r, c, cg[r][c]] += 1

    # Convert to probabilities with floor
    probs = counts.astype(np.float64) / n_sims
    probs = np.clip(probs, PROB_FLOOR, None)
    probs = probs / probs.sum(axis=-1, keepdims=True)
    return probs


def blend_predictions(pred_a, pred_b, alpha):
    """Blend: result = alpha * pred_a + (1-alpha) * pred_b"""
    result = alpha * pred_a + (1.0 - alpha) * pred_b
    result = np.clip(result, PROB_FLOOR, None)
    result = result / result.sum(axis=-1, keepdims=True)
    return result


# ============================================================
# Main evaluation
# ============================================================

def main():
    print("=" * 60)
    print("  Experiment 3: Simulator-GBM Blend")
    print("=" * 60)

    # Load all training data
    all_samples = load_v2_data()
    if not all_samples:
        print("ERROR: No training data found!")
        return

    # Group by round
    rounds = {}
    for s in all_samples:
        rounds.setdefault(s["round"], []).append(s)
    round_nums = sorted(rounds.keys())
    print(f"\nLoaded {len(all_samples)} samples across {len(round_nums)} rounds: {round_nums}")

    # Alphas to test
    alphas = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

    # LOO cross-validation: for each round, train GBM on others, predict, blend
    all_gbm_scores = []
    all_sim_scores = []
    all_blend_scores = {a: [] for a in alphas}

    n_sims = 30  # MC sims per seed (30 is enough for stable averages)

    total_start = time.time()

    for fold_i, test_rn in enumerate(round_nums):
        fold_start = time.time()
        print(f"\n--- Round {test_rn} (fold {fold_i+1}/{len(round_nums)}) ---")

        # Train GBM on all other rounds
        train_samples = [s for rn in round_nums if rn != test_rn for s in rounds[rn]]
        X_train, Y_train = build_training_arrays(train_samples)
        print(f"  Training GBM on {len(train_samples)} samples ({X_train.shape[0]} cells)...")
        models = train_models(X_train, Y_train)

        test_samples = rounds[test_rn]
        seed_gbm = []
        seed_sim = []
        seed_blend = {a: [] for a in alphas}

        for s in test_samples:
            grid = s["grid"]
            gt = s["gt"]

            # GBM prediction (with GT-derived hidden params for fair comparison)
            gbm_pred = predict_grid(models, grid, s["ss"], s["st"], s["pa"],
                                     settlement_stats=s.get("settlement_stats"))
            gbm_score = score_prediction(gbm_pred, gt)
            seed_gbm.append(gbm_score)

            # Simulator MC prediction
            grid_list = grid.tolist()
            settlements = extract_settlements_from_grid(grid_list)
            sim_pred = run_simulator_mc(grid_list, settlements, n_sims=n_sims,
                                         base_seed=test_rn * 1000 + s["seed"])
            sim_score = score_prediction(sim_pred, gt)
            seed_sim.append(sim_score)

            # Blend at various alphas
            for alpha in alphas:
                blended = blend_predictions(sim_pred, gbm_pred, alpha)
                blend_score = score_prediction(blended, gt)
                seed_blend[alpha].append(blend_score)

        mean_gbm = np.mean(seed_gbm)
        mean_sim = np.mean(seed_sim)
        all_gbm_scores.append(mean_gbm)
        all_sim_scores.append(mean_sim)

        best_alpha = max(alphas, key=lambda a: np.mean(seed_blend[a]))
        best_blend = np.mean(seed_blend[best_alpha])

        for a in alphas:
            all_blend_scores[a].append(np.mean(seed_blend[a]))

        elapsed = time.time() - fold_start
        print(f"  GBM:  {mean_gbm:.2f}")
        print(f"  Sim:  {mean_sim:.2f}")
        print(f"  Best blend: alpha={best_alpha:.2f} -> {best_blend:.2f}")
        print(f"  ({elapsed:.0f}s)")

    # Summary
    total_elapsed = time.time() - total_start
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY ({total_elapsed:.0f}s total)")
    print(f"{'=' * 60}")

    mean_gbm_overall = np.mean(all_gbm_scores)
    mean_sim_overall = np.mean(all_sim_scores)

    print(f"\n  GBM alone:       {mean_gbm_overall:.2f}")
    print(f"  Simulator alone: {mean_sim_overall:.2f}")
    print(f"\n  Alpha sweep (sim weight -> score):")

    best_overall_alpha = None
    best_overall_score = -1
    for a in alphas:
        mean_blend = np.mean(all_blend_scores[a])
        delta_vs_gbm = mean_blend - mean_gbm_overall
        marker = ""
        if mean_blend > best_overall_score:
            best_overall_score = mean_blend
            best_overall_alpha = a
            marker = " <--"
        print(f"    alpha={a:.2f}: {mean_blend:.2f}  (vs GBM: {delta_vs_gbm:+.2f}){marker}")

    print(f"\n  BEST: alpha={best_overall_alpha:.2f} -> {best_overall_score:.2f}")
    print(f"  Improvement over GBM: {best_overall_score - mean_gbm_overall:+.2f}")

    # Per-round detail
    print(f"\n  Per-round at best alpha ({best_overall_alpha:.2f}):")
    for i, rn in enumerate(round_nums):
        gbm = all_gbm_scores[i]
        sim = all_sim_scores[i]
        blend = all_blend_scores[best_overall_alpha][i]
        delta = blend - gbm
        print(f"    R{rn:2d}: GBM={gbm:.1f}  Sim={sim:.1f}  Blend={blend:.1f}  delta={delta:+.1f}")


if __name__ == "__main__":
    main()
