"""
Simple prior baseline using empirical GT distributions from training data.
Two versions: global averages per terrain code, and neighbor-adjusted.
"""

import json
import numpy as np
from pathlib import Path
from collections import defaultdict
from eval import eval_predict_fn

N_CLASSES = 6
ROUND_DATA_DIR = Path(__file__).parent / "round_data"


def count_neighbors(grid, code):
    mask = (grid == code).astype(np.float32)
    c = np.zeros_like(mask)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            c += np.roll(np.roll(mask, dy, 0), dx, 1)
    return c


def learn_priors(exclude_round=None):
    """Learn empirical GT distributions per (terrain_code, neighbor_bucket)."""
    # Collect: for each (terrain_code, n_settlements_bucket), accumulate GT vectors
    stats = defaultdict(lambda: defaultdict(list))

    for p in sorted(ROUND_DATA_DIR.glob("round_*.json")):
        d = json.loads(p.read_text())
        if exclude_round and d["round_number"] == exclude_round:
            continue
        grid = np.array(d["initial_grid"], dtype=np.int32)
        n_settle = count_neighbors(grid, 1)
        n_ocean = count_neighbors(grid, 10)

        for s in d.get("seeds", []):
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt, dtype=np.float64)

            for code in [0, 1, 2, 3, 4, 5, 10, 11]:
                mask = grid == code
                if not mask.any():
                    continue
                ns = n_settle[mask]
                no = n_ocean[mask]
                gt_vals = gt[mask]

                for j in range(mask.sum()):
                    # Bucket: (terrain, settle_neighbors, is_coast)
                    ns_bucket = min(int(ns[j]), 3)  # 0,1,2,3+
                    is_coast = int(no[j] > 0)
                    key = (code, ns_bucket, is_coast)
                    stats[code][key].append(gt_vals[j])

    # Average into lookup tables
    prior_table = {}
    global_per_code = {}

    for code in stats:
        all_vecs = []
        for key, vecs in stats[code].items():
            avg = np.mean(vecs, axis=0)
            prior_table[key] = avg
            all_vecs.extend(vecs)
        global_per_code[code] = np.mean(all_vecs, axis=0)

    return prior_table, global_per_code


def empirical_prior(initial_grid, seed_index=None, queries=None,
                    prior_table=None, global_per_code=None):
    grid = np.asarray(initial_grid, dtype=np.int32)
    h, w = grid.shape
    pred = np.full((h, w, N_CLASSES), 1.0 / N_CLASSES)

    n_settle = count_neighbors(grid, 1)
    n_ocean = count_neighbors(grid, 10)

    for r in range(h):
        for c in range(w):
            code = grid[r, c]
            ns = min(int(n_settle[r, c]), 3)
            is_coast = int(n_ocean[r, c] > 0)
            key = (code, ns, is_coast)

            if prior_table and key in prior_table:
                pred[r, c] = prior_table[key]
            elif global_per_code and code in global_per_code:
                pred[r, c] = global_per_code[code]

    pred = np.clip(pred, 0.01, None)
    pred = pred / pred.sum(axis=-1, keepdims=True)
    return pred


if __name__ == "__main__":
    from eval import load_all_rounds

    # --- Version 1: Global empirical (no cross-val, uses all data = cheating) ---
    print("=== Empirical prior (all data, NOT cross-validated) ===")
    pt, gpc = learn_priors()
    def pred_all(grid, si, q):
        return empirical_prior(grid, si, q, pt, gpc)
    eval_predict_fn(pred_all)

    # --- Version 2: Leave-one-round-out cross-validation ---
    print("\n=== Empirical prior (leave-one-round-out CV) ===")
    rounds = load_all_rounds()
    from eval import score_prediction
    all_results = []
    for rnd in rounds:
        rn = rnd["round_number"]
        pt_cv, gpc_cv = learn_priors(exclude_round=rn)
        grid = np.array(rnd["initial_grid"], dtype=np.int32)

        seed_scores = []
        for s in rnd.get("seeds", []):
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt, dtype=np.float64)
            pred = empirical_prior(grid, prior_table=pt_cv, global_per_code=gpc_cv)
            seed_scores.append(score_prediction(pred, gt))

        if seed_scores:
            avg = sum(seed_scores) / len(seed_scores)
            actual = rnd.get("round_score")
            seeds_str = " ".join(f"{s:.1f}" for s in seed_scores)
            actual_str = f" (actual: {actual:.1f})" if actual else ""
            print(f"  Round {rn:2d}: {avg:6.2f}  seeds=[{seeds_str}]{actual_str}")
            all_results.append(avg)

    if all_results:
        print(f"\n  CV Mean: {sum(all_results)/len(all_results):.2f}")
