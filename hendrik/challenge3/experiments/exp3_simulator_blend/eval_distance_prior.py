"""
Experiment: Use Arian's distance priors as features or blend target for GBM.

Tests:
  1. GBM baseline (no prior features)
  2. GBM + 6 prior probability features
  3. Blend: alpha * prior + (1-alpha) * GBM
  4. Blend: alpha * prior + (1-alpha) * GBM+prior_features
"""

import json
import sys
import time
import numpy as np
from pathlib import Path
from scipy.ndimage import distance_transform_edt, convolve

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from solve import (
    load_v2_data, build_training_arrays, extract_features, train_models,
    predict_grid, score_prediction, GRID_SIZE, N_CLASSES, PROB_FLOOR,
    FEATURE_NAMES, LGB_PARAMS,
)
import lightgbm as lgb

PRIOR_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "arian" / "distance_priors.json"
LOG_FILE = Path(__file__).parent / "distance_prior_results.txt"


def log(msg):
    print(msg, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(msg + "\n")


# ============================================================
# Load + preprocess priors into fast numpy lookup
# ============================================================
print("Loading distance priors...", flush=True)
with open(PRIOR_PATH) as f:
    RAW_PRIORS = json.load(f)
PRIOR_RATE_KEYS = sorted(RAW_PRIORS.keys(), key=float)
PRIOR_RATE_VALS = np.array([float(k) for k in PRIOR_RATE_KEYS])

# Build numpy lookup: key = (terrain, distance, n_forest, is_coastal) -> 6 probs
# Encode as int key: terrain*10000 + distance*100 + n_forest*10 + is_coastal
# Pre-build dict[rate_key] -> dict[int_key] -> np.array(6)
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
print(f"  Loaded {len(PRIOR_RATE_KEYS)} rates, preprocessed lookups", flush=True)


def find_nearest_rate(expansion_rate):
    idx = np.argmin(np.abs(PRIOR_RATE_VALS - expansion_rate))
    return PRIOR_RATE_KEYS[idx]


def get_expansion_rate(grid, gt):
    grid = np.asarray(grid)
    gt = np.asarray(gt)
    non_settle = ~np.isin(grid, [1, 2])
    land = grid != 10
    mask = non_settle & land
    if mask.sum() == 0:
        return 0.1
    return float(gt[mask, 1].mean())


def compute_prior_features_vectorized(grid, expansion_rate):
    """Vectorized prior lookup. Returns (40, 40, 6)."""
    grid = np.asarray(grid, dtype=np.int32)
    h, w = grid.shape
    rate_key = find_nearest_rate(expansion_rate)
    lookup = PRIOR_LOOKUP[rate_key]

    # Distance map
    settle_mask = np.isin(grid, [1, 2])
    if settle_mask.any():
        dist_map = np.clip(distance_transform_edt(~settle_mask).astype(np.int32), 0, 20)
    else:
        dist_map = np.full((h, w), 20, dtype=np.int32)

    # Forest neighbor count via convolution
    kernel = np.array([[1,1,1],[1,0,1],[1,1,1]], dtype=np.int32)
    forest = (grid == 4).astype(np.int32)
    n_forest = convolve(forest, kernel, mode='constant', cval=0)
    n_forest = np.clip(n_forest, 0, 8)

    # Coastal via convolution
    ocean = (grid == 10).astype(np.int32)
    ocean_nbr = convolve(ocean, kernel, mode='constant', cval=0)
    is_coastal = ((ocean_nbr > 0) & (ocean == 0)).astype(np.int32)

    # Build int keys for all cells at once
    int_keys = grid * 10000 + dist_map * 100 + n_forest * 10 + is_coastal  # (h, w)

    # Vectorized lookup via flat array
    prior_probs = np.zeros((h, w, 6), dtype=np.float32)
    flat_keys = int_keys.ravel()
    for i, k in enumerate(flat_keys):
        p = lookup.get(int(k))
        if p is not None:
            prior_probs.ravel()[i*6:(i+1)*6] = p
        else:
            # Fallback: flip coastal
            k2 = int(k) ^ 1  # toggle last bit
            p2 = lookup.get(k2)
            if p2 is not None:
                prior_probs.ravel()[i*6:(i+1)*6] = p2
            else:
                prior_probs.ravel()[i*6:(i+1)*6] = DEFAULT_PRIOR

    return prior_probs


def build_augmented_arrays(samples, log_fn=None):
    """Build training arrays with 6 extra prior features."""
    n_cells = GRID_SIZE * GRID_SIZE
    n_base = len(FEATURE_NAMES)
    n_total = n_base + 6

    X = np.zeros((len(samples) * n_cells, n_total), dtype=np.float32)
    Y = np.zeros((len(samples) * n_cells, N_CLASSES), dtype=np.float32)

    for i, s in enumerate(samples):
        start = i * n_cells
        end = start + n_cells
        base_feats = extract_features(s["grid"], s["ss"], s["st"], s["pa"], s.get("settlement_stats"))
        X[start:end, :n_base] = base_feats

        exp_rate = get_expansion_rate(s["grid"], s["gt"])
        prior_probs = compute_prior_features_vectorized(s["grid"], exp_rate)
        X[start:end, n_base:] = prior_probs.reshape(n_cells, 6)

        Y[start:end] = s["gt"].reshape(n_cells, N_CLASSES)

    return X, Y


def predict_with_prior_features(models, grid, ss, st, pa, expansion_rate, settlement_stats=None):
    grid = np.asarray(grid, dtype=np.int32)
    n_base = len(FEATURE_NAMES)
    base_feats = extract_features(grid, ss, st, pa, settlement_stats)
    prior_probs = compute_prior_features_vectorized(grid, expansion_rate)

    X = np.zeros((GRID_SIZE * GRID_SIZE, n_base + 6), dtype=np.float32)
    X[:, :n_base] = base_feats
    X[:, n_base:] = prior_probs.reshape(GRID_SIZE * GRID_SIZE, 6)

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


def blend(a, b, alpha):
    r = alpha * a + (1 - alpha) * b
    r = np.clip(r, PROB_FLOOR, None)
    return r / r.sum(axis=-1, keepdims=True)


def main():
    with open(LOG_FILE, "w") as f:
        f.write("")

    log("=" * 70)
    log("  Experiment: Distance Prior Features + Blend")
    log("=" * 70)

    samples = load_v2_data()
    rounds = {}
    for s in samples:
        rounds.setdefault(s["round"], []).append(s)
    round_nums = sorted(rounds.keys())
    log(f"Loaded {len(samples)} samples, {len(round_nums)} rounds\n")

    alphas = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]

    scores_gbm = []
    scores_prior = []
    scores_gbm_aug = []
    scores_blend = {a: [] for a in alphas}
    scores_blend_aug = {a: [] for a in alphas}

    t0 = time.time()
    for fold_i, test_rn in enumerate(round_nums):
        ft = time.time()
        train = [s for rn in round_nums if rn != test_rn for s in rounds[rn]]
        test = rounds[test_rn]

        # Train base GBM
        t_train = time.time()
        X_base, Y_base = build_training_arrays(train)
        models_base = []
        for k in range(N_CLASSES):
            m = lgb.LGBMRegressor(**LGB_PARAMS)
            m.fit(X_base, Y_base[:, k], categorical_feature=[0])
            models_base.append(m)
        log(f"    Base GBM trained in {time.time()-t_train:.0f}s")

        # Train augmented GBM (with prior features)
        t_aug = time.time()
        X_aug, Y_aug = build_augmented_arrays(train)
        log(f"    Aug features built in {time.time()-t_aug:.0f}s")
        t_aug2 = time.time()
        models_aug = []
        for k in range(N_CLASSES):
            m = lgb.LGBMRegressor(**LGB_PARAMS)
            m.fit(X_aug, Y_aug[:, k], categorical_feature=[0])
            models_aug.append(m)
        log(f"    Aug GBM trained in {time.time()-t_aug2:.0f}s")

        fold_gbm, fold_prior, fold_aug = [], [], []
        fold_blend = {a: [] for a in alphas}
        fold_blend_aug = {a: [] for a in alphas}

        for s in test:
            gt = s["gt"]
            exp_rate = get_expansion_rate(s["grid"], gt)

            gbm_pred = predict_grid(models_base, s["grid"], s["ss"], s["st"], s["pa"],
                                     settlement_stats=s.get("settlement_stats"))
            fold_gbm.append(score_prediction(gbm_pred, gt))

            prior_pred = compute_prior_features_vectorized(s["grid"], exp_rate)
            prior_pred = np.clip(prior_pred, PROB_FLOOR, None)
            prior_pred = prior_pred / prior_pred.sum(axis=-1, keepdims=True)
            fold_prior.append(score_prediction(prior_pred, gt))

            aug_pred = predict_with_prior_features(models_aug, s["grid"], s["ss"], s["st"], s["pa"],
                                                     exp_rate, s.get("settlement_stats"))
            fold_aug.append(score_prediction(aug_pred, gt))

            for alpha in alphas:
                fold_blend[alpha].append(score_prediction(blend(prior_pred, gbm_pred, alpha), gt))
                fold_blend_aug[alpha].append(score_prediction(blend(prior_pred, aug_pred, alpha), gt))

        mean_gbm = np.mean(fold_gbm)
        mean_prior = np.mean(fold_prior)
        mean_aug = np.mean(fold_aug)
        scores_gbm.append(mean_gbm)
        scores_prior.append(mean_prior)
        scores_gbm_aug.append(mean_aug)
        for a in alphas:
            scores_blend[a].append(np.mean(fold_blend[a]))
            scores_blend_aug[a].append(np.mean(fold_blend_aug[a]))

        elapsed = time.time() - ft
        remaining = len(round_nums) - fold_i - 1
        eta = elapsed * remaining
        log(f"  R{test_rn:2d}: GBM={mean_gbm:.1f}  Prior={mean_prior:.1f}  "
            f"GBM+feat={mean_aug:.1f}  ({elapsed:.0f}s, {remaining} left, ETA {eta:.0f}s)")

    log(f"\n{'=' * 70}")
    log(f"  SUMMARY ({time.time()-t0:.0f}s)")
    log(f"{'=' * 70}")

    log(f"\n  GBM baseline:         {np.mean(scores_gbm):.2f}")
    log(f"  Prior only:           {np.mean(scores_prior):.2f}")
    log(f"  GBM + prior features: {np.mean(scores_gbm_aug):.2f}")

    log(f"\n  Blend (prior weight -> score):")
    log(f"  {'alpha':<8} {'prior+GBM':<12} {'prior+GBM_aug':<14}")
    for a in alphas:
        log(f"  {a:<8.1f} {np.mean(scores_blend[a]):<12.2f} {np.mean(scores_blend_aug[a]):<14.2f}")

    best_aug_mean = np.mean(scores_gbm_aug)
    best_blend_a = max(alphas, key=lambda a: np.mean(scores_blend[a]))
    best_blend_mean = np.mean(scores_blend[best_blend_a])
    best_blend_aug_a = max(alphas, key=lambda a: np.mean(scores_blend_aug[a]))
    best_blend_aug_mean = np.mean(scores_blend_aug[best_blend_aug_a])

    winner = max([
        ("GBM+prior_feat", best_aug_mean, None),
        (f"blend(prior,GBM,{best_blend_a})", best_blend_mean, best_blend_a),
        (f"blend(prior,GBM_aug,{best_blend_aug_a})", best_blend_aug_mean, best_blend_aug_a),
    ], key=lambda x: x[1])

    log(f"\n  BEST: {winner[0]} -> {winner[1]:.2f} "
        f"(vs GBM {np.mean(scores_gbm):.2f}, delta: {winner[1]-np.mean(scores_gbm):+.2f})")


if __name__ == "__main__":
    main()
