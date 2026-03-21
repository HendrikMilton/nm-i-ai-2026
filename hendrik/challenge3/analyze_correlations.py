"""
Correlation analysis across seeds, rounds, and cells.
Linear (Pearson), rank (Spearman), and non-linear (mutual information).
"""

import json
import numpy as np
from pathlib import Path
from collections import defaultdict
from scipy.stats import spearmanr, pearsonr
from sklearn.metrics import mutual_info_score

ROUND_DATA_DIR = Path(__file__).parent / "round_data"
CLASS_NAMES = ["empty", "settle", "port", "ruin", "forest", "mtn"]


def load_all_gt():
    """Load all ground truth as {round_num: {seed_idx: 40x40x6 array}}"""
    data = {}
    for p in sorted(ROUND_DATA_DIR.glob("round_*.json")):
        d = json.loads(p.read_text())
        rn = d["round_number"]
        grid = np.array(d["initial_grid"])
        seeds = {}
        for s in d.get("seeds", []):
            gt = s.get("ground_truth")
            if gt is not None:
                seeds[s["seed_index"]] = np.array(gt)
        if seeds:
            data[rn] = {"grid": grid, "seeds": seeds}
    return data


def section(title):
    print(f"\n{'=' * 80}")
    print(title)
    print('=' * 80)


def main():
    data = load_all_gt()
    print(f"Loaded {len(data)} rounds with GT")

    # ================================================================
    # 1. SEED-TO-SEED CORRELATION within same round
    # ================================================================
    section("1. SEED-TO-SEED CORRELATION (same round, different seeds)")
    print("   Are seed outcomes correlated? If yes, observing one seed helps predict others.")

    for rn in sorted(list(data.keys()))[:6]:
        seeds = data[rn]["seeds"]
        sids = sorted(seeds.keys())
        if len(sids) < 2:
            continue

        print(f"\n  Round {rn}:")
        # Flatten GT to vectors for correlation
        # Use P(settlement) as the signal — most informative class
        for cls, cls_name in [(1, "settle"), (4, "forest")]:
            vecs = {}
            for si in sids:
                vecs[si] = seeds[si][:, :, cls].flatten()

            # Pairwise Pearson
            pearson_vals = []
            spearman_vals = []
            mi_vals = []
            for i in range(len(sids)):
                for j in range(i + 1, len(sids)):
                    a, b = vecs[sids[i]], vecs[sids[j]]
                    pr, _ = pearsonr(a, b)
                    sr, _ = spearmanr(a, b)
                    # Mutual info: discretize to bins
                    a_binned = np.digitize(a, np.linspace(0, 1, 20))
                    b_binned = np.digitize(b, np.linspace(0, 1, 20))
                    mi = mutual_info_score(a_binned, b_binned)
                    pearson_vals.append(pr)
                    spearman_vals.append(sr)
                    mi_vals.append(mi)

            print(f"    P({cls_name}): Pearson={np.mean(pearson_vals):.3f}  "
                  f"Spearman={np.mean(spearman_vals):.3f}  "
                  f"MI={np.mean(mi_vals):.3f}")

    # ================================================================
    # 2. ROUND-TO-ROUND CORRELATION (same seed index)
    # ================================================================
    section("2. ROUND-TO-ROUND CORRELATION (do similar grids produce similar outcomes?)")

    # For seed 0 across all rounds, correlate the GT distributions
    rounds_sorted = sorted(data.keys())
    print(f"\n  Seed 0, P(settlement) — Pearson correlation between rounds:")
    print(f"  {'':>8}", end="")
    for rn in rounds_sorted:
        print(f" R{rn:>2}", end="")
    print()

    for rn1 in rounds_sorted:
        if 0 not in data[rn1]["seeds"]:
            continue
        v1 = data[rn1]["seeds"][0][:, :, 1].flatten()
        print(f"  R{rn1:>2}    ", end="")
        for rn2 in rounds_sorted:
            if 0 not in data[rn2]["seeds"]:
                print(f"  -- ", end="")
                continue
            v2 = data[rn2]["seeds"][0][:, :, 1].flatten()
            pr, _ = pearsonr(v1, v2)
            print(f" {pr:>.2f}", end="")
        print()

    # ================================================================
    # 3. SPATIAL AUTOCORRELATION — are nearby cells correlated?
    # ================================================================
    section("3. SPATIAL AUTOCORRELATION (Moran's I approximation)")
    print("   Do nearby cells have similar outcomes?")

    for rn in [8, 9, 11, 12]:
        if rn not in data:
            continue
        gt = data[rn]["seeds"][0]
        grid = data[rn]["grid"]

        for cls, cls_name in [(1, "settle"), (4, "forest")]:
            vals = gt[:, :, cls]
            mean_v = vals.mean()
            if mean_v < 0.001:
                continue

            # Compute lag-1 autocorrelation (horizontal + vertical neighbors)
            denom = ((vals - mean_v) ** 2).sum()
            if denom < 1e-10:
                continue

            numer = 0.0
            n_pairs = 0
            for lag in [1, 2, 3, 5]:
                numer = 0.0
                n_pairs = 0
                for r in range(40):
                    for c in range(40):
                        if grid[r, c] == 10:  # skip ocean
                            continue
                        for dr, dc in [(0, lag), (lag, 0)]:
                            nr, nc = r + dr, c + dc
                            if nr < 40 and nc < 40 and grid[nr, nc] != 10:
                                numer += (vals[r, c] - mean_v) * (vals[nr, nc] - mean_v)
                                n_pairs += 1

                if n_pairs > 0:
                    morans_i = (n_pairs * numer) / (n_pairs * denom) * 40 * 40
                    # Simpler: just correlation
                    corr = numer / (n_pairs * (denom / (40*40)))

                print(f"  Round {rn} P({cls_name}) lag={lag}: autocorr={corr:.3f} (n={n_pairs})")

    # ================================================================
    # 4. INITIAL TERRAIN → GT CORRELATION (non-linear)
    # ================================================================
    section("4. FEATURE IMPORTANCE — which initial grid features predict outcomes?")
    print("   Mutual information between initial features and GT P(settlement)")

    from scipy.ndimage import distance_transform_edt

    all_features = []
    all_targets = []

    for rn in sorted(data.keys()):
        grid = data[rn]["grid"]
        settle_mask = (grid == 1).astype(np.float32)
        dist_s = distance_transform_edt(1 - settle_mask) if settle_mask.sum() > 0 else np.full((40, 40), 99.0)

        n_ocean = np.zeros((40, 40))
        n_forest = np.zeros((40, 40))
        n_settle = np.zeros((40, 40))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                n_ocean += np.roll(np.roll((grid == 10).astype(float), dy, 0), dx, 1)
                n_forest += np.roll(np.roll((grid == 4).astype(float), dy, 0), dx, 1)
                n_settle += np.roll(np.roll((grid == 1).astype(float), dy, 0), dx, 1)

        for si in data[rn]["seeds"]:
            gt = data[rn]["seeds"][si]
            for r in range(40):
                for c in range(40):
                    if grid[r, c] == 10:
                        continue
                    all_features.append([
                        grid[r, c],          # terrain code
                        dist_s[r, c],        # dist to settlement
                        n_ocean[r, c],       # ocean neighbors
                        n_forest[r, c],      # forest neighbors
                        n_settle[r, c],      # settlement neighbors
                        r, c,                # position
                    ])
                    all_targets.append(gt[r, c, 1])  # P(settlement)

    features = np.array(all_features)
    target = np.array(all_targets)
    target_binned = np.digitize(target, np.linspace(0, 1, 30))

    feat_names = ["terrain", "dist_settle", "n_ocean", "n_forest", "n_settle", "row", "col"]
    print(f"\n  {'Feature':>15} | {'MI':>8} | {'Spearman':>10} | {'Pearson':>10}")
    for i, name in enumerate(feat_names):
        f_binned = np.digitize(features[:, i], np.linspace(features[:, i].min(), features[:, i].max(), 30))
        mi = mutual_info_score(f_binned, target_binned)
        sr, _ = spearmanr(features[:, i], target)
        pr, _ = pearsonr(features[:, i], target)
        print(f"  {name:>15} | {mi:>8.4f} | {sr:>10.4f} | {pr:>10.4f}")

    # ================================================================
    # 5. CROSS-SEED PREDICTION — can seed 0 predict seeds 1-4?
    # ================================================================
    section("5. CROSS-SEED PREDICTION POWER")
    print("   If we know seed 0 GT, how well does it predict seeds 1-4?")

    from eval import score_prediction

    for rn in sorted(data.keys()):
        seeds = data[rn]["seeds"]
        if 0 not in seeds or len(seeds) < 2:
            continue

        s0 = seeds[0]
        cross_scores = []
        for si in sorted(seeds.keys()):
            if si == 0:
                continue
            # Use seed 0 GT as prediction for seed si
            score = score_prediction(s0, seeds[si])
            cross_scores.append(score)

        print(f"  Round {rn}: seed0→others mean score = {np.mean(cross_scores):.1f} "
              f"({' '.join(f's{i+1}={s:.1f}' for i, s in enumerate(cross_scores))})")


if __name__ == "__main__":
    main()
