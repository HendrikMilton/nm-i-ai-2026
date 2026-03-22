"""
Deep correlation analysis for Astar Island.

Analyzes relationships between initial_grid, observations, and GT at multiple levels:
1. Per-cell: how does a cell's initial terrain, observation, and GT relate?
2. Neighbor: how do neighboring cells influence each other?
3. Spatial lags: how does information propagate across distances?
4. Cross-source lags: initial_grid → obs → GT signal chains

Uses: Pearson, Spearman, Mutual Information, and Distance Correlation.
"""

import json, numpy as np, os, sys, time
from pathlib import Path
from scipy import stats
from scipy.ndimage import uniform_filter, distance_transform_edt
from sklearn.metrics import mutual_info_score, normalized_mutual_info_score
from collections import defaultdict

BASE = Path(__file__).parent.parent / "round_data"

def load_all():
    """Load rounds with initial_grid + obs + GT."""
    data = []
    for rn in range(1, 23):
        rpath = BASE / f"round_{rn:02d}.json"
        spath = BASE / f"round_{rn:02d}_submit.json"
        if not rpath.exists():
            continue
        rd = json.load(open(rpath))
        sd = json.load(open(spath)) if spath.exists() else {}
        submit_seeds = sd.get("seeds", {})

        for s in rd.get("seeds", []):
            if not isinstance(s, dict) or s.get("ground_truth") is None:
                continue
            sid = s["seed_index"]
            sub = submit_seeds.get(str(sid), {})
            ig_raw = sub.get("initial_grid") or rd.get("initial_grid")
            if ig_raw is None:
                continue

            grid = np.array(ig_raw, dtype=np.int32)
            gt = np.array(s["ground_truth"], dtype=np.float32)
            obs = np.array(sub["observed_probs"], dtype=np.float32) if sub.get("observed_probs") else None
            nobs = np.array(sub["n_observations"], dtype=np.float32) if sub.get("n_observations") else None

            data.append({"round": rn, "seed": sid, "grid": grid, "gt": gt,
                         "obs": obs, "nobs": nobs})
    return data


def discretize(arr, n_bins=10):
    """Discretize continuous array for MI computation."""
    flat = arr.ravel()
    if flat.std() < 1e-8:
        return np.zeros_like(flat, dtype=int)
    bins = np.percentile(flat[flat > 0], np.linspace(0, 100, n_bins + 1)) if (flat > 0).sum() > 10 else np.linspace(flat.min(), flat.max(), n_bins + 1)
    bins = np.unique(bins)
    return np.digitize(flat, bins).reshape(arr.shape)


def shifted(arr, dy, dx):
    """Shift 2D array by (dy, dx), filling with NaN."""
    h, w = arr.shape[:2]
    result = np.full_like(arr, np.nan)
    src_r = slice(max(0, -dy), min(h, h - dy))
    src_c = slice(max(0, -dx), min(w, w - dx))
    dst_r = slice(max(0, dy), min(h, h + dy))
    dst_c = slice(max(0, dx), min(w, w + dx))
    result[dst_r, dst_c] = arr[src_r, src_c]
    return result


def safe_corr(a, b):
    """Pearson correlation handling NaN and zero-variance."""
    mask = ~(np.isnan(a) | np.isnan(b))
    a, b = a[mask], b[mask]
    if len(a) < 10 or a.std() < 1e-8 or b.std() < 1e-8:
        return np.nan
    return np.corrcoef(a, b)[0, 1]


def safe_spearman(a, b):
    mask = ~(np.isnan(a) | np.isnan(b))
    a, b = a[mask], b[mask]
    if len(a) < 10 or a.std() < 1e-8 or b.std() < 1e-8:
        return np.nan
    return stats.spearmanr(a, b)[0]


def safe_mi(a, b, n_bins=8):
    """Mutual information between two continuous arrays."""
    mask = ~(np.isnan(a) | np.isnan(b))
    a, b = a[mask], b[mask]
    if len(a) < 20:
        return np.nan
    a_d = np.digitize(a, np.linspace(a.min(), a.max(), n_bins + 1))
    b_d = np.digitize(b, np.linspace(b.min(), b.max(), n_bins + 1))
    return normalized_mutual_info_score(a_d, b_d)


def main():
    t0 = time.time()
    data = load_all()
    has_obs = [d for d in data if d["obs"] is not None]
    print(f"Loaded {len(data)} total, {len(has_obs)} with observations ({time.time()-t0:.1f}s)")

    class_names = ["empty", "settle", "port", "ruin", "forest", "mountain"]

    # ================================================================
    # SECTION 1: PER-CELL CORRELATIONS
    # initial_grid terrain → GT class probabilities
    # observation → GT class probabilities
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  1. PER-CELL: terrain/obs → GT (Pearson, Spearman, MI)")
    print(f"{'='*70}")

    # 1a. Initial terrain one-hot → GT per class
    print(f"\n  1a. initial_terrain → GT class probability")
    terrain_codes = [0, 1, 2, 3, 4, 5, 10, 11]
    terrain_names = {0: "empty", 1: "settle", 2: "port", 3: "ruin", 4: "forest", 5: "mountain", 10: "ocean", 11: "plains"}

    for tc in [11, 4, 1]:  # plains, forest, settlement
        for k in [0, 1, 4]:  # empty, settle, forest in GT
            pearsons, spearmans, mis = [], [], []
            for d in data:
                land = d["grid"] != 10
                is_terrain = (d["grid"] == tc).astype(float)
                gt_k = d["gt"][:, :, k]
                vals_a = is_terrain[land]
                vals_b = gt_k[land]
                if vals_a.std() > 0 and vals_b.std() > 0:
                    pearsons.append(np.corrcoef(vals_a, vals_b)[0, 1])
                    spearmans.append(stats.spearmanr(vals_a, vals_b)[0])
                    mis.append(safe_mi(vals_a, vals_b))
            if pearsons:
                print(f"    {terrain_names[tc]:>8} → gt_{class_names[k]:>6}: "
                      f"pearson={np.nanmean(pearsons):+.3f}  "
                      f"spearman={np.nanmean(spearmans):+.3f}  "
                      f"MI={np.nanmean(mis):.3f}")

    # 1b. Observation → GT (per class, on observed cells)
    print(f"\n  1b. observation → GT per class (observed cells only)")
    for k in range(6):
        pearsons, spearmans, mis = [], [], []
        for d in has_obs:
            observed = (d["nobs"] > 0) & (d["grid"] != 10)
            if observed.sum() < 50:
                continue
            a = d["obs"][observed, k]
            b = d["gt"][observed, k]
            if a.std() > 0 and b.std() > 0:
                pearsons.append(np.corrcoef(a, b)[0, 1])
                spearmans.append(stats.spearmanr(a, b)[0])
                mis.append(safe_mi(a, b))
        if pearsons:
            print(f"    obs_{class_names[k]:>8} → gt_{class_names[k]:>8}: "
                  f"pearson={np.nanmean(pearsons):+.3f}  "
                  f"spearman={np.nanmean(spearmans):+.3f}  "
                  f"MI={np.nanmean(mis):.3f}")

    # ================================================================
    # SECTION 2: NEIGHBOR CORRELATIONS
    # How does GT at (r,c) relate to GT/obs/terrain at (r+dy, c+dx)?
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  2. NEIGHBOR: cell → neighbor correlations")
    print(f"{'='*70}")

    offsets = [(0,1,"→"), (1,0,"↓"), (1,1,"↘"), (0,2,"→→"), (2,0,"↓↓"),
               (0,3,"→→→"), (3,0,"↓↓↓"), (0,5,"→5"), (5,0,"↓5")]

    # 2a. GT → GT neighbor (spatial autocorrelation per class)
    print(f"\n  2a. GT[center] → GT[neighbor] per class")
    print(f"    {'class':>8}", end="")
    for _, _, label in offsets:
        print(f"  {label:>5}", end="")
    print()

    for k in [0, 1, 4]:
        print(f"    {class_names[k]:>8}", end="")
        for dy, dx, label in offsets:
            corrs = []
            for d in data:
                land = d["grid"] != 10
                gt_k = d["gt"][:, :, k]
                gt_shifted = shifted(gt_k, dy, dx)
                mask = land & ~np.isnan(gt_shifted)
                a = gt_k[mask]
                b = gt_shifted[mask]
                if a.std() > 0 and b.std() > 0:
                    corrs.append(np.corrcoef(a, b)[0, 1])
            print(f"  {np.mean(corrs):+.3f}" if corrs else "    nan", end="")
        print()

    # 2b. Obs → GT neighbor (does my observation predict my neighbor's GT?)
    print(f"\n  2b. Obs[center] → GT[neighbor] (settle class)")
    print(f"    {'source':>8}", end="")
    for _, _, label in offsets[:7]:
        print(f"  {label:>5}", end="")
    print()

    for k in [1]:  # settlement
        for src_name, src_fn in [("obs_raw", lambda d: d["obs"][:,:,k]),
                                  ("obs_s3", lambda d: uniform_filter(d["obs"][:,:,k], 3)),
                                  ("obs_s5", lambda d: uniform_filter(d["obs"][:,:,k], 5))]:
            print(f"    {src_name:>8}", end="")
            for dy, dx, label in offsets[:7]:
                corrs = []
                for d in has_obs:
                    observed = (d["nobs"] > 0) & (d["grid"] != 10)
                    src = src_fn(d)
                    gt_shifted = shifted(d["gt"][:,:,k], dy, dx)
                    mask = observed & ~np.isnan(gt_shifted)
                    a = src[mask]
                    b = gt_shifted[mask]
                    if a.std() > 0 and b.std() > 0:
                        corrs.append(np.corrcoef(a, b)[0, 1])
                print(f"  {np.mean(corrs):+.3f}" if corrs else "    nan", end="")
            print()

    # 2c. Initial terrain neighbor → GT center
    print(f"\n  2c. Initial settle_density[radius] → GT[center] settle prob")
    for radius in [1, 2, 3, 5, 7]:
        corrs_p, corrs_s, corrs_mi = [], [], []
        for d in data:
            land = d["grid"] != 10
            settle_init = np.isin(d["grid"], [1, 2]).astype(float)
            density = uniform_filter(settle_init, size=2*radius+1)
            gt_settle = d["gt"][:,:,1]
            a = density[land]
            b = gt_settle[land]
            if a.std() > 0 and b.std() > 0:
                corrs_p.append(np.corrcoef(a, b)[0, 1])
                corrs_s.append(stats.spearmanr(a, b)[0])
                corrs_mi.append(safe_mi(a, b))
        print(f"    r={radius}: pearson={np.nanmean(corrs_p):+.3f}  "
              f"spearman={np.nanmean(corrs_s):+.3f}  MI={np.nanmean(corrs_mi):.3f}")

    # ================================================================
    # SECTION 3: CROSS-SOURCE SPATIAL LAGS
    # initial_grid at offset → obs at center → GT at center
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  3. CROSS-SOURCE SPATIAL LAGS")
    print(f"{'='*70}")

    # 3a. Initial terrain at distance d → GT settle at center
    print(f"\n  3a. settle_in_initial[ring at d] → GT settle[center]")
    for d_ring in range(1, 8):
        corrs = []
        for d in data:
            land = d["grid"] != 10
            settle = np.isin(d["grid"], [1, 2]).astype(float)
            # Ring at distance d: avg of cells at exactly distance d
            density_outer = uniform_filter(settle, size=2*d_ring+1)
            if d_ring > 1:
                density_inner = uniform_filter(settle, size=2*(d_ring-1)+1)
                n_outer = (2*d_ring+1)**2
                n_inner = (2*(d_ring-1)+1)**2
                ring = (density_outer * n_outer - density_inner * n_inner) / max(n_outer - n_inner, 1)
            else:
                ring = density_outer
            gt_s = d["gt"][:,:,1]
            a = ring[land]
            b = gt_s[land]
            if a.std() > 0 and b.std() > 0:
                corrs.append(np.corrcoef(a, b)[0, 1])
        print(f"    d={d_ring}: pearson={np.mean(corrs):+.3f}" if corrs else f"    d={d_ring}: nan")

    # 3b. Obs at neighbor → GT at center (spatial lag of obs signal)
    print(f"\n  3b. obs_settle[at offset] → GT settle[center]")
    for dy, dx, label in offsets[:7]:
        corrs = []
        for d in has_obs:
            observed = (d["nobs"] > 0) & (d["grid"] != 10)
            obs_shifted = shifted(d["obs"][:,:,1], dy, dx)
            mask = observed & ~np.isnan(obs_shifted)
            a = obs_shifted[mask]
            b = d["gt"][:,:,1][mask]
            if a.std() > 0 and b.std() > 0:
                corrs.append(np.corrcoef(a, b)[0, 1])
        print(f"    offset {label:>3}: pearson={np.mean(corrs):+.3f}" if corrs else f"    offset {label}: nan")

    # 3c. GT at center → obs at neighbor (reverse: does GT predict neighbor obs?)
    print(f"\n  3c. GT settle[center] → obs settle[at offset] (reverse)")
    for dy, dx, label in offsets[:7]:
        corrs = []
        for d in has_obs:
            observed = (d["nobs"] > 0) & (d["grid"] != 10)
            obs_shifted = shifted(d["obs"][:,:,1], dy, dx)
            mask = observed & ~np.isnan(obs_shifted)
            a = d["gt"][:,:,1][mask]
            b = obs_shifted[mask]
            if a.std() > 0 and b.std() > 0:
                corrs.append(np.corrcoef(a, b)[0, 1])
        print(f"    offset {label:>3}: pearson={np.mean(corrs):+.3f}" if corrs else f"    offset {label}: nan")

    # 3d. Combined: initial + obs neighbor → GT
    print(f"\n  3d. COMBINED: initial_settle_density + obs_settle_smooth → GT settle")
    print(f"       (multiple regression R² on land cells)")
    from numpy.linalg import lstsq
    for d in has_obs[:5]:  # just a few examples
        land = (d["grid"] != 10) & (d["nobs"] > 0)
        if land.sum() < 100:
            continue
        settle_init = np.isin(d["grid"], [1, 2]).astype(float)
        density3 = uniform_filter(settle_init, size=3)[land]
        density5 = uniform_filter(settle_init, size=5)[land]
        obs_raw = d["obs"][:,:,1][land]
        obs_s3 = uniform_filter(d["obs"][:,:,1], size=3)[land]
        obs_s5 = uniform_filter(d["obs"][:,:,1], size=5)[land]

        gt_s = d["gt"][:,:,1][land]

        # Single predictors
        for name, x in [("init_d3", density3), ("init_d5", density5),
                         ("obs_raw", obs_raw), ("obs_s3", obs_s3), ("obs_s5", obs_s5)]:
            if x.std() > 0:
                r2 = np.corrcoef(x, gt_s)[0, 1]**2
            else:
                r2 = 0
            # Only print first round

        # Combined: all features
        X = np.column_stack([density3, density5, obs_raw, obs_s3, obs_s5, np.ones(land.sum())])
        coef, res, _, _ = lstsq(X, gt_s, rcond=None)
        pred = X @ coef
        ss_res = ((gt_s - pred)**2).sum()
        ss_tot = ((gt_s - gt_s.mean())**2).sum()
        r2_combined = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # Individual R²
        r2_init3 = np.corrcoef(density3, gt_s)[0,1]**2 if density3.std() > 0 else 0
        r2_obs_raw = np.corrcoef(obs_raw, gt_s)[0,1]**2 if obs_raw.std() > 0 else 0
        r2_obs_s5 = np.corrcoef(obs_s5, gt_s)[0,1]**2 if obs_s5.std() > 0 else 0

        print(f"    R{d['round']:2d} S{d['seed']}: "
              f"init_d3={r2_init3:.3f}  obs_raw={r2_obs_raw:.3f}  obs_s5={r2_obs_s5:.3f}  "
              f"combined={r2_combined:.3f}")

    # ================================================================
    # SECTION 4: DISTANCE-CONDITIONED CORRELATIONS
    # Same analyses but split by distance to nearest settlement
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  4. DISTANCE-CONDITIONED: correlations by dist to settlement")
    print(f"{'='*70}")

    # 4a. obs → GT by distance (settlement class)
    print(f"\n  4a. obs_settle → GT settle, by distance")
    for dist_range, label in [((0,1),"d=0"), ((1,2),"d=1"), ((2,3),"d=2"),
                                ((3,5),"d=3-4"), ((5,8),"d=5-7"), ((8,20),"d=8+")]:
        p_corrs, s_corrs, mi_corrs = [], [], []
        for d in has_obs:
            settle_mask = np.isin(d["grid"], [1, 2])
            if not settle_mask.any():
                continue
            dist = distance_transform_edt(~settle_mask).astype(int)
            mask = (d["nobs"] > 0) & (d["grid"] != 10) & (dist >= dist_range[0]) & (dist < dist_range[1])
            if mask.sum() < 20:
                continue
            a = d["obs"][mask, 1]
            b = d["gt"][mask, 1]
            if a.std() > 0 and b.std() > 0:
                p_corrs.append(np.corrcoef(a, b)[0, 1])
                s_corrs.append(stats.spearmanr(a, b)[0])
                mi_corrs.append(safe_mi(a, b))
        if p_corrs:
            print(f"    {label:>5}: pearson={np.nanmean(p_corrs):+.3f}  "
                  f"spearman={np.nanmean(s_corrs):+.3f}  MI={np.nanmean(mi_corrs):.3f}")

    # 4b. neighbor obs → GT by distance
    print(f"\n  4b. obs_settle_smooth5 → GT settle, by distance")
    for dist_range, label in [((0,1),"d=0"), ((1,2),"d=1"), ((2,3),"d=2"),
                                ((3,5),"d=3-4"), ((5,8),"d=5-7")]:
        corrs = []
        for d in has_obs:
            settle_mask = np.isin(d["grid"], [1, 2])
            if not settle_mask.any():
                continue
            dist = distance_transform_edt(~settle_mask).astype(int)
            mask = (d["nobs"] > 0) & (d["grid"] != 10) & (dist >= dist_range[0]) & (dist < dist_range[1])
            if mask.sum() < 20:
                continue
            a = uniform_filter(d["obs"][:,:,1], size=5)[mask]
            b = d["gt"][mask, 1]
            if a.std() > 0 and b.std() > 0:
                corrs.append(np.corrcoef(a, b)[0, 1])
        if corrs:
            print(f"    {label:>5}: pearson={np.mean(corrs):+.3f}  (smooth5 vs raw above)")

    print(f"\nTotal time: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
