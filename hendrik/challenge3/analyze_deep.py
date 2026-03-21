"""
Deep data exploration — verify assumptions, find patterns.
"""

import json
import numpy as np
from pathlib import Path
from collections import defaultdict

ROUND_DATA_DIR = Path(__file__).parent / "round_data"
CLASS_NAMES = ["empty", "settlement", "port", "ruin", "forest", "mountain"]


def load_rounds():
    rounds = []
    for p in sorted(ROUND_DATA_DIR.glob("round_*.json")):
        d = json.loads(p.read_text())
        has_gt = any(s.get("ground_truth") is not None for s in d.get("seeds", []))
        if has_gt:
            rounds.append(d)
    return rounds


def count_neighbors(grid, code):
    mask = (grid == code).astype(np.float32)
    c = np.zeros_like(mask)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            c += np.roll(np.roll(mask, dy, 0), dx, 1)
    return c


def count_any_land_neighbors(grid):
    land = ((grid != 10)).astype(np.float32)
    c = np.zeros_like(land)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            c += np.roll(np.roll(land, dy, 0), dx, 1)
    return c


def section(title):
    print(f"\n{'=' * 80}")
    print(title)
    print('=' * 80)


def main():
    rounds = load_rounds()
    print(f"Loaded {len(rounds)} rounds with ground truth")

    # ================================================================
    # 1. SEED VARIANCE — how much do seeds differ for same initial grid?
    # ================================================================
    section("1. SEED-TO-SEED VARIANCE (same initial grid, different sim seeds)")
    print("   If low → one prediction per grid is enough. If high → need per-seed strategy.")

    for rnd in rounds[:6]:
        rn = rnd["round_number"]
        gts = []
        for s in rnd["seeds"]:
            gt = s.get("ground_truth")
            if gt is not None:
                gts.append(np.array(gt))
        if len(gts) < 2:
            continue

        # Pairwise L1 distance between seed GT distributions
        dists = []
        for i in range(len(gts)):
            for j in range(i + 1, len(gts)):
                dists.append(np.abs(gts[i] - gts[j]).mean())

        # Per-cell std across seeds
        stacked = np.stack(gts)  # (5, 40, 40, 6)
        cell_std = stacked.std(axis=0).mean()

        # Argmax agreement
        argmaxes = [np.argmax(g, axis=-1) for g in gts]
        agreements = []
        for i in range(len(argmaxes)):
            for j in range(i + 1, len(argmaxes)):
                agreements.append((argmaxes[i] == argmaxes[j]).mean())

        print(f"  Round {rn}: mean_L1={np.mean(dists):.4f}, cell_std={cell_std:.4f}, "
              f"argmax_agree={np.mean(agreements):.1%}")

    # ================================================================
    # 2. OCEAN CELLS — do they really change?
    # ================================================================
    section("2. OCEAN CELLS — do they actually change or is it noise?")
    print("   Checking if 'ocean → settlement' is real or just probability floor.")

    ocean_changed = 0
    ocean_total = 0
    ocean_examples = []
    for rnd in rounds:
        grid = np.array(rnd["initial_grid"])
        ocean_mask = grid == 10
        for s in rnd["seeds"]:
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt)
            ocean_gt = gt[ocean_mask]
            # Cells where argmax is NOT empty
            argmax = np.argmax(ocean_gt, axis=-1)
            changed = (argmax != 0).sum()
            ocean_changed += changed
            ocean_total += ocean_mask.sum()

            # Find most extreme ocean cell
            if changed > 0:
                non_empty_prob = 1.0 - ocean_gt[:, 0]
                worst_idx = np.argmax(non_empty_prob)
                if non_empty_prob[worst_idx] > 0.3:
                    ocean_examples.append((rnd["round_number"], s["seed_index"],
                                          non_empty_prob[worst_idx], ocean_gt[worst_idx]))

    print(f"  Ocean cells where argmax != empty: {ocean_changed}/{ocean_total} "
          f"({ocean_changed/ocean_total:.1%})")
    print(f"  Examples of ocean cells with high non-empty prob:")
    for rn, si, prob, dist in sorted(ocean_examples, key=lambda x: -x[2])[:5]:
        print(f"    Round {rn} seed {si}: P(non-empty)={prob:.2f}, dist={np.round(dist, 3)}")

    # ================================================================
    # 3. MOUNTAIN CELLS — truly static?
    # ================================================================
    section("3. MOUNTAIN CELLS — truly static?")

    mtn_stays = 0
    mtn_total = 0
    for rnd in rounds:
        grid = np.array(rnd["initial_grid"])
        mtn_mask = grid == 5
        for s in rnd["seeds"]:
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt)
            argmax = np.argmax(gt[mtn_mask], axis=-1)
            mtn_stays += (argmax == 5).sum()
            mtn_total += mtn_mask.sum()

    print(f"  Mountain stays mountain: {mtn_stays}/{mtn_total} ({mtn_stays/mtn_total:.1%})")
    print(f"  Mountain changes: {mtn_total - mtn_stays}/{mtn_total} ({(mtn_total-mtn_stays)/mtn_total:.1%})")

    # ================================================================
    # 4. DISTANCE FROM SETTLEMENT — does it predict outcome?
    # ================================================================
    section("4. DISTANCE FROM NEAREST SETTLEMENT vs OUTCOME")
    print("   For plains cells: does proximity to settlements predict what they become?")

    from scipy.ndimage import distance_transform_edt

    dist_buckets = defaultdict(lambda: np.zeros(6))
    dist_counts = defaultdict(int)

    for rnd in rounds:
        grid = np.array(rnd["initial_grid"])
        settle_mask = (grid == 1).astype(np.float32)
        if settle_mask.sum() == 0:
            continue
        dist_map = distance_transform_edt(1 - settle_mask)
        plains_mask = grid == 11

        for s in rnd["seeds"]:
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt)
            for r in range(40):
                for c in range(40):
                    if not plains_mask[r, c]:
                        continue
                    d = int(min(dist_map[r, c], 15))
                    dist_buckets[d] += gt[r, c]
                    dist_counts[d] += 1

    print(f"  {'Dist':>6} | {'N':>7} | " + " ".join(f"{c:>10}" for c in CLASS_NAMES))
    for d in range(16):
        if dist_counts[d] == 0:
            continue
        avg = dist_buckets[d] / dist_counts[d]
        print(f"  {d:>6} | {dist_counts[d]:>7} | " + " ".join(f"{p:>10.4f}" for p in avg))

    # ================================================================
    # 5. SETTLEMENT CLUSTER SIZE vs SURVIVAL
    # ================================================================
    section("5. SETTLEMENT CLUSTER SIZE vs SURVIVAL RATE")
    print("   Do larger clusters survive better?")

    from scipy.ndimage import label as ndlabel

    cluster_survival = defaultdict(list)
    for rnd in rounds:
        grid = np.array(rnd["initial_grid"])
        settle_mask = (grid == 1).astype(np.int32)
        labeled, n_clusters = ndlabel(settle_mask)

        for s in rnd["seeds"]:
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt)

            for cid in range(1, n_clusters + 1):
                cluster_cells = labeled == cid
                size = cluster_cells.sum()
                # Average settlement probability for cells in this cluster
                settle_prob = gt[cluster_cells, 1].mean()
                cluster_survival[min(size, 8)].append(settle_prob)

    print(f"  {'Size':>6} | {'N clusters':>10} | {'Mean P(settle)':>14} | {'Std':>8}")
    for size in sorted(cluster_survival.keys()):
        vals = cluster_survival[size]
        print(f"  {size:>6} | {len(vals):>10} | {np.mean(vals):>14.4f} | {np.std(vals):>8.4f}")

    # ================================================================
    # 6. EDGE vs CENTER — do border cells behave differently?
    # ================================================================
    section("6. EDGE vs CENTER BEHAVIOR")
    print("   Do cells near the map border behave differently?")

    edge_gt = np.zeros(6)
    center_gt = np.zeros(6)
    edge_n = 0
    center_n = 0

    for rnd in rounds:
        grid = np.array(rnd["initial_grid"])
        for s in rnd["seeds"]:
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt)
            for r in range(40):
                for c in range(40):
                    if grid[r, c] == 10:  # skip ocean
                        continue
                    is_edge = r <= 1 or r >= 38 or c <= 1 or c >= 38
                    if is_edge:
                        edge_gt += gt[r, c]
                        edge_n += 1
                    else:
                        center_gt += gt[r, c]
                        center_n += 1

    print(f"  {'Zone':>8} | {'N':>8} | " + " ".join(f"{c:>10}" for c in CLASS_NAMES))
    print(f"  {'edge':>8} | {edge_n:>8} | " + " ".join(f"{p:>10.4f}" for p in edge_gt / edge_n))
    print(f"  {'center':>8} | {center_n:>8} | " + " ".join(f"{p:>10.4f}" for p in center_gt / center_n))

    # ================================================================
    # 7. ROUND DIFFICULTY — what makes a round hard?
    # ================================================================
    section("7. ROUND DIFFICULTY — correlation with grid properties")

    print(f"  {'Round':>5} | {'Score':>7} | {'#Settle':>7} | {'#Forest':>7} | {'#Ocean':>7} | "
          f"{'MeanEnt':>8} | {'HighEntCells':>12}")
    for rnd in rounds:
        rn = rnd["round_number"]
        score = rnd.get("round_score")
        grid = np.array(rnd["initial_grid"])
        n_s = (grid == 1).sum()
        n_f = (grid == 4).sum()
        n_o = (grid == 10).sum()

        ents = []
        high_ent = 0
        for s in rnd["seeds"]:
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt)
            gt_safe = np.clip(gt, 1e-10, None)
            ent = -np.sum(gt_safe * np.log(gt_safe), axis=-1)
            ents.append(ent.mean())
            high_ent += (ent > 0.5).sum()

        mean_ent = np.mean(ents) if ents else 0
        score_str = f"{score:>7.1f}" if score else "    N/A"
        print(f"  {rn:>5} | {score_str} | {n_s:>7} | {n_f:>7} | {n_o:>7} | "
              f"{mean_ent:>8.3f} | {high_ent // max(len(ents),1):>12}")

    # ================================================================
    # 8. FOREST NEIGHBOR COUNT vs FOREST SURVIVAL
    # ================================================================
    section("8. FOREST CELLS — neighbor forest count vs survival")

    forest_by_nf = defaultdict(lambda: np.zeros(6))
    forest_by_nf_n = defaultdict(int)

    for rnd in rounds:
        grid = np.array(rnd["initial_grid"])
        nf = count_neighbors(grid, 4)
        forest_mask = grid == 4

        for s in rnd["seeds"]:
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt)
            for r in range(40):
                for c in range(40):
                    if not forest_mask[r, c]:
                        continue
                    bucket = int(nf[r, c])
                    forest_by_nf[bucket] += gt[r, c]
                    forest_by_nf_n[bucket] += 1

    print(f"  {'#ForNbr':>7} | {'N':>8} | {'P(empty)':>10} {'P(settle)':>10} {'P(forest)':>10}")
    for nf_count in range(9):
        if forest_by_nf_n[nf_count] == 0:
            continue
        avg = forest_by_nf[nf_count] / forest_by_nf_n[nf_count]
        print(f"  {nf_count:>7} | {forest_by_nf_n[nf_count]:>8} | {avg[0]:>10.4f} {avg[1]:>10.4f} {avg[4]:>10.4f}")

    # ================================================================
    # 9. INITIAL SETTLEMENT COUNT vs OVERALL SCORE
    # ================================================================
    section("9. CORRELATION: initial grid features vs Elias offline scores")

    # Check if more settlements = harder/easier
    scored = [(rnd["round_number"],
               (np.array(rnd["initial_grid"]) == 1).sum(),
               (np.array(rnd["initial_grid"]) == 4).sum(),
               rnd.get("round_score"))
              for rnd in rounds if rnd.get("round_score")]

    if scored:
        rns, settles, forests, scores = zip(*scored)
        settles, scores = np.array(settles, dtype=float), np.array(scores, dtype=float)
        corr_s = np.corrcoef(settles, scores)[0, 1]
        forests = np.array(forests, dtype=float)
        corr_f = np.corrcoef(forests, scores)[0, 1]
        print(f"  Correlation(#settlements, score) = {corr_s:.3f}")
        print(f"  Correlation(#forests, score)      = {corr_f:.3f}")

    # ================================================================
    # 10. PER-SEED SCORE VARIATION — is seed 0 always easiest?
    # ================================================================
    section("10. PER-SEED SCORE PATTERN — is seed 0 consistently different?")

    from eval import score_prediction
    seed_scores_all = defaultdict(list)
    for rnd in rounds:
        grid = np.array(rnd["initial_grid"])
        for s in rnd["seeds"]:
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt)
            gt_safe = np.clip(gt, 1e-10, None)
            ent = -np.sum(gt_safe * np.log(gt_safe), axis=-1)
            seed_scores_all[s["seed_index"]].append(ent.mean())

    print(f"  {'Seed':>6} | {'Mean Entropy':>12} | {'Std':>8} | {'N':>4}")
    for si in sorted(seed_scores_all.keys()):
        vals = seed_scores_all[si]
        print(f"  {si:>6} | {np.mean(vals):>12.4f} | {np.std(vals):>8.4f} | {len(vals):>4}")


if __name__ == "__main__":
    main()
