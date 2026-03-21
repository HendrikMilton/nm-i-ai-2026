"""
Astar Island v2 — Scoring with unified floors.

Uses CLASS_FLOORS consistently in KL computation (v2 fix: v1 used 1e-10).
"""

import math
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from run import CLASS_FLOORS


def kl_divergence(p, q):
    """KL(p || q) using CLASS_FLOORS as minimum for q (not 1e-10)."""
    total = 0.0
    for i, (pi, qi) in enumerate(zip(p, q)):
        if pi > 0:
            qi_floor = max(qi, CLASS_FLOORS[i])
            total += pi * math.log(pi / qi_floor)
    return total


def cell_entropy(p):
    """Shannon entropy of a probability vector."""
    return -sum(pi * math.log(pi) for pi in p if pi > 0)


def score_prediction(prediction, ground_truth):
    """Score a prediction tensor against ground truth.

    Returns dict with score, weighted_kl, scored_cells, worst_cells.
    """
    h = len(ground_truth)
    w = len(ground_truth[0])

    total_kl = 0.0
    total_entropy = 0.0
    scored_cells = 0
    worst_cells = []

    for r in range(h):
        for c in range(w):
            gt = ground_truth[r][c]
            pred = prediction[r][c]
            ent = cell_entropy(gt)

            if ent < 0.01:
                continue

            kl = kl_divergence(gt, pred)
            total_kl += ent * kl
            total_entropy += ent
            scored_cells += 1
            worst_cells.append((r, c, ent * kl, kl, ent))

    weighted_kl = total_kl / total_entropy if total_entropy > 0 else 0
    score = max(0.0, min(100.0, 100.0 * math.exp(-3 * weighted_kl)))

    worst_cells.sort(key=lambda x: -x[2])

    return {
        "score": round(score, 4),
        "weighted_kl": round(weighted_kl, 6),
        "scored_cells": scored_cells,
        "total_cells": h * w,
        "worst_cells": worst_cells[:20],
    }


def score_all_seeds(predictions, ground_truths):
    """Score predictions for multiple seeds."""
    seed_results = {}
    scores = []

    for seed_idx in sorted(predictions.keys()):
        if seed_idx not in ground_truths:
            continue
        result = score_prediction(predictions[seed_idx], ground_truths[seed_idx])
        seed_results[seed_idx] = result
        scores.append(result["score"])

    avg = sum(scores) / len(scores) if scores else 0

    return {
        "round_score": round(avg, 4),
        "seed_scores": {k: v["score"] for k, v in seed_results.items()},
        "seed_details": seed_results,
    }
