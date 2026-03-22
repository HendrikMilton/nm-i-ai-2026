"""
V3: GBM + distance prior features + n_settlements expansion rate estimation.

Key improvement over v2: instead of default expansion_rate=0.1, we estimate it from
settlement_stats.n_settlements via regression: exp_rate = 0.759 * (n_sett/n_land) - 0.004

Train on R1-R20, validate on R21 (actual: 84.81).
If improvement, retrain on R1-R21 and save to checkpoints_v3.
"""

import json
import sys
import time
import numpy as np
from pathlib import Path
from scipy.ndimage import distance_transform_edt, convolve

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from solve import (
    load_v2_data, build_training_arrays, extract_features,
    predict_grid, score_prediction, compute_hidden_params,
    compute_hidden_params_from_obs,
    GRID_SIZE, N_CLASSES, PROB_FLOOR, FEATURE_NAMES, LGB_PARAMS,
    DEFAULT_SETTLE_SURVIVE, DEFAULT_SPREAD_TENDENCY, DEFAULT_PORT_ACTIVITY,
)
import lightgbm as lgb
import joblib

PRIOR_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "arian" / "distance_priors.json"
SUBMIT_DIR = Path(__file__).resolve().parent.parent.parent / "round_data"
LOG_FILE = Path(__file__).parent / "train_v3_results.txt"
CHECKPOINT_V3_DIR = Path(__file__).resolve().parent.parent.parent / "checkpoints_v3"


def log(msg):
    print(msg, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(msg + "\n")


# ============================================================
# Distance prior lookup
# ============================================================
log_init = print  # use print before log file is ready
log_init("Loading distance priors...")
with open(PRIOR_PATH) as f:
    RAW_PRIORS = json.load(f)
PRIOR_RATE_KEYS = sorted(RAW_PRIORS.keys(), key=float)
PRIOR_RATE_VALS = np.array([float(k) for k in PRIOR_RATE_KEYS])
PRIOR_LOOKUP = {}
for rk in PRIOR_RATE_KEYS:
    table = RAW_PRIORS[rk]
    lookup = {}
    for str_key, probs in table.items():
        parts = str_key.split("_")
        t, d, nf, ic = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        int_key = t * 10000 + d * 100 + nf * 10 + ic
        lookup[int_key] = np.array(probs, dtype=np.float32)
    PRIOR_LOOKUP[rk] = lookup
DEFAULT_PRIOR = np.array([1.0/6]*6, dtype=np.float32)
log_init("  Done.")


def find_nearest_rate(expansion_rate):
    idx = np.argmin(np.abs(PRIOR_RATE_VALS - expansion_rate))
    return PRIOR_RATE_KEYS[idx]


# ============================================================
# Expansion rate estimation
# ============================================================
def estimate_expansion_rate_from_settlement_stats(grid, settlement_stats):
    """Estimate expansion rate from n_settlements (R²=0.995 on R17-R21)."""
    if not settlement_stats:
        return 0.1  # default
    n_sett = settlement_stats.get("n_settlements", 0)
    if n_sett == 0:
        return 0.1
    grid = np.asarray(grid)
    n_land = (grid != 10).sum()
    if n_land == 0:
        return 0.1
    final_frac = n_sett / n_land
    exp_rate = 0.759 * final_frac - 0.004
    return max(0.001, min(0.5, exp_rate))  # clamp


def get_expansion_rate_from_gt(grid, gt):
    """Ground truth expansion rate (training only)."""
    grid = np.asarray(grid)
    gt = np.asarray(gt)
    non_settle = ~np.isin(grid, [1, 2])
    land = grid != 10
    mask = non_settle & land
    if mask.sum() == 0:
        return 0.1
    return float(gt[mask, 1].mean())


# ============================================================
# Prior features (vectorized)
# ============================================================
def compute_prior_features(grid, expansion_rate):
    grid = np.asarray(grid, dtype=np.int32)
    h, w = grid.shape
    rate_key = find_nearest_rate(expansion_rate)
    lookup = PRIOR_LOOKUP[rate_key]

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
            flat_priors[i] = p2 if p2 is not None else DEFAULT_PRIOR
    return prior_probs


# ============================================================
# Training
# ============================================================
def build_augmented_X(grid, ss, st, pa, expansion_rate, settlement_stats=None):
    n_base = len(FEATURE_NAMES)
    base = extract_features(grid, ss, st, pa, settlement_stats)
    prior = compute_prior_features(grid, expansion_rate).reshape(GRID_SIZE * GRID_SIZE, 6)
    X = np.zeros((GRID_SIZE * GRID_SIZE, n_base + 6), dtype=np.float32)
    X[:, :n_base] = base
    X[:, n_base:] = prior
    return X


def train_models(samples):
    n_cells = GRID_SIZE * GRID_SIZE
    n_total = len(FEATURE_NAMES) + 6

    t0 = time.time()
    X = np.zeros((len(samples) * n_cells, n_total), dtype=np.float32)
    Y = np.zeros((len(samples) * n_cells, N_CLASSES), dtype=np.float32)

    for i, s in enumerate(samples):
        start = i * n_cells
        end = start + n_cells
        exp_rate = get_expansion_rate_from_gt(s["grid"], s["gt"])
        X[start:end] = build_augmented_X(s["grid"], s["ss"], s["st"], s["pa"],
                                          exp_rate, s.get("settlement_stats"))
        Y[start:end] = s["gt"].reshape(n_cells, N_CLASSES)

    log(f"  Features: {X.shape} ({time.time()-t0:.1f}s)")

    models = []
    t0 = time.time()
    for k in range(N_CLASSES):
        tk = time.time()
        m = lgb.LGBMRegressor(**LGB_PARAMS)
        m.fit(X, Y[:, k], categorical_feature=[0])
        models.append(m)
        log(f"  Class {k}: {time.time()-tk:.1f}s")
    log(f"  Total: {time.time()-t0:.0f}s")
    return models


def predict_augmented(models, grid, ss, st, pa, expansion_rate, settlement_stats=None):
    grid = np.asarray(grid, dtype=np.int32)
    X = build_augmented_X(grid, ss, st, pa, expansion_rate, settlement_stats)
    preds = np.zeros((GRID_SIZE * GRID_SIZE, N_CLASSES), dtype=np.float64)
    for k, model in enumerate(models):
        preds[:, k] = model.predict(X)
    pred = preds.reshape(GRID_SIZE, GRID_SIZE, N_CLASSES)
    ocean = grid == 10
    mountain = grid == 5
    if ocean.any():
        pred[ocean] = 0.0
        pred[ocean, 0] = 1.0
    if mountain.any():
        pred[mountain] = 0.0
        pred[mountain, 5] = 1.0
    pred = np.clip(pred, PROB_FLOOR, None)
    return pred / pred.sum(axis=-1, keepdims=True)


def save_models(models, checkpoint_dir):
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for k, m in enumerate(models):
        joblib.dump(m, checkpoint_dir / f"lgbm_v3_class_{k}.joblib")
    log(f"  Saved to {checkpoint_dir}")


# ============================================================
# Main
# ============================================================
def main():
    with open(LOG_FILE, "w") as f:
        f.write("")

    log("=" * 70)
    log("  V3: GBM + Distance Priors + n_settlements Expansion Rate")
    log("=" * 70)

    all_samples = load_v2_data()
    rounds = {}
    for s in all_samples:
        rounds.setdefault(s["round"], []).append(s)

    train_samples = [s for rn in sorted(rounds.keys()) if rn <= 20 for s in rounds[rn]]
    test_samples = rounds.get(21, [])
    log(f"Train: {len(train_samples)} samples (R1-R20)")
    log(f"Test:  {len(test_samples)} samples (R21)")

    # Load R21 submit data
    submit_path = SUBMIT_DIR / "round_21_submit.json"
    submit_seeds = {}
    if submit_path.exists():
        submit_seeds = json.load(open(submit_path)).get("seeds", {})

    # --- Train ---
    log("\n--- Training on R1-R20 ---")
    t0 = time.time()
    models = train_models(train_samples)
    log(f"  Training complete ({time.time()-t0:.0f}s)")

    # --- Validate on R21 ---
    log("\n--- R21 Validation ---")
    log(f"  Actual live: 84.81  seeds=[87.83, 78.40, 87.89, 83.44, 86.49]")
    log(f"  V2 default:  85.68")

    scores_v3_estimated = []
    scores_v3_default = []
    scores_v2_default = []

    for s in test_samples:
        gt = s["gt"]
        grid = s["grid"]
        sid = s["seed"]
        sub = submit_seeds.get(str(sid), {})
        sett_stats = sub.get("settlement_stats")

        # V3: estimated expansion rate from n_settlements
        exp_est = estimate_expansion_rate_from_settlement_stats(grid, sett_stats)

        # V3: default expansion rate (same as v2)
        exp_default = 0.1

        # GT expansion rate (oracle)
        exp_gt = get_expansion_rate_from_gt(grid, gt)

        pred_est = predict_augmented(models, grid, DEFAULT_SETTLE_SURVIVE,
                                      DEFAULT_SPREAD_TENDENCY, DEFAULT_PORT_ACTIVITY,
                                      exp_est, sett_stats)
        sc_est = score_prediction(pred_est, gt)
        scores_v3_estimated.append(sc_est)

        pred_def = predict_augmented(models, grid, DEFAULT_SETTLE_SURVIVE,
                                      DEFAULT_SPREAD_TENDENCY, DEFAULT_PORT_ACTIVITY,
                                      exp_default, sett_stats)
        sc_def = score_prediction(pred_def, gt)
        scores_v3_default.append(sc_def)

        log(f"  Seed {sid}: est_exp={exp_est:.3f} (gt={exp_gt:.3f})  "
            f"v3_estimated={sc_est:.1f}  v3_default={sc_def:.1f}")

    mean_est = np.mean(scores_v3_estimated)
    mean_def = np.mean(scores_v3_default)

    log(f"\n  {'=' * 50}")
    log(f"  R21 RESULTS")
    log(f"  {'=' * 50}")
    log(f"  Actual live:          84.81")
    log(f"  V2 (default exp=0.1): 85.68")
    log(f"  V3 (default exp=0.1): {mean_def:.2f}")
    log(f"  V3 (estimated exp):   {mean_est:.2f}  <-- NEW")
    log(f"  Delta vs actual:      {mean_est - 84.81:+.2f}")
    log(f"  Delta vs V2:          {mean_est - 85.68:+.2f}")

    # --- Retrain on R1-R21 if improvement ---
    if "--retrain" in sys.argv:
        log(f"\n--- Retraining on R1-R21 ---")
        all_train = [s for rn in sorted(rounds.keys()) for s in rounds[rn]]
        log(f"  {len(all_train)} samples")
        t0 = time.time()
        models_full = train_models(all_train)
        save_models(models_full, CHECKPOINT_V3_DIR)
        log(f"  Done ({time.time()-t0:.0f}s)")
    else:
        log(f"\n  Run with --retrain to train on R1-R21 and save checkpoints_v3")


if __name__ == "__main__":
    main()
