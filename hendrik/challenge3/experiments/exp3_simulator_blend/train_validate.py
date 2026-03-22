"""
Train GBM + distance prior features on R1-R20, validate on R21 vs actual 84.81.
Then optionally retrain on R1-R21 and save checkpoints.

Uses all available data: initial_grid, settlement_stats, observed_probs.
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
    compute_hidden_params_from_obs, reconstruct_observations,
    GRID_SIZE, N_CLASSES, PROB_FLOOR, FEATURE_NAMES, LGB_PARAMS,
    CHECKPOINT_DIR,
)
import lightgbm as lgb
import joblib

PRIOR_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "arian" / "distance_priors.json"
SUBMIT_DIR = Path(__file__).resolve().parent.parent.parent / "round_data"
LOG_FILE = Path(__file__).parent / "train_validate_results.txt"

CHECKPOINT_V2_DIR = Path(__file__).resolve().parent.parent.parent / "checkpoints_v2"


def log(msg):
    print(msg, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(msg + "\n")


# ============================================================
# Distance prior lookup (vectorized)
# ============================================================
print("Loading distance priors...", flush=True)
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
print("  Loaded.", flush=True)


def find_nearest_rate(expansion_rate):
    idx = np.argmin(np.abs(PRIOR_RATE_VALS - expansion_rate))
    return PRIOR_RATE_KEYS[idx]


def get_expansion_rate_from_gt(grid, gt):
    grid = np.asarray(grid)
    gt = np.asarray(gt)
    non_settle = ~np.isin(grid, [1, 2])
    land = grid != 10
    mask = non_settle & land
    if mask.sum() == 0:
        return 0.1
    return float(gt[mask, 1].mean())


def get_expansion_rate_from_obs(grid, obs_probs, n_obs):
    """Estimate expansion rate from observations."""
    grid = np.asarray(grid)
    obs_probs = np.asarray(obs_probs)
    n_obs = np.asarray(n_obs)
    non_settle = ~np.isin(grid, [1, 2])
    land = grid != 10
    observed = n_obs > 0
    mask = non_settle & land & observed
    if mask.sum() < 50:
        return 0.1  # default
    return float(obs_probs[mask, 1].mean())


def compute_prior_features(grid, expansion_rate):
    """Vectorized prior lookup. Returns (40, 40, 6)."""
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
# Augmented feature extraction
# ============================================================
N_PRIOR_FEATURES = 6
AUGMENTED_FEATURE_NAMES = FEATURE_NAMES + [
    "prior_p0", "prior_p1", "prior_p2", "prior_p3", "prior_p4", "prior_p5",
]


def build_augmented_X(grid, ss, st, pa, expansion_rate, settlement_stats=None):
    """Build feature array with prior features for one sample."""
    n_base = len(FEATURE_NAMES)
    base = extract_features(grid, ss, st, pa, settlement_stats)
    prior = compute_prior_features(grid, expansion_rate).reshape(GRID_SIZE * GRID_SIZE, 6)
    X = np.zeros((GRID_SIZE * GRID_SIZE, n_base + 6), dtype=np.float32)
    X[:, :n_base] = base
    X[:, n_base:] = prior
    return X


def train_augmented_models(samples, log_fn=log):
    """Train 6 LightGBM models with prior features."""
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

    log_fn(f"  Features built: {X.shape} ({time.time()-t0:.1f}s)")

    models = []
    t0 = time.time()
    for k in range(N_CLASSES):
        tk = time.time()
        m = lgb.LGBMRegressor(**LGB_PARAMS)
        m.fit(X, Y[:, k], categorical_feature=[0])
        models.append(m)
        log_fn(f"  Class {k}: {time.time()-tk:.1f}s")
    log_fn(f"  Total training: {time.time()-t0:.0f}s")
    return models


def predict_augmented(models, grid, ss, st, pa, expansion_rate, settlement_stats=None):
    """Predict using augmented models."""
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
    pred = pred / pred.sum(axis=-1, keepdims=True)
    return pred


def save_augmented_models(models):
    CHECKPOINT_V2_DIR.mkdir(parents=True, exist_ok=True)
    for k, m in enumerate(models):
        joblib.dump(m, CHECKPOINT_V2_DIR / f"lgbm_v2_class_{k}.joblib")
    log(f"  Saved {len(models)} models to {CHECKPOINT_V2_DIR}")


# ============================================================
# Main
# ============================================================
def main():
    with open(LOG_FILE, "w") as f:
        f.write("")

    log("=" * 70)
    log("  Train on R1-R20, Validate on R21 (actual: 84.81)")
    log("=" * 70)

    # Load all data
    all_samples = load_v2_data()
    rounds = {}
    for s in all_samples:
        rounds.setdefault(s["round"], []).append(s)

    # Split: train=R1-R20, test=R21
    train_samples = [s for rn in sorted(rounds.keys()) if rn <= 20 for s in rounds[rn]]
    test_samples = rounds.get(21, [])
    log(f"Train: {len(train_samples)} samples (R1-R20)")
    log(f"Test:  {len(test_samples)} samples (R21)")

    # Load R21 submit data for settlement_stats + observed_probs
    submit_path = SUBMIT_DIR / "round_21_submit.json"
    submit_data = {}
    if submit_path.exists():
        submit_data = json.load(open(submit_path))
    submit_seeds = submit_data.get("seeds", {})

    # --- Train augmented GBM ---
    log("\n--- Training GBM + distance prior features on R1-R20 ---")
    models = train_augmented_models(train_samples)

    # --- Validate on R21 ---
    log("\n--- Validating on R21 ---")
    log(f"  Actual live score: 84.81")
    log(f"  Actual seed scores: [87.83, 78.40, 87.89, 83.44, 86.49]")

    seed_scores_gt_params = []
    seed_scores_obs_params = []
    seed_scores_default_params = []

    for s in test_samples:
        gt = s["gt"]
        grid = s["grid"]
        sid = s["seed"]

        # Get submit data for this seed
        sub = submit_seeds.get(str(sid), {})
        sett_stats = sub.get("settlement_stats")
        obs_probs_raw = sub.get("observed_probs")
        n_obs_raw = sub.get("n_observations")

        # --- Method 1: GT-derived params (oracle, upper bound) ---
        exp_rate_gt = get_expansion_rate_from_gt(grid, gt)
        pred_gt = predict_augmented(models, grid, s["ss"], s["st"], s["pa"],
                                     exp_rate_gt, sett_stats)
        sc_gt = score_prediction(pred_gt, gt)
        seed_scores_gt_params.append(sc_gt)

        # --- Method 2: Obs-derived params (realistic) ---
        if obs_probs_raw and n_obs_raw:
            obs_probs = np.array(obs_probs_raw, dtype=np.float32)
            n_obs = np.array(n_obs_raw, dtype=np.float32)
            ss_obs, st_obs, pa_obs = compute_hidden_params_from_obs(grid, obs_probs, n_obs)
            exp_rate_obs = get_expansion_rate_from_obs(grid, obs_probs, n_obs)
            pred_obs = predict_augmented(models, grid, ss_obs, st_obs, pa_obs,
                                          exp_rate_obs, sett_stats)
            sc_obs = score_prediction(pred_obs, gt)
        else:
            sc_obs = sc_gt  # fallback
        seed_scores_obs_params.append(sc_obs)

        # --- Method 3: Default params (worst case) ---
        from solve import DEFAULT_SETTLE_SURVIVE, DEFAULT_SPREAD_TENDENCY, DEFAULT_PORT_ACTIVITY
        pred_def = predict_augmented(models, grid, DEFAULT_SETTLE_SURVIVE,
                                      DEFAULT_SPREAD_TENDENCY, DEFAULT_PORT_ACTIVITY,
                                      0.1, sett_stats)
        sc_def = score_prediction(pred_def, gt)
        seed_scores_default_params.append(sc_def)

        log(f"  Seed {sid}: GT_params={sc_gt:.1f}  Obs_params={sc_obs:.1f}  "
            f"Default={sc_def:.1f}  (actual={s.get('score', '?')})")

    mean_gt = np.mean(seed_scores_gt_params)
    mean_obs = np.mean(seed_scores_obs_params)
    mean_def = np.mean(seed_scores_default_params)

    log(f"\n  {'=' * 50}")
    log(f"  R21 RESULTS")
    log(f"  {'=' * 50}")
    log(f"  Actual live score:     84.81")
    log(f"  GT params (oracle):    {mean_gt:.2f}  (delta vs actual: {mean_gt - 84.81:+.2f})")
    log(f"  Obs params (realistic):{mean_obs:.2f}  (delta vs actual: {mean_obs - 84.81:+.2f})")
    log(f"  Default params:        {mean_def:.2f}  (delta vs actual: {mean_def - 84.81:+.2f})")

    log(f"\n  PAUSING — check results before retraining on R1-R21.")
    log(f"  To retrain: python3 train_validate.py --retrain")

    # --- Retrain on all if requested ---
    if "--retrain" in sys.argv:
        log(f"\n--- Retraining on R1-R21 (all data) ---")
        all_train = [s for rn in sorted(rounds.keys()) for s in rounds[rn]]
        log(f"  {len(all_train)} samples")
        models_full = train_augmented_models(all_train)
        save_augmented_models(models_full)
        log(f"  Done! Checkpoints saved.")


if __name__ == "__main__":
    main()
