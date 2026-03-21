"""
Merge live query observation grids into round_data JSONs.
Adds per-seed fields:
  - raw_observations: list of {viewport, grid} from live queries
  - observed_counts: 40x40x6 int array — how many times each cell was observed as each class
  - observed_probs: 40x40x6 float — empirical probability distribution from observations
  - n_observations: 40x40 int — how many times each cell was observed
"""

import json
import numpy as np
from pathlib import Path

ROUND_DATA_DIR = Path(__file__).parent / "round_data"
ELIAS_ROUNDS_DIR = Path('/home/hendrik/Documents/agentic-avengers-nm-ai/elias/logs/rounds')

# Sim terrain code → prediction class
CODE_TO_CLASS = {0: 0, 11: 0, 10: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}


def merge_observations():
    # Map round_id → round file
    round_files = {}
    for p in sorted(ROUND_DATA_DIR.glob("round_*.json")):
        d = json.loads(p.read_text())
        round_files[d["round_id"]] = p

    updated = 0
    for f in sorted(ELIAS_ROUNDS_DIR.glob("*.json")):
        rid = f.stem
        if rid not in round_files:
            continue

        live = json.loads(f.read_text())
        queries = live.get("queries", [])
        if not queries or not any("grid" in q for q in queries):
            continue

        # Load round data
        rpath = round_files[rid]
        rdata = json.loads(rpath.read_text())
        grid = np.array(rdata["initial_grid"], dtype=np.int32)
        h, w = grid.shape

        # Group queries by seed
        from collections import defaultdict
        seed_queries = defaultdict(list)
        for q in queries:
            if "grid" in q and "seed_index" in q:
                seed_queries[q["seed_index"]].append(q)

        # Update each seed
        for seed in rdata.get("seeds", []):
            si = seed["seed_index"]
            qs = seed_queries.get(si, [])

            # Build observation counts: 40x40x6
            obs_counts = np.zeros((h, w, 6), dtype=np.int32)
            n_obs = np.zeros((h, w), dtype=np.int32)

            raw_obs = []
            for q in qs:
                vp = q["viewport"]
                vx, vy, vw, vh = vp["x"], vp["y"], vp["w"], vp["h"]
                obs_grid = np.array(q["grid"], dtype=np.int32)

                raw_obs.append({"viewport": vp, "grid": q["grid"]})

                for lr in range(vh):
                    for lc in range(vw):
                        gr, gc = vy + lr, vx + lc
                        if gr >= h or gc >= w:
                            continue
                        code = obs_grid[lr, lc]
                        cls = CODE_TO_CLASS.get(code, 0)
                        obs_counts[gr, gc, cls] += 1
                        n_obs[gr, gc] += 1

            # Build empirical probabilities
            obs_probs = np.zeros((h, w, 6), dtype=np.float64)
            observed_mask = n_obs > 0
            obs_probs[observed_mask] = obs_counts[observed_mask] / n_obs[observed_mask, np.newaxis]

            seed["raw_observations"] = raw_obs
            seed["observed_counts"] = obs_counts.tolist()
            seed["observed_probs"] = obs_probs.tolist()
            seed["n_observations"] = n_obs.tolist()

        # Save
        rpath.write_text(json.dumps(rdata, indent=2))
        rn = rdata["round_number"]
        n_seeds_with_obs = sum(1 for s in rdata["seeds"]
                               if s.get("raw_observations") and len(s["raw_observations"]) > 0)
        total_obs = sum(len(s.get("raw_observations", [])) for s in rdata["seeds"])
        print(f"  Round {rn}: merged {total_obs} observations across {n_seeds_with_obs} seeds")
        updated += 1

    print(f"\nUpdated {updated} round files")

    # Summary: which rounds have observations
    print("\nCoverage summary:")
    for p in sorted(ROUND_DATA_DIR.glob("round_*.json")):
        d = json.loads(p.read_text())
        rn = d["round_number"]
        has_obs = any(s.get("raw_observations") for s in d.get("seeds", []))
        if has_obs:
            obs_per_seed = [len(s.get("raw_observations", [])) for s in d["seeds"]]
            n_obs_example = np.array(d["seeds"][0].get("n_observations", []))
            if n_obs_example.size > 0:
                coverage = (np.array(n_obs_example) > 0).sum()
            else:
                coverage = 0
            print(f"  Round {rn}: obs_per_seed={obs_per_seed}, seed0_cells_covered={coverage}/1600")
        else:
            print(f"  Round {rn}: no observations")


if __name__ == "__main__":
    merge_observations()
