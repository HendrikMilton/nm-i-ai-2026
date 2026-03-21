"""
Challenge 3: Astar Island — Per-cell LightGBM prediction.
Uses 3 round-level hidden params (settle_survive, spread_tendency, port_activity)
derived from GT (training) or observations (inference).
"""

import json
import logging
import math
import glob as glob_module
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter
import lightgbm as lgb
import joblib

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ============================================================
# Constants
# ============================================================
GRID_SIZE = 40
N_CLASSES = 6
PROB_FLOOR = 0.01
TERRAIN_TO_CLASS = {0: 0, 10: 0, 11: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}

CHECKPOINT_DIR = Path(__file__).parent / "checkpoints"
V2_DATA_DIR = Path(__file__).parent / "../../elias/logs/offline"
ROUND_DATA_DIR = Path(__file__).parent / "round_data"

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
    # 3 round-level hidden params
    "settle_survive", "spread_tendency", "port_activity",
]


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
def extract_features(grid, settle_survive, spread_tendency, port_activity):
    """Extract per-cell features + 3 round-level hidden params. Returns (1600, 28)."""
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

    # Remaining rounds from round_data (with per-seed grids)
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
        seen_rounds.add(rnum)
        for s in seeds:
            if not isinstance(s, dict):
                continue
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt, dtype=np.float32)
            ig_raw = s.get("initial_grid") or d.get("initial_grid")
            ig = np.array(ig_raw, dtype=np.int32)
            if ig.shape != (GRID_SIZE, GRID_SIZE) or gt.shape != (GRID_SIZE, GRID_SIZE, N_CLASSES):
                continue
            ss, st, pa = compute_hidden_params(ig, gt)
            samples.append({
                "grid": ig, "gt": gt,
                "ss": ss, "st": st, "pa": pa,
                "round": rnum, "seed": s.get("seed_index", 0),
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
        X[start:end] = extract_features(s["grid"], s["ss"], s["st"], s["pa"])
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
    models = []
    for k in range(N_CLASSES):
        p = CHECKPOINT_DIR / f"lgbm_class_{k}.joblib"
        if not p.exists():
            return None
        models.append(joblib.load(p))
    # Verify feature count matches
    expected = len(FEATURE_NAMES)
    actual = models[0].n_features_
    if actual != expected:
        log.warning(f"Checkpoint has {actual} features, expected {expected}. Retraining.")
        return None
    log.info(f"Loaded {len(models)} models from {CHECKPOINT_DIR}")
    return models


# ============================================================
# Prediction
# ============================================================
def predict_grid(models, grid, settle_survive=None, spread_tendency=None, port_activity=None,
                 obs_probs=None, n_obs=None):
    """Predict 40x40x6 probability distribution.

    Hidden params can be provided directly, or estimated from obs, or use defaults.
    """
    grid = np.asarray(grid, dtype=np.int32)

    # Determine hidden params
    if settle_survive is not None and spread_tendency is not None and port_activity is not None:
        ss, st, pa = settle_survive, spread_tendency, port_activity
    elif obs_probs is not None and n_obs is not None:
        ss, st, pa = compute_hidden_params_from_obs(grid, obs_probs, n_obs)
        log.info(f"  Estimated params from obs: ss={ss:.3f} st={st:.3f} pa={pa:.3f}")
    else:
        ss, st, pa = DEFAULT_SETTLE_SURVIVE, DEFAULT_SPREAD_TENDENCY, DEFAULT_PORT_ACTIVITY

    X = extract_features(grid, ss, st, pa)

    preds = np.zeros((GRID_SIZE * GRID_SIZE, N_CLASSES), dtype=np.float64)
    for k, model in enumerate(models):
        preds[:, k] = model.predict(X)

    pred = preds.reshape(GRID_SIZE, GRID_SIZE, N_CLASSES)

    # Static overrides
    ocean_mask = grid == 10
    mountain_mask = grid == 5
    if ocean_mask.any():
        pred[ocean_mask] = 0.0
        pred[ocean_mask, 0] = 1.0
    if mountain_mask.any():
        pred[mountain_mask] = 0.0
        pred[mountain_mask, 5] = 1.0

    # Floor and renormalize
    pred = np.clip(pred, PROB_FLOOR, None)
    pred = pred / pred.sum(axis=-1, keepdims=True)
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
    _models = load_models()
    if _models is not None:
        return
    log.info("Training models from scratch...")
    samples = load_v2_data()
    if not samples:
        log.error("No training data!")
        _models = []
        return
    X, Y = build_training_arrays(samples)
    log.info(f"Training: X={X.shape}, Y={Y.shape}")
    _models = train_models(X, Y)
    save_models(_models)


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

    pred = predict_grid(_models, grid)
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
