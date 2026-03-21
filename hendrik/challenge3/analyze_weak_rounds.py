"""
Analyze why R9 and R12 score poorly in LOO CV.
Compares terrain, GT distributions, config, and cross-round similarity.
"""

import json
import numpy as np
import math
from pathlib import Path
from collections import defaultdict

V2_DIR = Path("../../elias/logs/offline")

def load_all():
    data = {}
    for f in sorted(V2_DIR.glob("v2_R*.json")):
        with open(f) as fh:
            d = json.load(fh)
        rnum = d["round_number"]
        config = d["config"]
        seeds = {}
        for sid in ["0","1","2","3","4"]:
            s = d["seeds"][sid]
            seeds[int(sid)] = {
                "grid": np.array(s["initial_grid"], dtype=np.int32),
                "gt": np.array(s["ground_truth"], dtype=np.float32),
            }
        data[rnum] = {
            "warmth": config.get("warmth", "warm"),
            "exp_rate": config.get("expansion_rate", 0.15),
            "seeds": seeds,
        }
    return data

def terrain_dist(grid):
    """Return dict of terrain code -> fraction."""
    total = grid.size
    unique, counts = np.unique(grid, return_counts=True)
    return {int(u): c / total for u, c in zip(unique, counts)}

def gt_class_means(gt):
    """Mean probability per class across all cells."""
    return gt.mean(axis=(0, 1))

def wkl(gt, pred):
    gt_s = np.clip(gt, 1e-10, None)
    pred_s = np.clip(pred, 1e-10, None)
    ent = -np.sum(gt_s * np.log(gt_s), axis=-1)
    kl = np.sum(gt_s * (np.log(gt_s) - np.log(pred_s)), axis=-1)
    total_ent = ent.sum()
    if total_ent < 1e-8: return 0
    return (ent * kl).sum() / total_ent

def score(gt, pred):
    pred = np.clip(pred, 0.01, None)
    pred /= pred.sum(axis=-1, keepdims=True)
    return max(0, min(100, 100 * math.exp(-3 * wkl(gt, pred))))

data = load_all()
tn = {0:'Empty', 1:'Settle', 2:'Port', 3:'Ruin', 4:'Forest', 5:'Mt', 10:'Ocean', 11:'Plains'}
cn = ['Empty', 'Settle', 'Port', 'Ruin', 'Forest', 'Mountain']

# ============================================================
print("=" * 70)
print("1. PER-ROUND CONFIG + TERRAIN SUMMARY")
print("=" * 70)
for rn in sorted(data):
    d = data[rn]
    grid0 = d["seeds"][0]["grid"]
    td = terrain_dist(grid0)
    settle_pct = td.get(1, 0) * 100
    port_pct = td.get(2, 0) * 100
    forest_pct = td.get(4, 0) * 100
    ocean_pct = td.get(10, 0) * 100
    print(f"  R{rn:2d} {d['warmth']:5s} exp={d['exp_rate']:.4f} | "
          f"settle={settle_pct:.1f}% port={port_pct:.1f}% forest={forest_pct:.1f}% ocean={ocean_pct:.1f}%")

# ============================================================
print("\n" + "=" * 70)
print("2. GT CLASS DISTRIBUTIONS (seed 0)")
print("=" * 70)
print(f"  {'Round':>6} | {'Empty':>6} {'Settle':>6} {'Port':>6} {'Ruin':>6} {'Forest':>6} {'Mt':>6} | {'Entropy':>7}")
print("  " + "-" * 65)
for rn in sorted(data):
    gt = data[rn]["seeds"][0]["gt"]
    means = gt_class_means(gt)
    ent = -(np.clip(gt, 1e-10, None) * np.log(np.clip(gt, 1e-10, None))).sum(axis=-1)
    mean_ent = ent.mean()
    print(f"  R{rn:2d}   | {' '.join(f'{m:.4f}' for m in means)} | {mean_ent:.4f}")

# ============================================================
print("\n" + "=" * 70)
print("3. CROSS-SEED VARIANCE (how much do seeds differ within a round?)")
print("=" * 70)
for rn in sorted(data):
    gts = np.array([data[rn]["seeds"][s]["gt"] for s in range(5)])  # (5, 40, 40, 6)
    cross_var = gts.var(axis=0).mean()  # mean variance across cells and classes
    # Also check grid differences
    grids = [data[rn]["seeds"][s]["grid"] for s in range(5)]
    grid_diffs = [np.mean(grids[0] != grids[s]) for s in range(1, 5)]
    mean_grid_diff = np.mean(grid_diffs) * 100
    print(f"  R{rn:2d}: GT cross-seed var={cross_var:.5f}, grid diff from seed0={mean_grid_diff:.1f}%")

# ============================================================
print("\n" + "=" * 70)
print("4. CROSS-ROUND GT SIMILARITY (how similar is each round to others?)")
print("   Using terrain-conditioned mean GT per round")
print("=" * 70)

# For each round, compute per-terrain-code mean GT
round_profiles = {}
for rn in sorted(data):
    profile = {}
    for sid in range(5):
        grid = data[rn]["seeds"][sid]["grid"]
        gt = data[rn]["seeds"][sid]["gt"]
        for code in [0, 1, 2, 3, 4, 5, 10, 11]:
            mask = grid == code
            if mask.sum() > 0:
                if code not in profile:
                    profile[code] = []
                profile[code].append(gt[mask].mean(axis=0))
    round_profiles[rn] = {c: np.mean(vs, axis=0) for c, vs in profile.items()}

# Distance matrix: how different is each round's GT profile from others?
print(f"\n  {'':>4}", end="")
for rn2 in sorted(data):
    print(f"  R{rn2:2d}", end="")
print()
for rn1 in sorted(data):
    print(f"  R{rn1:2d}", end="")
    for rn2 in sorted(data):
        dist = 0
        n = 0
        for code in round_profiles[rn1]:
            if code in round_profiles[rn2]:
                dist += np.abs(round_profiles[rn1][code] - round_profiles[rn2][code]).sum()
                n += 1
        avg_dist = dist / max(n, 1)
        print(f" {avg_dist:5.3f}", end="")
    print()

# ============================================================
print("\n" + "=" * 70)
print("5. WHAT MAKES R9 AND R12 UNIQUE?")
print("=" * 70)

# R9 vs warm-round average
warm_rounds = [rn for rn in data if data[rn]["warmth"] == "warm"]
for target_rn in [9, 12, 7]:
    print(f"\n  --- R{target_rn} vs other warm rounds ---")
    for code in [1, 2, 4, 11]:
        target_vals = []
        other_vals = []
        for sid in range(5):
            grid = data[target_rn]["seeds"][sid]["grid"]
            gt = data[target_rn]["seeds"][sid]["gt"]
            mask = grid == code
            if mask.sum() > 0:
                target_vals.append(gt[mask].mean(axis=0))
        for rn in warm_rounds:
            if rn == target_rn:
                continue
            for sid in range(5):
                grid = data[rn]["seeds"][sid]["grid"]
                gt = data[rn]["seeds"][sid]["gt"]
                mask = grid == code
                if mask.sum() > 0:
                    other_vals.append(gt[mask].mean(axis=0))
        if target_vals and other_vals:
            t = np.mean(target_vals, axis=0)
            o = np.mean(other_vals, axis=0)
            diff = t - o
            # Only show classes with significant difference
            sig = [f"{cn[i]}:{diff[i]:+.3f}" for i in range(6) if abs(diff[i]) > 0.02]
            if sig:
                print(f"    {tn[code]:>8s}: {', '.join(sig)}")

# ============================================================
print("\n" + "=" * 70)
print("6. ENTROPY ANALYSIS (which rounds have hardest cells to predict?)")
print("=" * 70)
for rn in sorted(data):
    all_ent = []
    for sid in range(5):
        gt = data[rn]["seeds"][sid]["gt"]
        gt_s = np.clip(gt, 1e-10, None)
        ent = -(gt_s * np.log(gt_s)).sum(axis=-1)
        all_ent.append(ent)
    ents = np.array(all_ent)
    mean_ent = ents.mean()
    high_ent_pct = (ents > 1.0).mean() * 100  # % of cells with entropy > 1
    max_ent = ents.max()
    print(f"  R{rn:2d}: mean_entropy={mean_ent:.4f}, high_entropy(>1.0)={high_ent_pct:.1f}%, max={max_ent:.3f}")

# ============================================================
print("\n" + "=" * 70)
print("7. LOO LOOKUP SCORE BREAKDOWN (what score does simple lookup get per round?)")
print("=" * 70)
for test_rn in sorted(data):
    # Build lookup from other rounds
    feat_sums = {}
    feat_counts = {}
    for rn in data:
        if rn == test_rn:
            continue
        w = 'w' if data[rn]["warmth"] == "warm" else 'c'
        for sid in range(5):
            grid = data[rn]["seeds"][sid]["grid"]
            gt = data[rn]["seeds"][sid]["gt"]
            for r in range(40):
                for c in range(40):
                    code = grid[r, c]
                    nbrs = []
                    for dy in [-1,0,1]:
                        for dx in [-1,0,1]:
                            if dy==0 and dx==0: continue
                            nr, nc = r+dy, c+dx
                            if 0<=nr<40 and 0<=nc<40:
                                nbrs.append(grid[nr,nc])
                    has_sn = any(n==1 for n in nbrs)
                    is_coast = any(n==10 for n in nbrs) and code != 10
                    key = (int(code), w, has_sn, is_coast)
                    if key not in feat_sums:
                        feat_sums[key] = np.zeros(6)
                        feat_counts[key] = 0
                    feat_sums[key] += gt[r, c]
                    feat_counts[key] += 1
    lookup = {k: feat_sums[k]/feat_counts[k] for k in feat_sums}

    # Score
    w = 'w' if data[test_rn]["warmth"] == "warm" else 'c'
    seed_scores = []
    for sid in range(5):
        grid = data[test_rn]["seeds"][sid]["grid"]
        gt = data[test_rn]["seeds"][sid]["gt"]
        pred = np.full((40,40,6), 1/6)
        for r in range(40):
            for c in range(40):
                code = grid[r, c]
                nbrs = []
                for dy in [-1,0,1]:
                    for dx in [-1,0,1]:
                        if dy==0 and dx==0: continue
                        nr, nc = r+dy, c+dx
                        if 0<=nr<40 and 0<=nc<40:
                            nbrs.append(grid[nr,nc])
                has_sn = any(n==1 for n in nbrs)
                is_coast = any(n==10 for n in nbrs) and code != 10
                key = (int(code), w, has_sn, is_coast)
                if key in lookup:
                    pred[r,c] = lookup[key]
        seed_scores.append(score(gt, pred))

    mean_sc = np.mean(seed_scores)
    print(f"  R{test_rn:2d}: lookup={mean_sc:.1f}, GBM=??  seeds=[{' '.join(f'{s:.1f}' for s in seed_scores)}]")
