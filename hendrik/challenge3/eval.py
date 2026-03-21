"""
Eval harness for Challenge 3: Astar Island.
Scores predictions against ground truth using entropy-weighted KL divergence.

Usage:
    from eval import score_prediction, eval_all_rounds

    # Score a single seed
    s = score_prediction(prediction, ground_truth)  # both 40x40x6 numpy arrays

    # Eval a predict function across all rounds
    results = eval_all_rounds(predict_fn)
    # predict_fn(initial_grid: np.ndarray, queries: list) -> np.ndarray  (40x40x6)
"""

import json
import math
import numpy as np
from pathlib import Path

ROUND_DATA_DIR = Path(__file__).parent / "round_data"
PROB_FLOOR = 0.01


def score_prediction(pred: np.ndarray, gt: np.ndarray) -> float:
    """
    Score a 40x40x6 prediction against ground truth.
    Returns score in [0, 100]. Higher is better.
    """
    pred = np.clip(pred, PROB_FLOOR, None)
    pred = pred / pred.sum(axis=-1, keepdims=True)

    gt_safe = np.clip(gt, 1e-10, None)
    pred_safe = np.clip(pred, 1e-10, None)

    # Per-cell entropy of ground truth
    entropy = -np.sum(gt_safe * np.log(gt_safe), axis=-1)  # (H, W)

    # Per-cell KL(gt || pred)
    kl = np.sum(gt_safe * (np.log(gt_safe) - np.log(pred_safe)), axis=-1)  # (H, W)

    # Entropy-weighted KL
    total_entropy = entropy.sum()
    if total_entropy < 1e-8:
        return 100.0

    weighted_kl = (entropy * kl).sum() / total_entropy
    score = max(0.0, min(100.0, 100.0 * math.exp(-3.0 * weighted_kl)))
    return score


def load_round(round_number: int) -> dict:
    """Load a round JSON file."""
    path = ROUND_DATA_DIR / f"round_{round_number:02d}.json"
    return json.loads(path.read_text())


def load_all_rounds() -> list[dict]:
    """Load all rounds that have ground truth."""
    rounds = []
    for p in sorted(ROUND_DATA_DIR.glob("round_*.json")):
        d = json.loads(p.read_text())
        has_gt = any(s.get("ground_truth") is not None for s in d.get("seeds", []))
        if has_gt:
            rounds.append(d)
    return rounds


def eval_predict_fn(predict_fn, rounds=None, use_queries=False, verbose=True):
    """
    Evaluate a prediction function across rounds.

    predict_fn signature:
        predict_fn(initial_grid: np.ndarray, seed_index: int,
                   queries: list | None) -> np.ndarray  # 40x40x6

    Returns list of dicts with per-seed and per-round scores.
    """
    if rounds is None:
        rounds = load_all_rounds()

    results = []
    for rnd in rounds:
        rn = rnd["round_number"]
        grid = np.array(rnd["initial_grid"], dtype=np.int32)
        queries = rnd.get("queries", []) if use_queries else []

        seed_scores = []
        for seed in rnd.get("seeds", []):
            gt = seed.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt, dtype=np.float64)
            si = seed["seed_index"]

            seed_queries = [q for q in queries if q.get("seed_index") == si]
            pred = predict_fn(grid, si, seed_queries if use_queries else None)
            s = score_prediction(pred, gt)
            seed_scores.append(s)

        if not seed_scores:
            continue

        round_score = sum(seed_scores) / len(seed_scores)
        actual = rnd.get("round_score")

        entry = {
            "round_number": rn,
            "our_score": round_score,
            "actual_score": actual,
            "seed_scores": seed_scores,
            "delta": round_score - actual if actual else None,
        }
        results.append(entry)

        if verbose:
            seeds_str = " ".join(f"{s:.1f}" for s in seed_scores)
            actual_str = f" (actual: {actual:.1f})" if actual else ""
            print(f"  Round {rn:2d}: {round_score:6.2f}  seeds=[{seeds_str}]{actual_str}")

    if verbose and results:
        avg = sum(r["our_score"] for r in results) / len(results)
        scored = [r for r in results if r["actual_score"] is not None]
        print(f"\n  Mean: {avg:.2f} across {len(results)} rounds")
        if scored:
            avg_actual = sum(r["actual_score"] for r in scored) / len(scored)
            avg_delta = sum(r["delta"] for r in scored) / len(scored)
            print(f"  Mean actual: {avg_actual:.2f}, mean delta: {avg_delta:+.2f}")

    return results


# --- Quick sanity: uniform baseline ---
if __name__ == "__main__":
    def uniform_baseline(grid, seed_index, queries):
        return np.full((40, 40, 6), 1.0 / 6.0)

    print("Uniform baseline (1/6 everywhere):")
    eval_predict_fn(uniform_baseline)
