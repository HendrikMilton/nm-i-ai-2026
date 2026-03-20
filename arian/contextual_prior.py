"""
Contextual prior lookup — learned from R1-R7 ground truth.

Key: (initial_terrain_api, forest_neighbor_bin, is_coastal)
Value: 6-class probability distribution

Round classification:
  - Query seed 0 for settlement viewport
  - Check settlement survival rate from settlement stats
  - COLD: survival < 0.15 (e.g. R3 with winter_severity ~0.9)
  - WARM: survival >= 0.15 (all other rounds)

Usage:
    from contextual_prior import build_prior_prediction, classify_round_from_obs

    round_type = classify_round_from_obs(observations, initial_grid_api)
    prediction = build_prior_prediction(initial_grid_api, round_type)
"""
import json
import os
import numpy as np

OCEAN = 10
MOUNTAIN = 5
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PRIORS_FILE = os.path.join(_THIS_DIR, "contextual_priors.json")

_priors_cache = None


def _load_priors():
    global _priors_cache
    if _priors_cache is None:
        with open(_PRIORS_FILE) as f:
            _priors_cache = json.load(f)
    return _priors_cache


def _get_dist(priors_table, terrain, forest_bin, coastal, fallback):
    key = f"{terrain}_{forest_bin}_{int(coastal)}"
    if key in priors_table:
        return np.array(priors_table[key]["dist"], dtype=np.float32)
    # Fallback: try without coastal distinction
    for c in [0, 1]:
        k2 = f"{terrain}_{forest_bin}_{c}"
        if k2 in priors_table:
            return np.array(priors_table[k2]["dist"], dtype=np.float32)
    return fallback.copy()


def classify_round_type(observations: dict, initial_grid_api: np.ndarray) -> str:
    """
    Classify round as 'warm' or 'cold' from observations.

    Looks at initial settlement cells and checks what fraction ended up
    still as settlements in the observation. Low survival = cold round.

    observations: {(x, y): class_index}
    initial_grid_api: H x W array of raw API values
    """
    H, W = initial_grid_api.shape
    settle_cells = [(x, y) for y in range(H) for x in range(W)
                    if initial_grid_api[y, x] == 1]

    if not settle_cells:
        return 'warm'

    survived = sum(1 for (x, y) in settle_cells
                   if observations.get((x, y), -1) == 1)
    survival_rate = survived / len(settle_cells)

    return 'cold' if survival_rate < 0.15 else 'warm'


def build_prior_prediction(initial_grid_api: np.ndarray, round_type: str = 'warm') -> np.ndarray:
    """
    Build H x W x 6 prediction using contextual priors.

    initial_grid_api: H x W array of raw API values (10=ocean, 11=empty, 1=settle, etc.)
    round_type: 'warm', 'cold', or 'all'

    Returns normalized H x W x 6 probability array.
    """
    priors = _load_priors()
    table = priors.get(round_type, priors['all'])

    H, W = initial_grid_api.shape
    pred = np.zeros((H, W, 6), dtype=np.float32)

    # Default fallback distributions
    ocean_dist = np.array([0.99, 0.002, 0.002, 0.002, 0.002, 0.002], dtype=np.float32)
    mountain_dist = np.array([0.002, 0.002, 0.002, 0.002, 0.002, 0.99], dtype=np.float32)
    uniform_dist = np.ones(6, dtype=np.float32) / 6

    # Precompute forest and ocean masks for neighbor counting
    forest_mask = (initial_grid_api == 4).astype(float)
    ocean_mask = (initial_grid_api == OCEAN).astype(float)
    pf = np.pad(forest_mask, 1)
    po = np.pad(ocean_mask, 1)

    for y in range(H):
        for x in range(W):
            t = int(initial_grid_api[y, x])

            if t == OCEAN:
                pred[y, x] = ocean_dist
                continue
            if t == MOUNTAIN:
                pred[y, x] = mountain_dist
                continue

            n_forest = int(pf[y:y+3, x:x+3].sum() - forest_mask[y, x])
            fb = min(n_forest, 3)
            coastal = bool(po[y:y+3, x:x+3].sum() > 0)

            dist = _get_dist(table, t, fb, coastal, uniform_dist)
            pred[y, x] = dist

    # Floor and normalize
    pred = np.maximum(pred, 0.002)
    pred = pred / pred.sum(axis=2, keepdims=True)
    return pred


def blend_prior_with_mc(prior_pred: np.ndarray, mc_pred: np.ndarray,
                        prior_weight: float = 4.0) -> np.ndarray:
    """
    Blend contextual prior with MC prediction.
    prior_weight: how many pseudo-observations the prior is worth vs MC.
    Higher = trust prior more. Default 4.0 based on Elias's backtest data.

    Formula: blended = (prior * prior_weight + mc * 1) / (prior_weight + 1)
    """
    blended = (prior_pred * prior_weight + mc_pred) / (prior_weight + 1)
    blended = np.maximum(blended, 0.002)
    blended = blended / blended.sum(axis=2, keepdims=True)
    return blended
