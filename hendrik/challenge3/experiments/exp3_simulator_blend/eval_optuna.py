"""
Optuna hyperparameter tuning for LightGBM.

Fast: 3-fold CV for search (3 diverse rounds), 20 trials.
Results written to optuna_results.txt for easy monitoring.
"""

import sys
import time
import csv
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)
import lightgbm as lgb

from solve import (
    load_v2_data, build_training_arrays,
    score_prediction, predict_grid, N_CLASSES, LGB_PARAMS,
)

OUT_DIR = Path(__file__).parent
RESULTS_FILE = OUT_DIR / "optuna_results.txt"

# Load data once
ALL_SAMPLES = load_v2_data()
ROUNDS = {}
for s in ALL_SAMPLES:
    ROUNDS.setdefault(s["round"], []).append(s)
ROUND_NUMS = sorted(ROUNDS.keys())

# 3 diverse folds: a weak round (R7=66), a mid round (R12=71), a strong round (R15=90)
FAST_FOLDS = [7, 12, 15]

def log(msg):
    print(msg, flush=True)
    with open(RESULTS_FILE, "a") as f:
        f.write(msg + "\n")


def train_and_eval(params, fold_rounds):
    scores = []
    for test_rn in fold_rounds:
        train = [s for rn in ROUND_NUMS if rn != test_rn for s in ROUNDS[rn]]
        X, Y = build_training_arrays(train)
        models = []
        for k in range(N_CLASSES):
            model = lgb.LGBMRegressor(**params)
            model.fit(X, Y[:, k], categorical_feature=[0])
            models.append(model)
        for s in ROUNDS[test_rn]:
            pred = predict_grid(models, s["grid"], s["ss"], s["st"], s["pa"],
                                settlement_stats=s.get("settlement_stats"))
            scores.append(score_prediction(pred, s["gt"]))
    return np.mean(scores)


BEST_SO_FAR = [0.0]

def objective(trial):
    params = {
        "objective": "regression",
        "metric": "mse",
        "n_estimators": trial.suggest_int("n_estimators", 500, 2000, step=100),
        "max_depth": trial.suggest_int("max_depth", 5, 9),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.08, log=True),
        "min_child_samples": trial.suggest_int("min_child_samples", 15, 80),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        "reg_alpha": trial.suggest_float("reg_alpha", 0.01, 0.5, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 0.05, 3.0, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 20, 100),
        "device": "gpu",
        "verbose": -1,
        "n_jobs": -1,
        "random_state": 42,
    }

    t0 = time.time()
    score = train_and_eval(params, FAST_FOLDS)
    elapsed = time.time() - t0

    is_best = score > BEST_SO_FAR[0]
    if is_best:
        BEST_SO_FAR[0] = score

    log(f"{'>>>' if is_best else '   '} T{trial.number:2d}: {score:.2f}  "
        f"({elapsed:.0f}s)  lr={params['learning_rate']:.4f} "
        f"depth={params['max_depth']} trees={params['n_estimators']} "
        f"leaves={params['num_leaves']} mcs={params['min_child_samples']} "
        f"sub={params['subsample']:.2f} col={params['colsample_bytree']:.2f} "
        f"a={params['reg_alpha']:.3f} l={params['reg_lambda']:.3f}")
    return score


def main():
    # Clear results file
    with open(RESULTS_FILE, "w") as f:
        f.write("")

    log("=" * 70)
    log("  Optuna LightGBM Tuning | 3-fold fast CV | 20 trials")
    log("=" * 70)
    log(f"Folds: R{FAST_FOLDS[0]}, R{FAST_FOLDS[1]}, R{FAST_FOLDS[2]}")

    # Baseline
    t0 = time.time()
    baseline = train_and_eval(LGB_PARAMS, FAST_FOLDS)
    BEST_SO_FAR[0] = baseline
    log(f"\nBASELINE: {baseline:.2f} ({time.time()-t0:.0f}s)")
    log(f"  Current: depth=7 lr=0.03 trees=1000 leaves=127 mcs=30")
    log("")

    # Search
    study = optuna.create_study(direction="maximize")
    study.enqueue_trial({
        "n_estimators": 1000, "max_depth": 7, "learning_rate": 0.03,
        "min_child_samples": 30, "subsample": 0.8, "colsample_bytree": 0.8,
        "reg_alpha": 0.05, "reg_lambda": 0.5, "num_leaves": 63,
    })

    t0 = time.time()
    study.optimize(objective, n_trials=20, show_progress_bar=False)

    log(f"\n{'=' * 70}")
    log(f"  DONE ({time.time()-t0:.0f}s total)")
    log(f"{'=' * 70}")
    log(f"  Baseline:  {baseline:.2f}")
    log(f"  Best:      {study.best_value:.2f}  (delta: {study.best_value - baseline:+.2f})")
    log(f"\n  Best params:")
    for k, v in sorted(study.best_params.items()):
        log(f"    {k}: {v}")

    # Full 21-fold LOO if improvement > 0.3
    if study.best_value - baseline > 0.3:
        log(f"\nImprovement > 0.3, running full 21-fold LOO validation...")
        best_params = {
            "objective": "regression", "metric": "mse",
            "device": "gpu", "verbose": -1, "n_jobs": -1, "random_state": 42,
            **study.best_params,
        }
        t0 = time.time()
        full_score = train_and_eval(best_params, ROUND_NUMS)
        log(f"  Full LOO: {full_score:.2f} (prev baseline: 83.64, delta: {full_score - 83.64:+.2f})")
        log(f"  ({time.time()-t0:.0f}s)")
    else:
        log(f"\nImprovement too small ({study.best_value - baseline:+.2f}), skipping full LOO.")


if __name__ == "__main__":
    main()
