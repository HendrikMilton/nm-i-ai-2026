"""
Challenge 3: Astar Island — Per-cell LightGBM prediction.
V3: base features + distance prior features + n_settlements expansion rate estimation.
"""

import json
import logging
import math
import glob as glob_module
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter, convolve
import lightgbm as lgb
import joblib

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ============================================================
# Constants
# ============================================================
GRID_SIZE = 40
N_CLASSES = 6
PROB_FLOOR = 0.01  # used in score_prediction only
# Per-class floors for predictions (lower floors = less mass stolen from dominant class)
CLASS_FLOORS = [0.005, 0.005, 0.001, 0.002, 0.005, 0.001]
TERRAIN_TO_CLASS = {0: 0, 10: 0, 11: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}

CHECKPOINT_DIR = Path(__file__).parent / "checkpoints"
CHECKPOINT_V3_DIR = Path(__file__).parent / "checkpoints_v3"
V2_DATA_DIR = Path(__file__).parent / "../../elias/logs/offline"
ROUND_DATA_DIR = Path(__file__).parent / "round_data"
DISTANCE_PRIOR_PATH = Path(__file__).parent / "../../arian/distance_priors.json"

# Default hidden params (median warm round values)
DEFAULT_SETTLE_SURVIVE = 0.30
DEFAULT_SPREAD_TENDENCY = 0.45
DEFAULT_PORT_ACTIVITY = 0.15

FEATURE_NAMES = [
    "terrain_code",
    "n_ocean", "n_settlement", "n_port", "n_forest", "n_mountain", "n_plains", "n_ruin",
    "is_coastal", "has_settle_nbr", "n_settle_nbr",
    "dist_to_settlement", "dist_to_ocean", "dist_to_port", "dist_to_forest",
    "settle_density_r3", "settle_density_r5", "settle_density_r7",
    "forest_density_r3", "forest_density_r5",
    "port_density_r3",
    "row_norm", "col_norm",
    "n_land_nbr", "terrain_diversity",
    # 3 round-level hidden params (from GT or obs)
    "settle_survive", "spread_tendency", "port_activity",
    # 7 settlement stats (from query API, defaults for historical rounds)
    "mean_population", "mean_food", "mean_wealth", "mean_defense",
    "n_factions", "sett_port_ratio", "alive_ratio",
]

# Defaults for settlement stats (median across observed rounds)
DEFAULT_SETTLEMENT_STATS = {
    "mean_population": 2.5, "mean_food": 0.4, "mean_wealth": 0.02,
    "mean_defense": 0.9, "n_factions": 15, "port_ratio": 0.05,
    "alive_ratio": 0.8,
}


# ============================================================
# Distance prior lookup (V3)
# ============================================================
_PRIOR_LOOKUP = None
_PRIOR_RATE_KEYS = None
_PRIOR_RATE_VALS = None
_PRIOR_DEFAULT = np.array([1.0/6]*6, dtype=np.float32)
_USE_V3 = False  # set True when V3 models are loaded


def _load_distance_priors():
    """Load and preprocess distance priors into fast lookup."""
    global _PRIOR_LOOKUP, _PRIOR_RATE_KEYS, _PRIOR_RATE_VALS
    if _PRIOR_LOOKUP is not None:
        return True
    if not DISTANCE_PRIOR_PATH.exists():
        log.warning(f"Distance priors not found at {DISTANCE_PRIOR_PATH}")
        return False
    t0 = time.time()
    with open(DISTANCE_PRIOR_PATH) as f:
        raw = json.load(f)
    _PRIOR_RATE_KEYS = sorted(raw.keys(), key=float)
    _PRIOR_RATE_VALS = np.array([float(k) for k in _PRIOR_RATE_KEYS])
    _PRIOR_LOOKUP = {}
    for rk in _PRIOR_RATE_KEYS:
        lookup = {}
        for str_key, probs in raw[rk].items():
            parts = str_key.split("_")
            t, d, nf, ic = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            int_key = t * 10000 + d * 100 + nf * 10 + ic
            lookup[int_key] = np.array(probs, dtype=np.float32)
        _PRIOR_LOOKUP[rk] = lookup
    log.info(f"Loaded distance priors ({len(_PRIOR_RATE_KEYS)} rates) in {time.time()-t0:.1f}s")
    return True


def _find_nearest_rate(expansion_rate):
    idx = np.argmin(np.abs(_PRIOR_RATE_VALS - expansion_rate))
    return _PRIOR_RATE_KEYS[idx]


def estimate_expansion_rate(grid, settlement_stats):
    """Estimate expansion rate from n_settlements (R²=0.995)."""
    if not settlement_stats:
        return 0.1
    n_sett = settlement_stats.get("n_settlements", 0)
    if n_sett == 0:
        return 0.1
    grid = np.asarray(grid)
    n_land = int((grid != 10).sum())
    if n_land == 0:
        return 0.1
    exp_rate = 0.759 * (n_sett / n_land) - 0.004
    return max(0.001, min(0.5, exp_rate))


def compute_obs_settle_density(query_grids, grid_shape=(GRID_SIZE, GRID_SIZE)):
    """From query settlements, compute per-cell settlement density at 3 radii + binary map."""
    from scipy.ndimage import uniform_filter as uf
    h, w = grid_shape
    sett_map = np.zeros((h, w), dtype=np.float32)
    seen = set()
    for q in query_grids:
        for s in q.get("settlements", []):
            x, y = s["x"], s["y"]
            if 0 <= y < h and 0 <= x < w and (x, y) not in seen:
                seen.add((x, y))
                sett_map[y, x] = 1.0
    return uf(sett_map, size=3), uf(sett_map, size=5), uf(sett_map, size=7), sett_map


N_OBS_DENSITY_FEATURES = 4  # d1, d2, d3, smap


def compute_prior_features(grid, expansion_rate):
    """Compute 6 distance prior probability features per cell. Returns (H, W, 6)."""
    grid = np.asarray(grid, dtype=np.int32)
    h, w = grid.shape
    rate_key = _find_nearest_rate(expansion_rate)
    lookup = _PRIOR_LOOKUP[rate_key]

    settle_mask = np.isin(grid, [1, 2])
    if settle_mask.any():
        dist_map = np.clip(distance_transform_edt(~settle_mask).astype(np.int32), 0, 20)
    else:
        dist_map = np.full((h, w), 20, dtype=np.int32)

    kernel = np.array([[1,1,1],[1,0,1],[1,1,1]], dtype=np.int32)
    forest = (grid == 4).astype(np.int32)
    n_forest = np.clip(convolve(forest, kernel, mode='constant', cval=0), 0, 8)
    ocean = (grid == 10).astype(np.int32)
    ocean_nbr = convolve(ocean, kernel, mode='constant', cval=0)
    is_coastal = ((ocean_nbr > 0) & (ocean == 0)).astype(np.int32)

    int_keys = grid * 10000 + dist_map * 100 + n_forest * 10 + is_coastal
    prior_probs = np.zeros((h, w, 6), dtype=np.float32)
    flat_keys = int_keys.ravel()
    flat_priors = prior_probs.reshape(-1, 6)
    for i, k in enumerate(flat_keys):
        p = lookup.get(int(k))
        if p is not None:
            flat_priors[i] = p
        else:
            k2 = int(k) ^ 1
            p2 = lookup.get(k2)
            flat_priors[i] = p2 if p2 is not None else _PRIOR_DEFAULT
    return prior_probs


# ============================================================
# Hidden param computation
# ============================================================
def compute_hidden_params(grid, probs):
    """Compute 3 hidden params from GT (smooth probs) or obs (binary probs).
    Same formula works for both — just noisier with observations.
    Returns (settle_survive, spread_tendency, port_activity).
    """
    grid = np.asarray(grid, dtype=np.int32)
    probs = np.asarray(probs, dtype=np.float32)

    sm = grid == 1   # settlement
    om = grid == 10  # ocean
    ptm = grid == 2  # port
    land = ~om

    # 1. settle_survive: P(settlement stays settlement)
    settle_survive = probs[sm, 1].mean() if sm.sum() > 0 else DEFAULT_SETTLE_SURVIVE

    # 2. spread_tendency: ratio of P(settle) at distance 2 vs distance 0
    if sm.sum() > 0:
        dist = distance_transform_edt(~sm).astype(int)
        d0_cells = (dist == 0) & land
        d2_cells = (dist == 2) & land
        d0 = probs[d0_cells, 1].mean() if d0_cells.sum() > 0 else 0.001
        d2 = probs[d2_cells, 1].mean() if d2_cells.sum() > 0 else 0
        spread_tendency = d2 / max(d0, 0.001)
    else:
        spread_tendency = DEFAULT_SPREAD_TENDENCY

    # 3. port_activity: port survival or coastal port formation
    if ptm.sum() > 0:
        port_activity = probs[ptm, 2].mean()
    else:
        ocean_nbr = np.zeros((GRID_SIZE, GRID_SIZE), dtype=bool)
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dy == 0 and dx == 0: continue
                ocean_nbr |= np.roll(np.roll(om, dy, 0), dx, 1)
        coastal = land & ocean_nbr
        port_activity = probs[coastal, 2].mean() if coastal.sum() > 0 else DEFAULT_PORT_ACTIVITY

    return float(settle_survive), float(spread_tendency), float(port_activity)


def compute_hidden_params_from_obs(grid, obs_probs, n_obs):
    """Compute hidden params from observation data. Falls back to defaults for unobserved areas."""
    obs_probs = np.asarray(obs_probs, dtype=np.float32)
    n_obs = np.asarray(n_obs, dtype=np.float32)

    # Only use cells that were actually observed
    observed = n_obs > 0
    if observed.sum() < 100:
        return DEFAULT_SETTLE_SURVIVE, DEFAULT_SPREAD_TENDENCY, DEFAULT_PORT_ACTIVITY

    # Create a masked version of probs (zeros where unobserved)
    return compute_hidden_params(grid, obs_probs)


# ============================================================
# Observation reconstruction
# ============================================================
def reconstruct_observations(queries):
    """Reconstruct observed_probs/n_obs from viewport query results."""
    obs_counts = np.zeros((GRID_SIZE, GRID_SIZE, N_CLASSES), dtype=np.int32)
    n_obs = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.int32)

    for q in queries:
        vp = q["viewport"]
        qgrid = np.array(q["grid"])
        x, y, w, h = vp["x"], vp["y"], vp["w"], vp["h"]
        for dr in range(min(h, qgrid.shape[0])):
            for dc in range(min(w, qgrid.shape[1])):
                r, c = y + dr, x + dc
                if 0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE:
                    cls = TERRAIN_TO_CLASS.get(int(qgrid[dr, dc]), 0)
                    obs_counts[r, c, cls] += 1
                    n_obs[r, c] += 1

    obs_probs = np.zeros((GRID_SIZE, GRID_SIZE, N_CLASSES), dtype=np.float32)
    mask = n_obs > 0
    obs_probs[mask] = obs_counts[mask] / n_obs[mask, None]
    return obs_probs, n_obs


# ============================================================
# Feature extraction
# ============================================================
def extract_features(grid, settle_survive, spread_tendency, port_activity, settlement_stats=None):
    """Extract per-cell features + 3 hidden params + 7 settlement stats. Returns (1600, 35)."""
    grid = np.asarray(grid, dtype=np.int32)
    h, w = grid.shape

    masks = {}
    for name, code in [("ocean", 10), ("settlement", 1), ("port", 2),
                        ("forest", 4), ("mountain", 5), ("ruin", 3),
                        ("plains", 11), ("empty", 0)]:
        masks[name] = (grid == code).astype(np.float32)

    def nbr_count(mask):
        c = np.zeros_like(mask)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                shifted = np.zeros_like(mask)
                r_src = slice(max(0, -dy), min(h, h - dy))
                c_src = slice(max(0, -dx), min(w, w - dx))
                r_dst = slice(max(0, dy), min(h, h + dy))
                c_dst = slice(max(0, dx), min(w, w + dx))
                shifted[r_dst, c_dst] = mask[r_src, c_src]
                c += shifted
        return c / 8.0

    n_ocean = nbr_count(masks["ocean"])
    n_settle = nbr_count(masks["settlement"])
    n_port = nbr_count(masks["port"])
    n_forest = nbr_count(masks["forest"])
    n_mountain = nbr_count(masks["mountain"])
    n_plains = nbr_count(masks["plains"])
    n_ruin = nbr_count(masks["ruin"])

    land = 1.0 - masks["ocean"]
    is_coastal = (n_ocean > 0).astype(np.float32) * land
    has_settle_nbr = (n_settle > 0).astype(np.float32)
    n_settle_nbr = n_settle * 8

    def dist_norm(mask, max_d=20):
        if mask.sum() == 0:
            return np.ones((h, w), dtype=np.float32)
        return np.clip(distance_transform_edt(1 - mask) / max_d, 0, 1).astype(np.float32)

    dist_settle = dist_norm(masks["settlement"])
    dist_ocean = dist_norm(masks["ocean"])
    dist_port = dist_norm(masks["port"])
    dist_forest = dist_norm(masks["forest"])

    settle_d3 = gaussian_filter(masks["settlement"], sigma=3).astype(np.float32)
    settle_d5 = gaussian_filter(masks["settlement"], sigma=5).astype(np.float32)
    settle_d7 = gaussian_filter(masks["settlement"], sigma=7).astype(np.float32)
    forest_d3 = gaussian_filter(masks["forest"], sigma=3).astype(np.float32)
    forest_d5 = gaussian_filter(masks["forest"], sigma=5).astype(np.float32)
    port_d3 = gaussian_filter(masks["port"], sigma=3).astype(np.float32)

    row_norm = np.repeat(np.linspace(0, 1, h)[:, None], w, axis=1).astype(np.float32)
    col_norm = np.repeat(np.linspace(0, 1, w)[None, :], h, axis=0).astype(np.float32)

    n_land_nbr = nbr_count(land)
    div = np.zeros((h, w), dtype=np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            shifted = np.zeros_like(grid)
            r_src = slice(max(0, -dy), min(h, h - dy))
            c_src = slice(max(0, -dx), min(w, w - dx))
            r_dst = slice(max(0, dy), min(h, h + dy))
            c_dst = slice(max(0, dx), min(w, w + dx))
            shifted[r_dst, c_dst] = grid[r_src, c_src]
            div += (shifted != grid).astype(np.float32)
    terrain_div = div / 8.0

    # 3 hidden params broadcast to all cells
    ss_arr = np.full((h, w), settle_survive, dtype=np.float32)
    st_arr = np.full((h, w), spread_tendency, dtype=np.float32)
    pa_arr = np.full((h, w), port_activity, dtype=np.float32)

    # 7 settlement stats broadcast to all cells
    ss_dict = settlement_stats or DEFAULT_SETTLEMENT_STATS
    mp_arr = np.full((h, w), ss_dict.get("mean_population", DEFAULT_SETTLEMENT_STATS["mean_population"]), dtype=np.float32)
    mf_arr = np.full((h, w), ss_dict.get("mean_food", DEFAULT_SETTLEMENT_STATS["mean_food"]), dtype=np.float32)
    mw_arr = np.full((h, w), ss_dict.get("mean_wealth", DEFAULT_SETTLEMENT_STATS["mean_wealth"]), dtype=np.float32)
    md_arr = np.full((h, w), ss_dict.get("mean_defense", DEFAULT_SETTLEMENT_STATS["mean_defense"]), dtype=np.float32)
    nf_arr = np.full((h, w), ss_dict.get("n_factions", DEFAULT_SETTLEMENT_STATS["n_factions"]), dtype=np.float32)
    pr_arr = np.full((h, w), ss_dict.get("port_ratio", DEFAULT_SETTLEMENT_STATS["port_ratio"]), dtype=np.float32)
    ar_arr = np.full((h, w), ss_dict.get("alive_ratio", DEFAULT_SETTLEMENT_STATS["alive_ratio"]), dtype=np.float32)

    feature_maps = [
        grid.astype(np.float32),
        n_ocean, n_settle, n_port, n_forest, n_mountain, n_plains, n_ruin,
        is_coastal, has_settle_nbr, n_settle_nbr,
        dist_settle, dist_ocean, dist_port, dist_forest,
        settle_d3, settle_d5, settle_d7,
        forest_d3, forest_d5,
        port_d3,
        row_norm, col_norm,
        n_land_nbr, terrain_div,
        ss_arr, st_arr, pa_arr,
        mp_arr, mf_arr, mw_arr, md_arr, nf_arr, pr_arr, ar_arr,
    ]

    return np.stack([f.ravel() for f in feature_maps], axis=1)


# ============================================================
# Data loading
# ============================================================
def load_v2_data(exclude_rounds=None):
    """Load training data. Hidden params computed from GT."""
    exclude = set(exclude_rounds or [])
    samples = []
    seen_rounds = set()

    # R1-R12 from v2_R files
    for f in sorted(V2_DATA_DIR.glob("v2_R*.json")):
        if f.stem.count("_") > 1:
            continue
        with open(f) as fh:
            d = json.load(fh)
        rnum = d["round_number"]
        if rnum in exclude or rnum in seen_rounds:
            continue
        seen_rounds.add(rnum)

        for sid in ["0", "1", "2", "3", "4"]:
            seed = d["seeds"][sid]
            ig = np.array(seed["initial_grid"], dtype=np.int32)
            gt = np.array(seed["ground_truth"], dtype=np.float32)
            if ig.shape != (GRID_SIZE, GRID_SIZE) or gt.shape != (GRID_SIZE, GRID_SIZE, N_CLASSES):
                continue
            ss, st, pa = compute_hidden_params(ig, gt)
            samples.append({
                "grid": ig, "gt": gt,
                "ss": ss, "st": st, "pa": pa,
                "round": rnum, "seed": int(sid),
            })

    # R13+ from v2 variant files or round_data
    for extra in ["v2_R13_baseline.json", "v2_depth_R14.json", "v2_R16.json"]:
        path = V2_DATA_DIR / extra
        if not path.exists():
            continue
        with open(path) as fh:
            d = json.load(fh)
        rnum = d["round_number"]
        if rnum in exclude or rnum in seen_rounds:
            continue
        seen_rounds.add(rnum)
        for sid in ["0", "1", "2", "3", "4"]:
            seed = d["seeds"][sid]
            ig = np.array(seed["initial_grid"], dtype=np.int32)
            gt = np.array(seed["ground_truth"], dtype=np.float32)
            if ig.shape != (GRID_SIZE, GRID_SIZE) or gt.shape != (GRID_SIZE, GRID_SIZE, N_CLASSES):
                continue
            ss, st, pa = compute_hidden_params(ig, gt)
            samples.append({
                "grid": ig, "gt": gt,
                "ss": ss, "st": st, "pa": pa,
                "round": rnum, "seed": int(sid),
            })

    # Remaining rounds from round_data + submit files
    # Submit files have per-seed grids + settlement stats
    # Round files have GT
    for f in sorted(ROUND_DATA_DIR.glob("round_*.json")):
        if "_submit" in f.name:
            continue
        with open(f) as fh:
            d = json.load(fh)
        rnum = d.get("round_number")
        if rnum is None or rnum in exclude or rnum in seen_rounds:
            continue
        seeds = d.get("seeds", [])
        if isinstance(seeds, dict):
            seeds = list(seeds.values())
        has_gt = any(s.get("ground_truth") is not None for s in seeds if isinstance(s, dict))
        if not has_gt:
            continue

        # Load submit file for per-seed grids + settlement stats
        submit_path = ROUND_DATA_DIR / f"round_{rnum:02d}_submit.json"
        submit_data = {}
        if submit_path.exists():
            try:
                with open(submit_path) as fh:
                    submit_data = json.load(fh)
            except Exception:
                pass
        submit_seeds = submit_data.get("seeds", {})

        seen_rounds.add(rnum)
        for s in seeds:
            if not isinstance(s, dict):
                continue
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt, dtype=np.float32)
            sid = s.get("seed_index", 0)

            # Per-seed grid: prefer submit file > seed data > round-level
            sub_seed = submit_seeds.get(str(sid), {})
            ig_raw = sub_seed.get("initial_grid") or s.get("initial_grid") or d.get("initial_grid")
            ig = np.array(ig_raw, dtype=np.int32)
            if ig.shape != (GRID_SIZE, GRID_SIZE) or gt.shape != (GRID_SIZE, GRID_SIZE, N_CLASSES):
                continue

            ss, st, pa = compute_hidden_params(ig, gt)

            # Settlement stats from submit file
            sett_stats = sub_seed.get("settlement_stats")

            samples.append({
                "grid": ig, "gt": gt,
                "ss": ss, "st": st, "pa": pa,
                "settlement_stats": sett_stats,
                "round": rnum, "seed": sid,
            })

    log.info(f"Loaded {len(samples)} samples from {len(seen_rounds)} rounds: {sorted(seen_rounds)}")
    return samples


def build_training_arrays(samples):
    """Convert samples to (X, Y) arrays."""
    n_cells = GRID_SIZE * GRID_SIZE
    n_features = len(FEATURE_NAMES)

    X = np.zeros((len(samples) * n_cells, n_features), dtype=np.float32)
    Y = np.zeros((len(samples) * n_cells, N_CLASSES), dtype=np.float32)

    for i, s in enumerate(samples):
        start = i * n_cells
        end = start + n_cells
        X[start:end] = extract_features(s["grid"], s["ss"], s["st"], s["pa"], s.get("settlement_stats"))
        Y[start:end] = s["gt"].reshape(n_cells, N_CLASSES)

    return X, Y


# ============================================================
# Model training
# ============================================================
LGB_PARAMS = {
    "objective": "regression",
    "metric": "mse",
    "n_estimators": 1000,
    "max_depth": 7,
    "learning_rate": 0.03,
    "min_child_samples": 30,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.05,
    "reg_lambda": 0.5,
    "device": "gpu",
    "verbose": -1,
    "n_jobs": -1,
    "random_state": 42,
}


def train_models(X, Y):
    models = []
    t0 = time.time()
    for k in range(N_CLASSES):
        tk = time.time()
        model = lgb.LGBMRegressor(**LGB_PARAMS)
        model.fit(X, Y[:, k], categorical_feature=[0])
        models.append(model)
        log.info(f"  Class {k}/{N_CLASSES}: {time.time()-tk:.1f}s (total {time.time()-t0:.0f}s)")
    return models


def save_models(models):
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    for k, m in enumerate(models):
        joblib.dump(m, CHECKPOINT_DIR / f"lgbm_class_{k}.joblib")
    log.info(f"Saved {len(models)} models to {CHECKPOINT_DIR}")


def load_models():
    """Load V3 models from checkpoints_v3/."""
    models = []
    for k in range(N_CLASSES):
        p = CHECKPOINT_V3_DIR / f"lgbm_v3_class_{k}.joblib"
        if not p.exists():
            log.error(f"V3 checkpoint missing: {p}")
            return None
        models.append(joblib.load(p))
    expected = len(FEATURE_NAMES) + 6 + N_OBS_DENSITY_FEATURES  # 35 + 6 + 4 = 45
    actual = models[0].n_features_
    if actual != expected:
        log.error(f"V3 checkpoint has {actual} features, expected {expected}!")
        return None
    log.info(f"Loaded V3 models from {CHECKPOINT_V3_DIR} ({actual} features)")
    return models


# ============================================================
# Prediction (V3: base features + distance prior features)
# ============================================================
def predict_grid(models, grid, settle_survive=None, spread_tendency=None, port_activity=None,
                 obs_probs=None, n_obs=None, settlement_stats=None, query_grids=None):
    """Predict 40x40x6 using V4 model (41 base+prior + 4 obs density = 45 features)."""
    grid = np.asarray(grid, dtype=np.int32)

    ss = settle_survive if settle_survive is not None else DEFAULT_SETTLE_SURVIVE
    st = spread_tendency if spread_tendency is not None else DEFAULT_SPREAD_TENDENCY
    pa = port_activity if port_activity is not None else DEFAULT_PORT_ACTIVITY

    exp_rate = estimate_expansion_rate(grid, settlement_stats)
    log.info(f"  V4 predict: exp_rate={exp_rate:.3f} (n_sett={settlement_stats.get('n_settlements', '?') if settlement_stats else '?'})")

    # Base features (35)
    X_base = extract_features(grid, ss, st, pa, settlement_stats)

    # Prior features (6)
    prior = compute_prior_features(grid, exp_rate)
    prior_flat = prior.reshape(GRID_SIZE * GRID_SIZE, 6)

    # Obs settlement density features (4)
    n_total = len(FEATURE_NAMES) + 6 + N_OBS_DENSITY_FEATURES
    X = np.zeros((GRID_SIZE * GRID_SIZE, n_total), dtype=np.float32)
    X[:, :len(FEATURE_NAMES)] = X_base
    X[:, len(FEATURE_NAMES):len(FEATURE_NAMES)+6] = prior_flat

    if query_grids:
        d1, d2, d3, smap = compute_obs_settle_density(query_grids)
        X[:, -4] = d1.ravel()
        X[:, -3] = d2.ravel()
        X[:, -2] = d3.ravel()
        X[:, -1] = smap.ravel()
        log.info(f"  Obs density: {int(smap.sum())} settlements from queries")

    preds = np.zeros((GRID_SIZE * GRID_SIZE, N_CLASSES), dtype=np.float64)
    for k, model in enumerate(models):
        preds[:, k] = model.predict(X)

    pred = preds.reshape(GRID_SIZE, GRID_SIZE, N_CLASSES)
    ocean_mask = grid == 10
    mountain_mask = grid == 5

    # Bayesian Dirichlet update with observations (if available)
    EQUIV_SAMPLES = 30
    if obs_probs is not None and n_obs is not None:
        obs_probs = np.asarray(obs_probs, dtype=np.float32)
        n_obs = np.asarray(n_obs, dtype=np.float32)
        observed = n_obs > 0
        if observed.any():
            obs_counts = obs_probs * n_obs[:, :, np.newaxis]
            alpha = pred * EQUIV_SAMPLES + obs_counts
            alpha_sum = alpha.sum(axis=-1, keepdims=True)
            pred[observed] = (alpha / alpha_sum)[observed]
            log.info(f"  Bayesian update: {observed.sum()} cells, equiv={EQUIV_SAMPLES}")

    # Per-class floors and renormalize
    for k in range(N_CLASSES):
        pred[:, :, k] = np.clip(pred[:, :, k], CLASS_FLOORS[k], None)
    pred = pred / pred.sum(axis=-1, keepdims=True)

    # Static overrides LAST (after all processing)
    if ocean_mask.any():
        pred[ocean_mask] = 0.0
        pred[ocean_mask, 0] = 1.0
    if mountain_mask.any():
        pred[mountain_mask] = 0.0
        pred[mountain_mask, 5] = 1.0
    return pred


# ============================================================
# Scoring
# ============================================================
def score_prediction(pred, gt):
    pred = np.clip(pred, PROB_FLOOR, None)
    pred = pred / pred.sum(axis=-1, keepdims=True)
    gt_s = np.clip(gt, 1e-10, None)
    pred_s = np.clip(pred, 1e-10, None)
    entropy = -np.sum(gt_s * np.log(gt_s), axis=-1)
    kl = np.sum(gt_s * (np.log(gt_s) - np.log(pred_s)), axis=-1)
    total_entropy = entropy.sum()
    if total_entropy < 1e-8:
        return 100.0
    weighted_kl = (entropy * kl).sum() / total_entropy
    return max(0.0, min(100.0, 100.0 * math.exp(-3.0 * weighted_kl)))


# ============================================================
# Global state
# ============================================================
_models = None


def _ensure_models():
    global _models
    if _models is not None:
        return
    # Load distance priors (required for V3)
    if not _load_distance_priors():
        log.error("Cannot load distance priors! V3 will not work.")
        _models = []
        return
    _models = load_models()
    if _models is not None:
        return
    log.error("V3 checkpoints not found! Run train_v3.py --retrain first.")
    _models = []


# ============================================================
# API entry point
# ============================================================
def predict(body: dict) -> dict:
    _ensure_models()
    initial_grid = body.get("initial_grid")
    if initial_grid is None:
        return {"error": "missing initial_grid"}
    grid = np.array(initial_grid, dtype=np.int32)
    if grid.shape != (GRID_SIZE, GRID_SIZE):
        return {"error": f"expected {GRID_SIZE}x{GRID_SIZE}, got {grid.shape}"}

    settlement_stats = body.get("settlement_stats")
    query_grids = body.get("query_grids")
    pred = predict_grid(_models, grid, settlement_stats=settlement_stats,
                         query_grids=query_grids)
    return {"prediction": pred.tolist()}


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import sys
    if "--delete-checkpoints" in sys.argv:
        import shutil
        if CHECKPOINT_DIR.exists():
            shutil.rmtree(CHECKPOINT_DIR)
            log.info("Deleted checkpoints")

    if "--cv" in sys.argv:
        samples = load_v2_data()
        rounds = {}
        for s in samples:
            rounds.setdefault(s["round"], []).append(s)
        round_nums = sorted(rounds.keys())
        all_scores = []
        cv_start = time.time()
        for fold_i, test_rn in enumerate(round_nums):
            train = [s for rn in round_nums if rn != test_rn for s in rounds[rn]]
            test = rounds[test_rn]
            X, Y = build_training_arrays(train)
            models = train_models(X, Y)
            seed_scores = []
            for s in test:
                pred = predict_grid(models, s["grid"], s["ss"], s["st"], s["pa"])
                seed_scores.append(score_prediction(pred, s["gt"]))
            mean = np.mean(seed_scores)
            all_scores.append(mean)
            elapsed = time.time() - cv_start
            eta = elapsed / (fold_i + 1) * (len(round_nums) - fold_i - 1)
            log.info(f"  R{test_rn:2d}: {mean:.1f}  seeds=[{' '.join(f'{s:.1f}' for s in seed_scores)}]  [ETA {eta:.0f}s]")
        log.info(f"\n  LOO Mean: {np.mean(all_scores):.1f} (total {time.time()-cv_start:.0f}s)")
    else:
        # Train on all, save
        samples = load_v2_data()
        X, Y = build_training_arrays(samples)
        log.info(f"Training on all: X={X.shape}")
        models = train_models(X, Y)
        save_models(models)
        _models = models
