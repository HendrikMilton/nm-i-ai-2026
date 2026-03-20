"""
Scoring utility — compute Astar Island scores locally.

Can score against:
  1. Real ground truth from the analysis API (completed rounds)
  2. Simulator-generated ground truth (offline testing)
"""

import math


def kl_divergence(p, q):
    """KL(p || q) for single cell probability vectors."""
    return sum(pi * math.log(pi / max(qi, 1e-10)) for pi, qi in zip(p, q) if pi > 0)


def cell_entropy(p):
    """Shannon entropy of a probability vector."""
    return -sum(pi * math.log(pi) for pi in p if pi > 0)


def score_prediction(prediction, ground_truth):
    """Score a prediction tensor against ground truth.

    Args:
        prediction: H x W x 6 probability tensor
        ground_truth: H x W x 6 probability tensor

    Returns:
        dict with score, weighted_kl, scored_cells, per_cell details
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
    """Score predictions for multiple seeds.

    Args:
        predictions: dict of seed_index -> H x W x 6 tensor
        ground_truths: dict of seed_index -> H x W x 6 tensor

    Returns:
        dict with per-seed scores and round average
    """
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


if __name__ == "__main__":
    # Quick test: score priors against Round 4
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from utils import get_round, get_analysis, floor_and_normalize
    from run import TERRAIN_PRIORS, parse_initial_grid, extract_map_dimensions

    round_id = "8e839974-b13b-407b-a5e7-fc749d877195"
    rd = get_round(round_id)
    map_w, map_h = extract_map_dimensions(rd)

    predictions = {}
    ground_truths = {}

    for seed in range(5):
        analysis = get_analysis(round_id, seed)
        ground_truths[seed] = analysis["ground_truth"]
        ig = analysis["initial_grid"]

        pred = []
        for r in range(map_h):
            row = []
            for c in range(map_w):
                prior = list(TERRAIN_PRIORS.get(ig[r][c], [1/6]*6))
                row.append(prior)
            pred.append(row)
        pred = floor_and_normalize(pred)
        predictions[seed] = pred

    results = score_all_seeds(predictions, ground_truths)
    print(f"Round score: {results['round_score']}")
    for seed, score in results["seed_scores"].items():
        print(f"  Seed {seed}: {score}")
