"""
Experiment: Post-hoc spatial smoothing on GBM predictions.

Applies Gaussian smoothing per-class on dynamic cells only (ocean/mountain stay fixed).
Tests various sigma values via LOO CV.
"""

import sys
import time
import numpy as np
from pathlib import Path
from scipy.ndimage import gaussian_filter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from solve import (
    load_v2_data, build_training_arrays, train_models, predict_grid,
    score_prediction, GRID_SIZE, N_CLASSES, PROB_FLOOR,
)


def smooth_prediction(pred, grid, sigma):
    """Apply Gaussian smoothing to prediction on dynamic cells only."""
    pred = np.array(pred, dtype=np.float64)
    grid = np.asarray(grid, dtype=np.int32)

    ocean = grid == 10
    mountain = grid == 5
    static = ocean | mountain

    # Smooth each class channel independently
    smoothed = np.zeros_like(pred)
    for k in range(N_CLASSES):
        smoothed[:, :, k] = gaussian_filter(pred[:, :, k], sigma=sigma)

    # Restore static cells
    smoothed[ocean] = 0.0
    smoothed[ocean, 0] = 1.0
    smoothed[mountain] = 0.0
    smoothed[mountain, 5] = 1.0

    # Floor and renormalize
    smoothed = np.clip(smoothed, PROB_FLOOR, None)
    smoothed = smoothed / smoothed.sum(axis=-1, keepdims=True)
    return smoothed


def main():
    print("=" * 60)
    print("  Experiment: Post-hoc Spatial Smoothing on GBM")
    print("=" * 60)

    samples = load_v2_data()
    rounds = {}
    for s in samples:
        rounds.setdefault(s["round"], []).append(s)
    round_nums = sorted(rounds.keys())
    print(f"Loaded {len(samples)} samples, {len(round_nums)} rounds")

    sigmas = [0.0, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0]
    all_scores = {s: [] for s in sigmas}

    t0 = time.time()
    for fold_i, test_rn in enumerate(round_nums):
        fold_t = time.time()

        train = [s for rn in round_nums if rn != test_rn for s in rounds[rn]]
        X, Y = build_training_arrays(train)
        models = train_models(X, Y)

        test = rounds[test_rn]
        fold_scores = {s: [] for s in sigmas}

        for s in test:
            pred = predict_grid(models, s["grid"], s["ss"], s["st"], s["pa"],
                                settlement_stats=s.get("settlement_stats"))
            for sigma in sigmas:
                if sigma == 0.0:
                    sc = score_prediction(pred, s["gt"])
                else:
                    sm = smooth_prediction(pred, s["grid"], sigma)
                    sc = score_prediction(sm, s["gt"])
                fold_scores[sigma].append(sc)

        for sigma in sigmas:
            all_scores[sigma].append(np.mean(fold_scores[sigma]))

        elapsed = time.time() - fold_t
        eta = elapsed * (len(round_nums) - fold_i - 1)
        raw = np.mean(fold_scores[0.0])
        best_s = max(sigmas, key=lambda s: np.mean(fold_scores[s]))
        best_v = np.mean(fold_scores[best_s])
        print(f"  R{test_rn:2d}: raw={raw:.1f}  best=sigma={best_s} -> {best_v:.1f}  ({elapsed:.0f}s, ETA {eta:.0f}s)")

    print(f"\n{'=' * 60}")
    print(f"  SUMMARY ({time.time()-t0:.0f}s)")
    print(f"{'=' * 60}")

    best_sigma = None
    best_score = -1
    for sigma in sigmas:
        mean = np.mean(all_scores[sigma])
        delta = mean - np.mean(all_scores[0.0])
        marker = ""
        if mean > best_score:
            best_score = mean
            best_sigma = sigma
            marker = " <--"
        print(f"  sigma={sigma:.1f}: {mean:.2f}  (vs raw: {delta:+.2f}){marker}")

    print(f"\n  BEST: sigma={best_sigma} -> {best_score:.2f}")
    print(f"  Improvement: {best_score - np.mean(all_scores[0.0]):+.2f}")

    # Per-round at best sigma
    if best_sigma != 0.0:
        print(f"\n  Per-round at sigma={best_sigma}:")
        for i, rn in enumerate(round_nums):
            raw = all_scores[0.0][i]
            sm = all_scores[best_sigma][i]
            print(f"    R{rn:2d}: raw={raw:.1f}  smooth={sm:.1f}  delta={sm-raw:+.1f}")


if __name__ == "__main__":
    main()
