"""
Analyze terrain transitions: what can each initial cell become?
Uses ground truth argmax + full probability distributions.
"""

import json
import numpy as np
from pathlib import Path
from collections import defaultdict

ROUND_DATA_DIR = Path(__file__).parent / "round_data"
TERRAIN_NAMES = {0: "empty", 1: "settlement", 2: "port", 3: "ruin", 4: "forest", 5: "mountain", 10: "ocean", 11: "plains"}
CLASS_NAMES = ["empty", "settlement", "port", "ruin", "forest", "mountain"]


def main():
    # transition_counts[init_code][output_class] = count of cells where argmax == output_class
    transition_counts = defaultdict(lambda: np.zeros(6))
    # transition_probs[init_code] = accumulated probability vectors
    transition_probs = defaultdict(lambda: np.zeros(6))
    transition_n = defaultdict(int)
    # Track min/max probability seen for each (init_code, output_class)
    prob_max = defaultdict(lambda: np.zeros(6))
    prob_min = defaultdict(lambda: np.ones(6))

    n_samples = 0
    for p in sorted(ROUND_DATA_DIR.glob("round_*.json")):
        d = json.loads(p.read_text())
        grid = np.array(d["initial_grid"], dtype=np.int32)

        for s in d.get("seeds", []):
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt, dtype=np.float64)
            argmax = np.argmax(gt, axis=-1)
            n_samples += 1

            for code in TERRAIN_NAMES:
                mask = grid == code
                if not mask.any():
                    continue
                n = mask.sum()
                transition_n[code] += n

                # Argmax counts
                for cls in range(6):
                    transition_counts[code][cls] += (argmax[mask] == cls).sum()

                # Probability accumulation
                transition_probs[code] += gt[mask].sum(axis=0)

                # Min/max per cell
                cell_probs = gt[mask]  # (n_cells, 6)
                prob_max[code] = np.maximum(prob_max[code], cell_probs.max(axis=0))
                prob_min[code] = np.minimum(prob_min[code], cell_probs.min(axis=0))

    print(f"Analyzed {n_samples} seed ground truths\n")

    # --- Transition matrix (argmax) ---
    print("=" * 80)
    print("ARGMAX TRANSITION MATRIX (% of cells where output class is most likely)")
    print("=" * 80)
    header = f"{'Initial':>12} | " + " ".join(f"{c:>10}" for c in CLASS_NAMES) + " |    N cells"
    print(header)
    print("-" * len(header))
    for code in [10, 11, 0, 1, 2, 3, 4, 5]:
        if transition_n[code] == 0:
            continue
        n = transition_n[code]
        pcts = transition_counts[code] / n * 100
        row = f"{TERRAIN_NAMES[code]:>12} | " + " ".join(f"{p:>9.1f}%" for p in pcts) + f" | {n:>10}"
        print(row)

    # --- Mean probability matrix ---
    print(f"\n{'=' * 80}")
    print("MEAN PROBABILITY MATRIX (average GT probability per cell)")
    print("=" * 80)
    print(header)
    print("-" * len(header))
    for code in [10, 11, 0, 1, 2, 3, 4, 5]:
        if transition_n[code] == 0:
            continue
        n = transition_n[code]
        avg = transition_probs[code] / n
        row = f"{TERRAIN_NAMES[code]:>12} | " + " ".join(f"{p:>10.4f}" for p in avg) + f" | {n:>10}"
        print(row)

    # --- Never/rare transitions ---
    print(f"\n{'=' * 80}")
    print("MAX PROBABILITY EVER SEEN (if max < 0.01, transition effectively never happens)")
    print("=" * 80)
    print(header)
    print("-" * len(header))
    for code in [10, 11, 0, 1, 2, 3, 4, 5]:
        if transition_n[code] == 0:
            continue
        n = transition_n[code]
        row = f"{TERRAIN_NAMES[code]:>12} | " + " ".join(f"{p:>10.4f}" for p in prob_max[code]) + f" | {n:>10}"
        print(row)

    # --- Impossible transitions ---
    print(f"\n{'=' * 80}")
    print("TRANSITIONS THAT NEVER HAPPEN (max prob < 0.05 across ALL cells, ALL rounds)")
    print("=" * 80)
    never = []
    rare = []
    for code in [10, 11, 0, 1, 2, 3, 4, 5]:
        if transition_n[code] == 0:
            continue
        for cls in range(6):
            mx = prob_max[code][cls]
            if mx < 0.01:
                never.append((TERRAIN_NAMES[code], CLASS_NAMES[cls], mx))
            elif mx < 0.05:
                rare.append((TERRAIN_NAMES[code], CLASS_NAMES[cls], mx))

    if never:
        print("\nNEVER (max < 1%):")
        for init, out, mx in never:
            print(f"  {init:>12} → {out:<12} (max prob seen: {mx:.4f})")

    if rare:
        print("\nRARE (max 1-5%):")
        for init, out, mx in rare:
            print(f"  {init:>12} → {out:<12} (max prob seen: {mx:.4f})")

    common = []
    for code in [10, 11, 0, 1, 2, 3, 4, 5]:
        if transition_n[code] == 0:
            continue
        for cls in range(6):
            avg = transition_probs[code][cls] / transition_n[code]
            if avg > 0.05:
                common.append((TERRAIN_NAMES[code], CLASS_NAMES[cls], avg, prob_max[code][cls]))

    print("\nCOMMON TRANSITIONS (mean prob > 5%):")
    for init, out, avg, mx in sorted(common, key=lambda x: -x[2]):
        print(f"  {init:>12} → {out:<12} mean={avg:.4f}  max={mx:.4f}")


if __name__ == "__main__":
    main()
