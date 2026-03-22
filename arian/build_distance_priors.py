"""
Build expansion-rate-aware distance priors from all available ground truth.

Key insight: a joint prior on (expansion_rate, terrain, distance, n_forest, is_coastal)
trained with Gaussian kernel weighting gives +6 points average over the old approach.

Output:
    - distance_priors.json: pre-computed tables for a grid of expansion rates
      Format: { "0.050": { "11_2_3_0": [p0..p5], ... }, "0.055": {...}, ... }
"""

import json
import glob
import math
import os

N_CLASSES = 6
BANDWIDTH = 0.03
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ELIAS_OFFLINE_DIR = os.path.join(SCRIPT_DIR, "..", "elias", "logs", "offline")
HENDRIK_DIR = os.path.join(SCRIPT_DIR, "..", "hendrik", "challenge3", "round_data")


def load_all_gt():
    """Load ground truth from all sources with distance maps and expansion rates."""
    all_data = []

    # Elias v2 files
    for fpath in sorted(glob.glob(os.path.join(ELIAS_OFFLINE_DIR, "v2_R*.json"))):
        basename = os.path.basename(fpath)
        # Skip variant files
        after_R = basename.split("v2_R")[1].replace(".json", "")
        if "_" in after_R:
            continue
        try:
            rd = json.load(open(fpath))
        except Exception:
            continue
        rn = rd.get("round_number")
        if rn is None:
            continue
        for sid, sv in rd.get("seeds", {}).items():
            gt = sv.get("ground_truth")
            ig = sv.get("initial_grid")
            if gt and ig:
                all_data.append((rn, ig, gt, "elias"))

    # Hendrik files
    for rn in range(1, 25):
        fpath = os.path.join(HENDRIK_DIR, f"round_{rn:02d}.json")
        if not os.path.exists(fpath):
            continue
        try:
            d = json.load(open(fpath))
        except Exception:
            continue
        for s in d.get("seeds", []):
            if not isinstance(s, dict):
                continue
            gt = s.get("ground_truth")
            ig = s.get("initial_grid")
            if gt and ig:
                # Only add if we don't already have this round from elias
                if not any(x[0] == rn for x in all_data):
                    all_data.append((rn, ig, gt, "hendrik"))

    return all_data


def compute_distance_map(ig):
    h = len(ig)
    w = len(ig[0]) if h > 0 else 0
    dist_map = [[999] * w for _ in range(h)]
    queue = []
    for r in range(h):
        for c in range(w):
            if ig[r][c] in (1, 2):
                dist_map[r][c] = 0
                queue.append((r, c))
    head = 0
    while head < len(queue):
        r, c = queue[head]
        head += 1
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if 0 <= nr < h and 0 <= nc < w and dist_map[nr][nc] > dist_map[r][c] + 1:
                    dist_map[nr][nc] = dist_map[r][c] + 1
                    queue.append((nr, nc))
    return dist_map


def compute_expansion_rate(ig, gt, dist_map):
    h = len(ig)
    w = len(ig[0]) if h > 0 else 0
    settle = 0.0
    total = 0
    for r in range(h):
        for c in range(w):
            if ig[r][c] in (10, 5, 1, 2):
                continue
            if 1 <= dist_map[r][c] <= 3:
                total += 1
                settle += gt[r][c][1] + gt[r][c][2]
    return settle / total if total > 0 else 0.0


def compute_cell_features(ig, r, c, h, w, dist_map):
    terrain = ig[r][c]
    if terrain in (10, 5):
        return None

    dist = min(dist_map[r][c], 7)
    n_forest = 0
    is_coastal = False
    n_settlement = 0
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w:
                if ig[nr][nc] == 4:
                    n_forest += 1
                if ig[nr][nc] == 10:
                    is_coastal = True
                if ig[nr][nc] in (1, 2):
                    n_settlement += 1

    key = f"{min(terrain, 11)}_{dist}_{min(n_forest, 4)}_{1 if is_coastal else 0}"
    return key


def build_priors_for_rate(target_rate, seed_data_list, bandwidth=BANDWIDTH):
    """Build prior table for a specific expansion rate using Gaussian kernel weighting."""
    accum = {}

    for exp_rate, ig, gt, dist_map in seed_data_list:
        weight = math.exp(-0.5 * ((target_rate - exp_rate) / bandwidth) ** 2)
        if weight < 0.001:
            continue

        h = len(ig)
        w = len(ig[0]) if h > 0 else 0

        for r in range(h):
            for c in range(w):
                key = compute_cell_features(ig, r, c, h, w, dist_map)
                if key is None:
                    continue

                if key not in accum:
                    accum[key] = {"ws": [0.0] * N_CLASSES, "tw": 0.0}
                for k in range(N_CLASSES):
                    accum[key]["ws"][k] += weight * float(gt[r][c][k])
                accum[key]["tw"] += weight

    table = {}
    for key, data in accum.items():
        tw = data["tw"]
        if tw > 0:
            avg = [v / tw for v in data["ws"]]
            total = sum(avg)
            if total > 0:
                avg = [v / total for v in avg]
            table[key] = [round(v, 6) for v in avg]

    return table


def main():
    print("Loading ground truth from all sources...")
    raw_data = load_all_gt()
    print(f"  Loaded {len(raw_data)} seed maps")

    # Precompute distance maps and expansion rates
    print("Computing distance maps and expansion rates...")
    seed_data = []
    round_rates = {}
    for rn, ig, gt, source in raw_data:
        dist_map = compute_distance_map(ig)
        exp_rate = compute_expansion_rate(ig, gt, dist_map)
        seed_data.append((exp_rate, ig, gt, dist_map))
        round_rates.setdefault(rn, []).append(exp_rate)

    print("\nPer-round expansion rates:")
    for rn in sorted(round_rates.keys()):
        rates = round_rates[rn]
        avg = sum(rates) / len(rates)
        warmth = "COLD" if avg < 0.05 else "warm"
        print(f"  R{rn:>2}: {avg:.4f} ({warmth})")

    # Build prior tables for a grid of expansion rates
    rate_grid = [i * 0.005 for i in range(81)]  # 0.000 to 0.400
    print(f"\nBuilding prior tables for {len(rate_grid)} expansion rates...")

    distance_priors = {}
    all_keys = set()
    for rate in rate_grid:
        rate_key = f"{rate:.3f}"
        table = build_priors_for_rate(rate, seed_data)
        distance_priors[rate_key] = table
        all_keys.update(table.keys())

    print(f"  Total unique keys: {len(all_keys)}")

    # Save
    out_path = os.path.join(SCRIPT_DIR, "distance_priors.json")
    with open(out_path, "w") as f:
        json.dump(distance_priors, f)
    size_kb = os.path.getsize(out_path) // 1024
    print(f"  Saved {out_path} ({size_kb} KB)")

    # Also save a metadata file
    meta = {
        "n_training_seeds": len(seed_data),
        "n_rounds": len(round_rates),
        "rounds": sorted(round_rates.keys()),
        "bandwidth": BANDWIDTH,
        "n_rate_steps": len(rate_grid),
        "n_keys": len(all_keys),
        "rate_range": [0.0, 0.400],
    }
    meta_path = os.path.join(SCRIPT_DIR, "distance_priors_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"  Saved {meta_path}")

    # Quick validation: show sample priors at different expansion rates
    sample_key = "11_2_2_0"  # plains, dist 2, 2 forests, inland
    if sample_key in all_keys:
        print(f"\nSample: {sample_key} (plains, dist=2, 2 forests, inland)")
        print(f"  {'Rate':>6}  {'Empty':>6} {'Settle':>6} {'Port':>6} {'Ruin':>6} {'Forest':>6}")
        for rate_str in ["0.005", "0.020", "0.050", "0.100", "0.150", "0.200", "0.300"]:
            if rate_str in distance_priors and sample_key in distance_priors[rate_str]:
                p = distance_priors[rate_str][sample_key]
                print(f"  {rate_str:>6}  {p[0]:>6.3f} {p[1]:>6.3f} {p[2]:>6.3f} {p[3]:>6.3f} {p[4]:>6.3f}")


if __name__ == "__main__":
    main()
