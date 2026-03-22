"""
Rebuild contextual priors from ALL available ground truth data (R1-R16).

Sources:
  - elias/logs/offline/v2_R*.json  (seeds as dict, R1-R15)
  - hendrik/challenge3/round_data/round_XX.json  (seeds as list, R1-R14, R16)

Output (in arian/):
  - contextual_priors.json
  - contextual_priors_warm.json
  - contextual_priors_cold.json
"""

import json
import glob
import os

N_CLASSES = 6
WARM_COLD_THRESHOLD = 0.05

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ELIAS_OFFLINE_DIR = os.path.join(SCRIPT_DIR, "..", "elias", "logs", "offline")
HENDRIK_DIR = os.path.join(SCRIPT_DIR, "..", "hendrik", "challenge3", "round_data")
OUTPUT_DIR = SCRIPT_DIR


def load_elias_gt():
    """Load GT from elias/logs/offline/v2_R*.json (dict-keyed seeds)."""
    rounds = {}
    for fpath in sorted(glob.glob(os.path.join(ELIAS_OFFLINE_DIR, "v2_R*.json"))):
        try:
            with open(fpath) as f:
                d = json.load(f)
        except Exception:
            continue

        rn = d.get("round_number")
        if rn is None:
            continue

        # Skip variant files (keep base v2_R{n}.json only)
        basename = os.path.basename(fpath)
        expected = f"v2_R{rn}.json"
        if basename != expected:
            continue

        seeds_data = {}
        for seed_str, sv in d.get("seeds", {}).items():
            gt = sv.get("ground_truth")
            ig = sv.get("initial_grid")
            if gt and ig:
                seeds_data[seed_str] = {"ground_truth": gt, "initial_grid": ig}

        if seeds_data:
            rounds[rn] = {"round_number": rn, "seeds": seeds_data, "source": "elias"}

    return rounds


def load_hendrik_gt():
    """Load GT from hendrik/challenge3/round_data/round_XX.json (list-keyed seeds)."""
    rounds = {}
    for rn in range(1, 25):
        fpath = os.path.join(HENDRIK_DIR, f"round_{rn:02d}.json")
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath) as f:
                d = json.load(f)
        except Exception:
            continue

        seeds_list = d.get("seeds", [])
        seeds_data = {}
        for i, s in enumerate(seeds_list):
            if not isinstance(s, dict):
                continue
            gt = s.get("ground_truth")
            ig = s.get("initial_grid")
            if gt and ig:
                seeds_data[str(i)] = {
                    "ground_truth": gt,
                    "initial_grid": ig,
                }

        if seeds_data:
            rounds[rn] = {"round_number": rn, "seeds": seeds_data, "source": "hendrik"}

    return rounds


def merge_rounds(elias, hendrik):
    """Merge, preferring source with more seeds. Elias wins ties."""
    all_rn = sorted(set(elias.keys()) | set(hendrik.keys()))
    merged = {}
    for rn in all_rn:
        e = elias.get(rn)
        h = hendrik.get(rn)
        if e and h:
            if len(h["seeds"]) > len(e["seeds"]):
                merged[rn] = h
            else:
                merged[rn] = e
        elif e:
            merged[rn] = e
        else:
            merged[rn] = h
    return merged


def compute_expansion_rate(initial_grid, ground_truth):
    """Avg P(settlement|port) at dist 1-3 from initial settlements."""
    h = len(initial_grid)
    w = len(initial_grid[0]) if h > 0 else 0

    dist = [[999] * w for _ in range(h)]
    queue = []
    for r in range(h):
        for c in range(w):
            if initial_grid[r][c] in (1, 2):
                dist[r][c] = 0
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
                if 0 <= nr < h and 0 <= nc < w and dist[nr][nc] > dist[r][c] + 1:
                    dist[nr][nc] = dist[r][c] + 1
                    queue.append((nr, nc))

    settle_prob = 0.0
    total_cells = 0
    for r in range(h):
        for c in range(w):
            if initial_grid[r][c] in (10, 5, 1, 2):
                continue
            if dist[r][c] < 1 or dist[r][c] > 3:
                continue
            total_cells += 1
            settle_prob += ground_truth[r][c][1] + ground_truth[r][c][2]

    if total_cells == 0:
        return None
    return settle_prob / total_cells


def build_contextual_key(terrain, n_forest, is_coastal):
    return f"{min(terrain, 11)}_{min(n_forest, 4)}_{1 if is_coastal else 0}"


def build_priors_from_rounds(rounds_dict):
    """Build per-round contextual priors and expansion rates."""
    round_data = []

    for rn in sorted(rounds_dict.keys()):
        rinfo = rounds_dict[rn]
        key_probs_warm = {}
        key_probs_cold = {}
        key_probs_all = {}
        expansion_rates = []

        for seed_str, seed_data in rinfo["seeds"].items():
            gt = seed_data["ground_truth"]
            ig = seed_data["initial_grid"]

            exp_rate = compute_expansion_rate(ig, gt)
            if exp_rate is not None:
                expansion_rates.append(exp_rate)

        avg_exp = sum(expansion_rates) / len(expansion_rates) if expansion_rates else None
        if avg_exp is None:
            print(f"  R{rn}: skipped (no expansion rate)")
            continue

        is_warm = avg_exp >= WARM_COLD_THRESHOLD
        warmth = "warm" if is_warm else "cold"

        for seed_str, seed_data in rinfo["seeds"].items():
            gt = seed_data["ground_truth"]
            ig = seed_data["initial_grid"]
            h = len(gt)
            w = len(gt[0]) if h > 0 else 0

            for r in range(h):
                for c in range(w):
                    terrain = ig[r][c]
                    if terrain == 10 or terrain == 5:
                        continue

                    n_forest = 0
                    is_coastal = False
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

                    key = build_contextual_key(terrain, n_forest, is_coastal)
                    gt_probs = [float(v) for v in gt[r][c]]

                    key_probs_all.setdefault(key, []).append(gt_probs)
                    if is_warm:
                        key_probs_warm.setdefault(key, []).append(gt_probs)
                    else:
                        key_probs_cold.setdefault(key, []).append(gt_probs)

        n_seeds = len(rinfo["seeds"])
        print(f"  R{rn:>2}: exp={avg_exp:.4f} ({warmth}), {n_seeds} seeds, src={rinfo['source']}")

        round_data.append({
            "round_number": rn,
            "expansion_rate": avg_exp,
            "warmth": warmth,
            "key_probs_warm": key_probs_warm,
            "key_probs_cold": key_probs_cold,
            "key_probs_all": key_probs_all,
        })

    return round_data


def average_probs(prob_lists):
    """Average a list of probability vectors and normalize."""
    n = len(prob_lists)
    if n == 0:
        return None
    avg = [0.0] * N_CLASSES
    for probs in prob_lists:
        for k in range(N_CLASSES):
            avg[k] += probs[k]
    avg = [v / n for v in avg]
    total = sum(avg)
    if total > 0:
        avg = [v / total for v in avg]
    return [round(v, 6) for v in avg]


def aggregate_tables(round_data_list):
    """Aggregate per-round key_probs into warm/cold/all tables."""
    all_probs = {}
    warm_probs = {}
    cold_probs = {}

    for rd in round_data_list:
        for key, pl in rd["key_probs_all"].items():
            all_probs.setdefault(key, []).extend(pl)
        for key, pl in rd["key_probs_warm"].items():
            warm_probs.setdefault(key, []).extend(pl)
        for key, pl in rd["key_probs_cold"].items():
            cold_probs.setdefault(key, []).extend(pl)

    all_table = {k: average_probs(v) for k, v in all_probs.items() if v}
    warm_table = {k: average_probs(v) for k, v in warm_probs.items() if v}
    cold_table = {k: average_probs(v) for k, v in cold_probs.items() if v}

    return all_table, warm_table, cold_table


def main():
    print("=" * 60)
    print("Loading ground truth from all sources")
    print("=" * 60)

    elias = load_elias_gt()
    print(f"  Elias: {len(elias)} rounds ({sorted(elias.keys())})")

    hendrik = load_hendrik_gt()
    print(f"  Hendrik: {len(hendrik)} rounds ({sorted(hendrik.keys())})")

    merged = merge_rounds(elias, hendrik)
    print(f"  Merged: {len(merged)} unique rounds ({sorted(merged.keys())})")

    print(f"\n{'=' * 60}")
    print("Building per-round priors")
    print("=" * 60)

    round_data = build_priors_from_rounds(merged)

    n_warm = sum(1 for rd in round_data if rd["warmth"] == "warm")
    n_cold = sum(1 for rd in round_data if rd["warmth"] == "cold")
    print(f"\n  {n_warm} warm rounds, {n_cold} cold rounds")

    print(f"\n{'=' * 60}")
    print("Aggregating into warm/cold/all tables")
    print("=" * 60)

    all_table, warm_table, cold_table = aggregate_tables(round_data)
    print(f"  All:  {len(all_table)} keys")
    print(f"  Warm: {len(warm_table)} keys")
    print(f"  Cold: {len(cold_table)} keys")

    # Save
    for name, table in [
        ("contextual_priors.json", all_table),
        ("contextual_priors_warm.json", warm_table),
        ("contextual_priors_cold.json", cold_table),
    ]:
        path = os.path.join(OUTPUT_DIR, name)
        with open(path, "w") as f:
            json.dump(table, f, indent=2)
        print(f"  Wrote {path} ({len(table)} keys)")


if __name__ == "__main__":
    main()
