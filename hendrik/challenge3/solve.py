"""
Challenge 3: Astar Island — Per-cell LightGBM prediction.
Trains on v2_R data (which has per-seed grids).
"""

import json
import logging
import math
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

CHECKPOINT_DIR = Path(__file__).parent / "checkpoints"
V2_DATA_DIR = Path(__file__).parent / "../../elias/logs/offline"

FEATURE_NAMES = [
    "terrain_code",
    "n_ocean", "n_settlement", "n_port", "n_forest", "n_mountain", "n_plains", "n_ruin",
    "is_coastal", "has_settle_nbr", "n_settle_nbr",
    "dist_to_settlement", "dist_to_ocean", "dist_to_port", "dist_to_forest",
    "settle_density_r3", "settle_density_r5", "settle_density_r7",
    "forest_density_r3", "forest_density_r5",
    "port_density_r3",
    "is_warm", "expansion_rate",
    "row_norm", "col_norm",
    "n_land_nbr", "terrain_diversity",
]


# ============================================================
# Feature extraction
# ============================================================
def extract_features(grid, is_warm, expansion_rate):
    """Extract per-cell features for a 40x40 grid. Returns (1600, n_features)."""
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
    n_settle_nbr = n_settle * 8  # un-normalize to get actual count

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

    warm_arr = np.full((h, w), float(is_warm), dtype=np.float32)
    exp_arr = np.full((h, w), expansion_rate, dtype=np.float32)

    n_land_nbr = nbr_count(land)
    # Terrain diversity: count of unique terrain types in 3x3 neighborhood
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

    feature_maps = [
        grid.astype(np.float32),
        n_ocean, n_settle, n_port, n_forest, n_mountain, n_plains, n_ruin,
        is_coastal, has_settle_nbr, n_settle_nbr,
        dist_settle, dist_ocean, dist_port, dist_forest,
        settle_d3, settle_d5, settle_d7,
        forest_d3, forest_d5,
        port_d3,
        warm_arr, exp_arr,
        row_norm, col_norm,
        n_land_nbr, terrain_div,
    ]

    return np.stack([f.ravel() for f in feature_maps], axis=1)


# ============================================================
# Data loading from v2_R files (per-seed grids!)
# ============================================================
def load_v2_data():
    """Load all v2_R rounds. Each seed has its own initial_grid."""
    samples = []
    for f in sorted(V2_DATA_DIR.glob("v2_R*.json")):
        with open(f) as fh:
            d = json.load(fh)
        rnum = d["round_number"]
        config = d.get("config", {})
        is_warm = config.get("warmth", "warm") == "warm"
        exp_rate = config.get("expansion_rate", 0.15)

        for sid in ["0", "1", "2", "3", "4"]:
            seed = d["seeds"][sid]
            ig = np.array(seed["initial_grid"], dtype=np.int32)
            gt = np.array(seed["ground_truth"], dtype=np.float32)
            if ig.shape == (GRID_SIZE, GRID_SIZE) and gt.shape == (GRID_SIZE, GRID_SIZE, N_CLASSES):
                samples.append({
                    "grid": ig,
                    "gt": gt,
                    "is_warm": is_warm,
                    "expansion_rate": exp_rate,
                    "round": rnum,
                    "seed": int(sid),
                })

    log.info(f"Loaded {len(samples)} samples from v2_R data ({len(samples)//5} rounds x 5 seeds)")
    return samples


def build_training_arrays(samples, augment=True):
    """Convert samples to (X, Y) arrays with optional D4 augmentation."""
    n_cells = GRID_SIZE * GRID_SIZE
    n_features = len(FEATURE_NAMES)
    n_augs = 8 if augment else 1
    total = len(samples) * n_augs

    X = np.zeros((total * n_cells, n_features), dtype=np.float32)
    Y = np.zeros((total * n_cells, N_CLASSES), dtype=np.float32)

    idx = 0
    for s in samples:
        grid = s["grid"]
        gt = s["gt"]
        for k in range(n_augs):
            # D4 transform: k%4 rotations, k>=4 adds flip
            g = np.rot90(grid, k % 4)
            t = np.rot90(gt, k % 4)
            if k >= 4:
                g = np.fliplr(g)
                t = np.fliplr(t)
            g = np.ascontiguousarray(g)
            t = np.ascontiguousarray(t)

            start = idx * n_cells
            end = start + n_cells
            X[start:end] = extract_features(g, s["is_warm"], s["expansion_rate"])
            Y[start:end] = t.reshape(n_cells, N_CLASSES)
            idx += 1

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
    """Train 6 independent LightGBM regressors."""
    import time
    models = []
    t0 = time.time()
    for k in range(N_CLASSES):
        tk = time.time()
        model = lgb.LGBMRegressor(**LGB_PARAMS)
        model.fit(X, Y[:, k], categorical_feature=[0])
        models.append(model)
        elapsed = time.time() - tk
        log.info(f"  Class {k}/{N_CLASSES}: {elapsed:.1f}s (total {time.time()-t0:.0f}s)")
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
    log.info(f"Loaded {len(models)} models from {CHECKPOINT_DIR}")
    return models


# ============================================================
# Prediction
# ============================================================
def predict_grid(models, grid, is_warm, expansion_rate, observations=None):
    """Predict 40x40x6 probability distribution."""
    grid = np.asarray(grid, dtype=np.int32)
    X = extract_features(grid, is_warm, expansion_rate)

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

    # Observation blending
    if observations is not None:
        n_obs = observations.get("n_observations")
        obs_probs = observations.get("observed_probs") or observations.get("ground_truth_from_queries")
        if n_obs is not None and obs_probs is not None:
            n_obs = np.array(n_obs, dtype=np.float32)
            obs_probs = np.array(obs_probs, dtype=np.float32)
            has_obs = n_obs > 0
            if has_obs.any():
                obs_weight = np.clip(n_obs * 0.2, 0, 0.8)[:, :, None]
                pred[has_obs] = (
                    (1 - obs_weight[has_obs]) * pred[has_obs]
                    + obs_weight[has_obs] * obs_probs[has_obs]
                )

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
# Leave-one-round-out cross-validation
# ============================================================
def cross_validate():
    """LOO-CV using per-seed grids from v2_R data."""
    samples = load_v2_data()
    rounds = {}
    for s in samples:
        rounds.setdefault(s["round"], []).append(s)
    round_nums = sorted(rounds.keys())

    import time
    all_round_scores = []
    cv_start = time.time()
    for fold_i, test_rn in enumerate(round_nums):
        fold_start = time.time()
        train = [s for rn in round_nums if rn != test_rn for s in rounds[rn]]
        test = rounds[test_rn]

        log.info(f"  Fold {fold_i+1}/{len(round_nums)}: building features...")
        X_train, Y_train = build_training_arrays(train)
        log.info(f"  Fold {fold_i+1}/{len(round_nums)}: training on X={X_train.shape}...")
        models = train_models(X_train, Y_train)

        seed_scores = []
        for s in test:
            pred = predict_grid(models, s["grid"], s["is_warm"], s["expansion_rate"])
            sc = score_prediction(pred, s["gt"])
            seed_scores.append(sc)

        round_mean = np.mean(seed_scores)
        all_round_scores.append(round_mean)
        warmth = "warm" if test[0]["is_warm"] else "cold"
        fold_time = time.time() - fold_start
        elapsed = time.time() - cv_start
        eta = elapsed / (fold_i + 1) * (len(round_nums) - fold_i - 1)
        log.info(f"  R{test_rn:2d} ({warmth}): {round_mean:.1f}  seeds=[{' '.join(f'{s:.1f}' for s in seed_scores)}]  [{fold_time:.0f}s, ETA {eta:.0f}s]")

    mean = np.mean(all_round_scores)
    log.info(f"\n  LOO Mean: {mean:.1f} (total {time.time()-cv_start:.0f}s)")
    return mean


# ============================================================
# Train-on-all evaluation (sanity check)
# ============================================================
def eval_train_on_all():
    """Train on all data and evaluate (upper bound — no holdout)."""
    samples = load_v2_data()
    X, Y = build_training_arrays(samples)
    log.info(f"Training on all: X={X.shape}")
    models = train_models(X, Y)
    save_models(models)

    rounds = {}
    for s in samples:
        rounds.setdefault(s["round"], []).append(s)

    all_scores = []
    for rn in sorted(rounds.keys()):
        seed_scores = []
        for s in rounds[rn]:
            pred = predict_grid(models, s["grid"], s["is_warm"], s["expansion_rate"])
            sc = score_prediction(pred, s["gt"])
            seed_scores.append(sc)
        round_mean = np.mean(seed_scores)
        all_scores.append(round_mean)
        log.info(f"  R{rn:2d}: {round_mean:.1f}  seeds=[{' '.join(f'{s:.1f}' for s in seed_scores)}]")

    log.info(f"\n  Train-on-all Mean: {np.mean(all_scores):.1f}")
    return models


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

    # Default config — at competition time we'd estimate from queries
    is_warm, exp_rate = True, 0.15
    pred = predict_grid(_models, grid, is_warm, exp_rate)
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
        cross_validate()
    else:
        eval_train_on_all()
