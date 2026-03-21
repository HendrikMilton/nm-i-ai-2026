"""
Add to each seed in round_data:
  - query_results: 40x40 int grid per observation (list of full grids, unobserved = -1)
  - ground_truth_from_queries: 40x40x6 probability distribution built from all observations
"""

import json
import numpy as np
from pathlib import Path

ROUND_DATA_DIR = Path(__file__).parent / "round_data"
CODE_TO_CLASS = {0: 0, 11: 0, 10: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}


def process_round(rpath):
    d = json.loads(rpath.read_text())
    h, w = 40, 40
    changed = False

    for seed in d.get("seeds", []):
        raw_obs = seed.get("raw_observations")
        if not raw_obs:
            continue

        # --- query_results: one 40x40 grid per observation ---
        query_grids = []
        for obs in raw_obs:
            vp = obs["viewport"]
            vx, vy, vw, vh = vp["x"], vp["y"], vp["w"], vp["h"]
            obs_grid = np.array(obs["grid"], dtype=np.int32)

            full = np.full((h, w), -1, dtype=np.int32)
            for lr in range(vh):
                for lc in range(vw):
                    gr, gc = vy + lr, vx + lc
                    if gr < h and gc < w:
                        full[gr, gc] = int(obs_grid[lr, lc])
            query_grids.append(full.tolist())

        # --- ground_truth_from_queries: 40x40x6 empirical probs ---
        counts = np.zeros((h, w, 6), dtype=np.int32)
        n_obs = np.zeros((h, w), dtype=np.int32)

        for obs in raw_obs:
            vp = obs["viewport"]
            vx, vy, vw, vh = vp["x"], vp["y"], vp["w"], vp["h"]
            obs_grid = np.array(obs["grid"], dtype=np.int32)

            for lr in range(vh):
                for lc in range(vw):
                    gr, gc = vy + lr, vx + lc
                    if gr < h and gc < w:
                        cls = CODE_TO_CLASS.get(int(obs_grid[lr, lc]), 0)
                        counts[gr, gc, cls] += 1
                        n_obs[gr, gc] += 1

        # Build probabilities (unobserved cells = null)
        gt_from_q = np.zeros((h, w, 6), dtype=np.float64)
        observed = n_obs > 0
        gt_from_q[observed] = counts[observed] / n_obs[observed, np.newaxis]

        # Floor and renormalize observed cells
        gt_from_q[observed] = np.clip(gt_from_q[observed], 0.01, None)
        gt_from_q[observed] = gt_from_q[observed] / gt_from_q[observed].sum(axis=-1, keepdims=True)

        # Unobserved → null (will be stored as all zeros, consumer knows via n_observations)
        seed["query_results"] = query_grids
        seed["ground_truth_from_queries"] = gt_from_q.tolist()
        changed = True

    if changed:
        rpath.write_text(json.dumps(d, indent=2))
    return changed


def main():
    for p in sorted(ROUND_DATA_DIR.glob("round_*.json")):
        d = json.loads(p.read_text())
        rn = d["round_number"]
        has_obs = any(s.get("raw_observations") for s in d.get("seeds", []))
        if not has_obs:
            print(f"  Round {rn}: no observations, skipping")
            continue

        changed = process_round(p)
        if changed:
            # Quick summary
            d2 = json.loads(p.read_text())
            for s in d2["seeds"]:
                qr = s.get("query_results", [])
                gt_q = s.get("ground_truth_from_queries")
                n_obs = s.get("n_observations")
                if qr:
                    n_obs_arr = np.array(n_obs)
                    cells_1 = (n_obs_arr == 1).sum()
                    cells_2 = (n_obs_arr >= 2).sum()
                    cells_0 = (n_obs_arr == 0).sum()
                    print(f"  Round {rn} seed {s['seed_index']}: "
                          f"{len(qr)} query grids, "
                          f"coverage: 0obs={cells_0}, 1obs={cells_1}, 2+obs={cells_2}")
                    break  # just show seed 0


if __name__ == "__main__":
    main()
