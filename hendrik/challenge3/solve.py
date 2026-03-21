"""
Challenge 3: Astar Island — Per-cell LightGBM prediction.
Trains on v2_R data (per-seed grids) with observation features from queries.
"""

import json
import logging
import math
import random
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
    # Observation features (8)
    "obs_p_empty", "obs_p_settle", "obs_p_port", "obs_p_ruin", "obs_p_forest", "obs_p_mountain",
    "n_obs_norm", "has_obs",
]

# Dropout rate: probability of zeroing obs features during training
OBS_DROPOUT = 0.3


# ============================================================
# Observation reconstruction
# ============================================================
def reconstruct_observations(queries):
    """Reconstruct observed_counts/probs/n_obs from viewport query results."""
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
                    code = int(qgrid[dr, dc])
                    cls = TERRAIN_TO_CLASS.get(code, 0)
                    obs_counts[r, c, cls] += 1
                    n_obs[r, c] += 1

    obs_probs = np.zeros((GRID_SIZE, GRID_SIZE, N_CLASSES), dtype=np.float32)
    mask = n_obs > 0
    obs_probs[mask] = obs_counts[mask] / n_obs[mask, None]
    return obs_probs, n_obs


# ============================================================
# Feature extraction
# ============================================================
def extract_features(grid, is_warm, expansion_rate, obs_probs=None, n_obs=None):
    """Extract per-cell features. Returns (1600, n_features)."""
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

    warm_arr = np.full((h, w), float(is_warm), dtype=np.float32)
    exp_arr = np.full((h, w), expansion_rate, dtype=np.float32)

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

    # Observation features
    if obs_probs is not None and n_obs is not None:
        obs_probs = np.asarray(obs_probs, dtype=np.float32)
        n_obs = np.asarray(n_obs, dtype=np.float32)
        obs_feat = [obs_probs[:, :, k] for k in range(N_CLASSES)]
        obs_feat.append(n_obs / 10.0)  # normalized
        obs_feat.append((n_obs > 0).astype(np.float32))
    else:
        obs_feat = [np.zeros((h, w), dtype=np.float32) for _ in range(N_CLASSES + 2)]

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
        *obs_feat,
    ]

    return np.stack([f.ravel() for f in feature_maps], axis=1)


# ============================================================
# Data loading
# ============================================================
def load_v2_data(exclude_rounds=None):
    """Load training data from v2_R files (R1-R12) + round_data (R13+)."""
    exclude = set(exclude_rounds or [])
    samples = []
    seen_rounds = set()

    # Config mapping from v2_R files
    config_map = {}
    for f in sorted(V2_DATA_DIR.glob("v2_R*.json")):
        # Skip variant files (v2_R9_threshold90.json etc)
        name = f.stem
        if name.count("_") > 1:
            continue
        with open(f) as fh:
            d = json.load(fh)
        rnum = d["round_number"]
        config_map[rnum] = d.get("config", {})
        config_map[d.get("round_id", "")] = d.get("config", {})

    # Load from v2_R files (R1-R12, have per-seed grids + queries)
    for f in sorted(V2_DATA_DIR.glob("v2_R*.json")):
        name = f.stem
        if name.count("_") > 1:
            continue
        with open(f) as fh:
            d = json.load(fh)
        rnum = d["round_number"]
        if rnum in exclude or rnum in seen_rounds:
            continue
        seen_rounds.add(rnum)
        config = d.get("config", {})
        is_warm = config.get("warmth", "warm") == "warm"
        exp_rate = config.get("expansion_rate", 0.15)

        for sid in ["0", "1", "2", "3", "4"]:
            seed = d["seeds"][sid]
            ig = np.array(seed["initial_grid"], dtype=np.int32)
            gt = np.array(seed["ground_truth"], dtype=np.float32)
            if ig.shape != (GRID_SIZE, GRID_SIZE) or gt.shape != (GRID_SIZE, GRID_SIZE, N_CLASSES):
                continue
            queries = seed.get("queries", [])
            obs_probs, n_obs = reconstruct_observations(queries) if queries else (None, None)
            samples.append({
                "grid": ig, "gt": gt, "is_warm": is_warm,
                "expansion_rate": exp_rate, "round": rnum, "seed": int(sid),
                "obs_probs": obs_probs, "n_obs": n_obs,
            })

    # Load from round_data (R13+ that have per-seed grids and GT)
    for f in sorted(ROUND_DATA_DIR.glob("round_*.json")):
        with open(f) as fh:
            d = json.load(fh)
        rnum = d.get("round_number")
        if rnum is None or rnum in exclude or rnum in seen_rounds:
            continue
        # Need GT to be useful for training
        seeds = d.get("seeds", [])
        if isinstance(seeds, dict):
            seeds = list(seeds.values())
        has_gt = any(s.get("ground_truth") is not None for s in seeds if isinstance(s, dict))
        if not has_gt:
            continue

        # Get config from mapping or estimate
        rid = d.get("round_id", "")
        cfg = config_map.get(rnum, config_map.get(rid, {}))
        is_warm = cfg.get("warmth", "warm") == "warm" if cfg else True
        exp_rate = cfg.get("expansion_rate", 0.15) if cfg else 0.15

        seen_rounds.add(rnum)
        for s in seeds:
            gt = s.get("ground_truth")
            if gt is None:
                continue
            gt = np.array(gt, dtype=np.float32)
            # Per-seed grid if available, else round-level grid
            ig_raw = s.get("initial_grid") or d.get("initial_grid")
            ig = np.array(ig_raw, dtype=np.int32)
            if ig.shape != (GRID_SIZE, GRID_SIZE) or gt.shape != (GRID_SIZE, GRID_SIZE, N_CLASSES):
                continue

            # Observations from query_grids or pre-aggregated
            obs_probs, n_obs = None, None
            if s.get("query_grids"):
                obs_probs, n_obs = reconstruct_observations(s["query_grids"])
            elif s.get("observed_probs") and s.get("n_observations"):
                obs_probs = np.array(s["observed_probs"], dtype=np.float32)
                n_obs = np.array(s["n_observations"], dtype=np.int32)

            samples.append({
                "grid": ig, "gt": gt, "is_warm": is_warm,
                "expansion_rate": exp_rate, "round": rnum,
                "seed": s.get("seed_index", 0),
                "obs_probs": obs_probs, "n_obs": n_obs,
            })

    log.info(f"Loaded {len(samples)} samples from {len(seen_rounds)} rounds: {sorted(seen_rounds)}")
    return samples


def build_training_arrays(samples, augment=False):
    """Convert samples to (X, Y) with D4 augmentation and observation dropout."""
    n_cells = GRID_SIZE * GRID_SIZE
    n_features = len(FEATURE_NAMES)
    n_augs = 8 if augment else 1
    total = len(samples) * n_augs

    X = np.zeros((total * n_cells, n_features), dtype=np.float32)
    Y = np.zeros((total * n_cells, N_CLASSES), dtype=np.float32)

    rng = random.Random(42)
    idx = 0
    for s in samples:
        grid = s["grid"]
        gt = s["gt"]
        obs_probs = s.get("obs_probs")
        n_obs_arr = s.get("n_obs")

        for k in range(n_augs):
            g = np.rot90(grid, k % 4)
            t = np.rot90(gt, k % 4)
            if obs_probs is not None:
                op = np.rot90(obs_probs, k % 4)
                no = np.rot90(n_obs_arr, k % 4)
            else:
                op, no = None, None
            if k >= 4:
                g = np.fliplr(g)
                t = np.fliplr(t)
                if op is not None:
                    op = np.fliplr(op)
                    no = np.fliplr(no)
            g = np.ascontiguousarray(g)
            t = np.ascontiguousarray(t)

            # Observation dropout: randomly zero out obs features
            use_obs = op is not None and rng.random() > OBS_DROPOUT
            if use_obs:
                op = np.ascontiguousarray(op)
                no = np.ascontiguousarray(no)
            else:
                op, no = None, None

            start = idx * n_cells
            end = start + n_cells
            X[start:end] = extract_features(g, s["is_warm"], s["expansion_rate"], op, no)
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
    log.info(f"Loaded {len(models)} models from {CHECKPOINT_DIR}")
    return models


# ============================================================
# Prediction
# ============================================================
def predict_grid(models, grid, is_warm, expansion_rate, obs_probs=None, n_obs=None):
    """Predict 40x40x6 probability distribution."""
    grid = np.asarray(grid, dtype=np.int32)
    X = extract_features(grid, is_warm, expansion_rate, obs_probs, n_obs)

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

    # Per-class floor and renormalize
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
    """LOO-CV with observation features."""
    samples = load_v2_data()
    rounds = {}
    for s in samples:
        rounds.setdefault(s["round"], []).append(s)
    round_nums = sorted(rounds.keys())

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
            pred = predict_grid(models, s["grid"], s["is_warm"], s["expansion_rate"],
                                s.get("obs_probs"), s.get("n_obs"))
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
# Train-on-all
# ============================================================
def eval_train_on_all():
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
            pred = predict_grid(models, s["grid"], s["is_warm"], s["expansion_rate"],
                                s.get("obs_probs"), s.get("n_obs"))
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

    # Default config
    is_warm, exp_rate = True, 0.15

    # Use observations if provided
    obs_probs, n_obs_arr = None, None
    if "observed_probs" in body and "n_observations" in body:
        obs_probs = np.array(body["observed_probs"], dtype=np.float32)
        n_obs_arr = np.array(body["n_observations"], dtype=np.float32)

    pred = predict_grid(_models, grid, is_warm, exp_rate, obs_probs, n_obs_arr)
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
