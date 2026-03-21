"""
Lookup table predictor v2: build from ground truth distributions directly.
Separate tables for seed 0 (mountains static) vs seeds 1-4 (mountains dissolve).
Key features: terrain code, distance to settlement, coast.
"""

import json
import numpy as np
from pathlib import Path
from collections import defaultdict
from scipy.ndimage import distance_transform_edt
from eval import eval_predict_fn, load_all_rounds, score_prediction

ROUND_DATA_DIR = Path(__file__).parent / "round_data"


def compute_features(grid):
    """Precompute spatial features for a 40x40 grid."""
    h, w = grid.shape
    settle_mask = (grid == 1).astype(np.float32)
    ocean_mask = (grid == 10).astype(np.float32)
    forest_mask = (grid == 4).astype(np.float32)

    dist_s = distance_transform_edt(1 - settle_mask) if settle_mask.sum() > 0 else np.full((h, w), 99.0)

    n_ocean = np.zeros((h, w), dtype=np.float32)
    n_settle = np.zeros((h, w), dtype=np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            n_ocean += np.roll(np.roll(ocean_mask, dy, 0), dx, 1)
            n_settle += np.roll(np.roll(settle_mask, dy, 0), dx, 1)

    return dist_s, n_ocean, n_settle


def cell_key(init_code, dist_s, is_coast, n_settle):
    ds = min(int(dist_s), 8)
    ns = min(int(n_settle), 3)
    return (init_code, ds, int(is_coast), ns)


def build_gt_lookup(exclude_round=None, seed_group="all"):
    """Build lookup from ground truth probability distributions.
    seed_group: "seed0", "seed1-4", or "all"
    """
    table = defaultdict(lambda: np.zeros(6, dtype=np.float64))
    counts = defaultdict(int)

    for p in sorted(ROUND_DATA_DIR.glob("round_*.json")):
        d = json.loads(p.read_text())
        if exclude_round and d["round_number"] == exclude_round:
            continue

        grid = np.array(d["initial_grid"], dtype=np.int32)
        h, w = grid.shape
        dist_s, n_ocean, n_settle = compute_features(grid)

        for s in d.get("seeds", []):
            gt = s.get("ground_truth")
            if gt is None:
                continue
            si = s["seed_index"]

            if seed_group == "seed0" and si != 0:
                continue
            if seed_group == "seed1-4" and si == 0:
                continue

            gt = np.array(gt, dtype=np.float64)

            for r in range(h):
                for c in range(w):
                    key = cell_key(grid[r, c], dist_s[r, c],
                                   n_ocean[r, c] > 0, n_settle[r, c])
                    table[key] += gt[r, c]
                    counts[key] += 1

    # Average
    prob_table = {}
    for key in table:
        prob_table[key] = table[key] / counts[key]

    return prob_table


def lookup_predict(initial_grid, seed_index=None, queries=None,
                   table_s0=None, table_s14=None):
    grid = np.asarray(initial_grid, dtype=np.int32)
    h, w = grid.shape
    pred = np.full((h, w, 6), 1.0 / 6.0)

    dist_s, n_ocean, n_settle = compute_features(grid)

    table = table_s0 if seed_index == 0 else table_s14

    for r in range(h):
        for c in range(w):
            key = cell_key(grid[r, c], dist_s[r, c],
                           n_ocean[r, c] > 0, n_settle[r, c])
            if key in table:
                pred[r, c] = table[key]
            else:
                # Fallback: relax n_settle
                for ns_fallback in range(4):
                    key2 = (key[0], key[1], key[2], ns_fallback)
                    if key2 in table:
                        pred[r, c] = table[key2]
                        break

    pred = np.clip(pred, 0.01, None)
    pred = pred / pred.sum(axis=-1, keepdims=True)
    return pred


if __name__ == "__main__":
    rounds = load_all_rounds()

    # --- Non-CV ---
    print("=== GT Lookup (all data, seed-aware, NOT cross-validated) ===")
    t0 = build_gt_lookup(seed_group="seed0")
    t14 = build_gt_lookup(seed_group="seed1-4")
    def pred_all(grid, si, q):
        return lookup_predict(grid, si, q, t0, t14)
    eval_predict_fn(pred_all)

    # --- Leave-one-round-out CV ---
    print("\n=== GT Lookup (leave-one-round-out CV, seed-aware) ===")
    results = []
    for rnd in rounds:
        rn = rnd["round_number"]
        t0_cv = build_gt_lookup(exclude_round=rn, seed_group="seed0")
        t14_cv = build_gt_lookup(exclude_round=rn, seed_group="seed1-4")
        grid = np.array(rnd["initial_grid"], dtype=np.int32)

        seed_scores = []
        for s in rnd.get("seeds", []):
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt, dtype=np.float64)
            si = s["seed_index"]
            pred = lookup_predict(grid, si, None, t0_cv, t14_cv)
            seed_scores.append(score_prediction(pred, gt))

        if seed_scores:
            avg = sum(seed_scores) / len(seed_scores)
            actual = rnd.get("round_score")
            seeds_str = " ".join(f"{s:.1f}" for s in seed_scores)
            actual_str = f" (actual: {actual:.1f})" if actual else ""
            print(f"  Round {rn:2d}: {avg:6.2f}  seeds=[{seeds_str}]{actual_str}")
            results.append(avg)

    if results:
        print(f"\n  CV Mean: {sum(results)/len(results):.2f}")
