"""
Experiment 1: CNN Residual on top of LightGBM.
Trains GBM per-cell, then a tiny CNN that refines predictions spatially.
"""
import sys
import os
from pathlib import Path

# Fix paths: eval_common uses Path(__file__).parent.parent to find challenge3/
# We need to patch it after import so it resolves correctly
_THIS_DIR = Path(__file__).resolve().parent
_EXPERIMENTS_DIR = _THIS_DIR.parent
_CHALLENGE3_DIR = _EXPERIMENTS_DIR.parent
sys.path.insert(0, str(_EXPERIMENTS_DIR))

import eval_common
eval_common.CHALLENGE3_DIR = _CHALLENGE3_DIR
eval_common.V2_DATA_DIR = _CHALLENGE3_DIR / "../../elias/logs/offline"
eval_common.ROUND_DATA_DIR = _CHALLENGE3_DIR / "round_data"

from eval_common import run_loo_cv, score_prediction, GRID_SIZE, N_CLASSES, PROB_FLOOR

import numpy as np
import math
import time
import torch
import torch.nn as nn
import torch.nn.functional as F
from scipy.ndimage import distance_transform_edt, gaussian_filter
import lightgbm as lgb

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# ============================================================
# Feature extraction (from solve.py)
# ============================================================
TERRAIN_TO_CLASS = {0: 0, 10: 0, 11: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}

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
    "settle_survive", "spread_tendency", "port_activity",
]


def extract_features(grid, ss, st, pa):
    """Extract per-cell features. Returns (1600, N_FEAT)."""
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
                if dy == 0 and dx == 0: continue
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
            if dy == 0 and dx == 0: continue
            shifted = np.zeros_like(grid)
            r_src = slice(max(0, -dy), min(h, h - dy))
            c_src = slice(max(0, -dx), min(w, w - dx))
            r_dst = slice(max(0, dy), min(h, h + dy))
            c_dst = slice(max(0, dx), min(w, w + dx))
            shifted[r_dst, c_dst] = grid[r_src, c_src]
            div += (shifted != grid).astype(np.float32)
    terrain_div = div / 8.0

    ss_arr = np.full((h, w), ss, dtype=np.float32)
    st_arr = np.full((h, w), st, dtype=np.float32)
    pa_arr = np.full((h, w), pa, dtype=np.float32)

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

    flat = np.stack([f.ravel() for f in feature_maps], axis=1)
    spatial = np.stack(feature_maps, axis=0)  # (C, H, W)
    return flat, spatial


# ============================================================
# GBM
# ============================================================
LGB_PARAMS = {
    "objective": "regression",
    "metric": "mse",
    "n_estimators": 800,
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


def train_gbm(X, Y):
    models = []
    t0 = time.time()
    for k in range(N_CLASSES):
        model = lgb.LGBMRegressor(**LGB_PARAMS)
        model.fit(X, Y[:, k], categorical_feature=[0])
        models.append(model)
    print(f"    GBM trained {N_CLASSES} models in {time.time()-t0:.1f}s", flush=True)
    return models


def predict_gbm(models, X, grid):
    preds = np.zeros((GRID_SIZE * GRID_SIZE, N_CLASSES), dtype=np.float64)
    for k, model in enumerate(models):
        preds[:, k] = model.predict(X)
    pred = preds.reshape(GRID_SIZE, GRID_SIZE, N_CLASSES)
    ocean_mask = grid == 10
    mountain_mask = grid == 5
    if ocean_mask.any():
        pred[ocean_mask] = 0.0
        pred[ocean_mask, 0] = 1.0
    if mountain_mask.any():
        pred[mountain_mask] = 0.0
        pred[mountain_mask, 5] = 1.0
    pred = np.clip(pred, PROB_FLOOR, None)
    pred = pred / pred.sum(axis=-1, keepdims=True)
    return pred


# ============================================================
# CNN model
# ============================================================
class ResidualBlock(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, 3, padding=1)
        self.bn1 = nn.BatchNorm2d(channels)
        self.conv2 = nn.Conv2d(channels, channels, 3, padding=1)
        self.bn2 = nn.BatchNorm2d(channels)

    def forward(self, x):
        h = F.relu(self.bn1(self.conv1(x)))
        h = self.bn2(self.conv2(h))
        return F.relu(h + x)


class ResidualCNN(nn.Module):
    """U-Net style CNN that predicts logit corrections to GBM.

    The first 6 input channels are GBM logits. The CNN outputs additive
    corrections, so GBM predictions are the starting point.
    """

    def __init__(self, in_channels):
        super().__init__()
        # Encoder
        self.enc1 = nn.Sequential(
            nn.Conv2d(in_channels, 48, 3, padding=1),
            nn.BatchNorm2d(48),
            nn.ReLU(),
        )
        self.enc2 = nn.Sequential(
            nn.Conv2d(48, 64, 3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
        )
        self.res1 = ResidualBlock(64)
        # Multi-scale context
        self.dilated1 = nn.Sequential(
            nn.Conv2d(64, 64, 3, padding=2, dilation=2),
            nn.BatchNorm2d(64),
            nn.ReLU(),
        )
        self.dilated2 = nn.Sequential(
            nn.Conv2d(64, 64, 3, padding=4, dilation=4),
            nn.BatchNorm2d(64),
            nn.ReLU(),
        )
        # Decoder with skip connection from enc1
        self.dec1 = nn.Sequential(
            nn.Conv2d(64 + 48, 48, 3, padding=1),  # skip from enc1
            nn.BatchNorm2d(48),
            nn.ReLU(),
        )
        self.res2 = ResidualBlock(48)
        self.dropout = nn.Dropout2d(0.1)
        # Output: correction to GBM logits (6 channels)
        self.head = nn.Conv2d(48, N_CLASSES, 1)
        # Initialize head near zero so initial output ≈ GBM
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, x):
        # x[:, :6] are GBM logits
        gbm_logits = x[:, :6]

        e1 = self.enc1(x)
        e2 = self.enc2(e1)
        e2 = self.res1(e2)
        # Multi-scale fusion
        d1 = self.dilated1(e2)
        d2 = self.dilated2(e2)
        e2 = e2 + d1 + d2
        # Decode with skip
        h = torch.cat([e2, e1], dim=1)
        h = self.dec1(h)
        h = self.res2(h)
        h = self.dropout(h)
        correction = self.head(h)
        # Add correction to GBM logits (residual learning)
        return gbm_logits + correction


def build_cnn_input_single(sample, gbm_models):
    """Build CNN input for one sample. Returns (C, H, W) input and (6, H, W) target.

    First 6 channels are GBM logits (log-probabilities), so the CNN can learn
    additive corrections in logit space.
    """
    grid = sample["grid"]
    flat_feats, spatial_feats = extract_features(grid, sample["ss"], sample["st"], sample["pa"])
    gbm_pred = predict_gbm(gbm_models, flat_feats, grid)  # (40, 40, 6)

    # Convert GBM predictions to logits for residual learning
    gbm_logits = np.log(np.clip(gbm_pred, 1e-6, None)).transpose(2, 0, 1).astype(np.float32)

    # Terrain one-hot: 8 classes
    terrain_oh = np.zeros((8, GRID_SIZE, GRID_SIZE), dtype=np.float32)
    for i, code in enumerate([0, 1, 2, 3, 4, 5, 10, 11]):
        terrain_oh[i] = (grid == code).astype(np.float32)

    # Hidden params as channels
    hp = np.stack([
        np.full((GRID_SIZE, GRID_SIZE), sample["ss"], dtype=np.float32),
        np.full((GRID_SIZE, GRID_SIZE), sample["st"], dtype=np.float32),
        np.full((GRID_SIZE, GRID_SIZE), sample["pa"], dtype=np.float32),
    ], axis=0)

    # ALL spatial features from extract_features (skip terrain_code at idx 0)
    # spatial_feats shape: (N_feat, H, W) — indices 1..27
    spatial_all = spatial_feats[1:]  # all except raw terrain code

    # Concat: GBM_logits(6) + terrain(8) + hidden(3) + spatial(27) = 44 channels
    inp = np.concatenate([gbm_logits, terrain_oh, hp, spatial_all], axis=0)
    target = sample["gt"].transpose(2, 0, 1).astype(np.float32)
    return inp, target


def augment_batch(inputs, targets):
    """Apply random rotations and flips for data augmentation. Returns augmented arrays."""
    aug_inputs = []
    aug_targets = []
    for inp, tgt in zip(inputs, targets):
        # Original
        aug_inputs.append(inp)
        aug_targets.append(tgt)
        # 3 rotations
        for k in [1, 2, 3]:
            aug_inputs.append(np.rot90(inp, k, axes=(1, 2)).copy())
            aug_targets.append(np.rot90(tgt, k, axes=(1, 2)).copy())
        # Horizontal flip
        aug_inputs.append(inp[:, :, ::-1].copy())
        aug_targets.append(tgt[:, :, ::-1].copy())
        # Vertical flip
        aug_inputs.append(inp[:, ::-1, :].copy())
        aug_targets.append(tgt[:, ::-1, :].copy())
        # Diagonal flips
        aug_inputs.append(np.rot90(inp[:, :, ::-1], 1, axes=(1, 2)).copy())
        aug_targets.append(np.rot90(tgt[:, :, ::-1], 1, axes=(1, 2)).copy())
        aug_inputs.append(np.rot90(inp[:, ::-1, :], 1, axes=(1, 2)).copy())
        aug_targets.append(np.rot90(tgt[:, ::-1, :], 1, axes=(1, 2)).copy())
    return np.stack(aug_inputs), np.stack(aug_targets)


def build_cnn_inputs(samples, gbm_models):
    """Build CNN training data with augmentation."""
    inputs = []
    targets = []
    for s in samples:
        inp, tgt = build_cnn_input_single(s, gbm_models)
        inputs.append(inp)
        targets.append(tgt)
    inputs = np.stack(inputs)
    targets = np.stack(targets)
    # Augment: 8x more data (original + 3 rotations + 2 flips + 2 diagonal flips)
    inputs, targets = augment_batch(inputs, targets)
    return inputs, targets


def entropy_weighted_kl_loss(pred_logits, target):
    """Entropy-weighted KL divergence matching competition scoring."""
    pred = F.softmax(pred_logits, dim=1)  # (B, 6, H, W)
    pred = pred.clamp(min=1e-7)
    target = target.clamp(min=1e-10)

    # KL per cell: sum over classes
    kl = (target * (target.log() - pred.log())).sum(dim=1)  # (B, H, W)

    # Entropy per cell
    entropy = -(target * target.log()).sum(dim=1)  # (B, H, W)

    # Weighted mean
    total_entropy = entropy.sum()
    if total_entropy < 1e-8:
        return torch.tensor(0.0, device=pred.device)
    loss = (entropy * kl).sum() / total_entropy
    return loss


def train_cnn(inputs, targets, n_epochs=200, lr=5e-4):
    """Train the CNN on augmented dataset."""
    in_channels = inputs.shape[1]
    model = ResidualCNN(in_channels).to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)

    X = torch.from_numpy(inputs).to(DEVICE)
    Y = torch.from_numpy(targets).to(DEVICE)

    n_params = sum(p.numel() for p in model.parameters())
    print(f"  CNN: {n_params} params, {in_channels} input channels, {len(inputs)} samples")

    best_loss = float("inf")
    patience = 30
    no_improve = 0
    best_state = None
    batch_size = 32

    for epoch in range(n_epochs):
        model.train()
        indices = torch.randperm(len(inputs))

        epoch_loss = 0
        n_batches = 0
        for i in range(0, len(indices), batch_size):
            batch_idx = indices[i:i+batch_size]
            xb = X[batch_idx]
            yb = Y[batch_idx]

            logits = model(xb)
            loss = entropy_weighted_kl_loss(logits, yb)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            epoch_loss += loss.item()
            n_batches += 1

        scheduler.step()
        avg_loss = epoch_loss / n_batches

        if avg_loss < best_loss - 1e-6:
            best_loss = avg_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1

        if no_improve >= patience:
            print(f"  CNN early stop at epoch {epoch}, best loss={best_loss:.6f}")
            break

        if (epoch + 1) % 50 == 0:
            print(f"  CNN epoch {epoch+1}: loss={avg_loss:.6f} best={best_loss:.6f}")

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model


def predict_with_cnn(cnn_model, gbm_models, sample):
    """Full prediction with test-time augmentation.

    CNN outputs corrected logits (GBM_logits + learned correction).
    We average softmax predictions over augmentations.
    """
    grid = sample["grid"]
    inp, _ = build_cnn_input_single(sample, gbm_models)

    # Test-time augmentation: average predictions over rotations/flips
    cnn_model.eval()
    preds = []
    inp_np = inp  # (C, H, W)
    transforms = [
        lambda x: x,
        lambda x: np.rot90(x, 1, axes=(1, 2)),
        lambda x: np.rot90(x, 2, axes=(1, 2)),
        lambda x: np.rot90(x, 3, axes=(1, 2)),
        lambda x: x[:, :, ::-1],
        lambda x: x[:, ::-1, :],
    ]
    inverse_transforms = [
        lambda x: x,
        lambda x: np.rot90(x, -1, axes=(1, 2)),
        lambda x: np.rot90(x, -2, axes=(1, 2)),
        lambda x: np.rot90(x, -3, axes=(1, 2)),
        lambda x: x[:, :, ::-1],
        lambda x: x[:, ::-1, :],
    ]

    with torch.no_grad():
        for tfm, inv_tfm in zip(transforms, inverse_transforms):
            aug_inp = tfm(inp_np).copy()
            inp_t = torch.from_numpy(aug_inp[None]).to(DEVICE)
            logits = cnn_model(inp_t)
            p = F.softmax(logits, dim=1)[0].cpu().numpy()
            p = inv_tfm(p).copy()
            preds.append(p)

    pred = np.mean(preds, axis=0).transpose(1, 2, 0)  # (40, 40, 6)

    # Static overrides
    ocean_mask = grid == 10
    mountain_mask = grid == 5
    if ocean_mask.any():
        pred[ocean_mask] = 0.0
        pred[ocean_mask, 0] = 1.0
    if mountain_mask.any():
        pred[mountain_mask] = 0.0
        pred[mountain_mask, 5] = 1.0

    pred = np.clip(pred, PROB_FLOOR, None)
    pred = pred / pred.sum(axis=-1, keepdims=True)
    return pred


# ============================================================
# LOO CV with GBM + CNN
# ============================================================
def train_and_predict(train_samples, test_samples):
    """Train GBM on train, then CNN on GBM outputs, predict test."""
    fold_t0 = time.time()

    # Step 1: Train GBM
    print(f"    Step 1/4: Training GBM on {len(train_samples)} samples...", flush=True)
    n_cells = GRID_SIZE * GRID_SIZE
    n_feat = len(FEATURE_NAMES)
    X_train = np.zeros((len(train_samples) * n_cells, n_feat), dtype=np.float32)
    Y_train = np.zeros((len(train_samples) * n_cells, N_CLASSES), dtype=np.float32)

    for i, s in enumerate(train_samples):
        flat_feats, _ = extract_features(s["grid"], s["ss"], s["st"], s["pa"])
        X_train[i*n_cells:(i+1)*n_cells] = flat_feats
        Y_train[i*n_cells:(i+1)*n_cells] = s["gt"].reshape(n_cells, N_CLASSES)

    gbm_models = train_gbm(X_train, Y_train)

    # Step 2: Build CNN training data from GBM predictions on train set
    t1 = time.time()
    print(f"    Step 2/4: Building CNN inputs...", flush=True)
    cnn_inputs, cnn_targets = build_cnn_inputs(train_samples, gbm_models)
    print(f"    CNN inputs built in {time.time()-t1:.1f}s, shape={cnn_inputs.shape}", flush=True)

    # Step 3: Train CNN
    print(f"    Step 3/4: Training CNN...", flush=True)
    cnn_model = train_cnn(cnn_inputs, cnn_targets)

    # Step 4: Predict test samples
    print(f"    Step 4/4: Predicting {len(test_samples)} test samples...", flush=True)
    predictions = []
    for s in test_samples:
        pred = predict_with_cnn(cnn_model, gbm_models, s)
        predictions.append(pred)

    print(f"    Fold done in {time.time()-fold_t0:.1f}s", flush=True)
    return predictions


# Also run GBM-only baseline for comparison
def train_and_predict_gbm_only(train_samples, test_samples):
    fold_t0 = time.time()
    print(f"    Training GBM on {len(train_samples)} samples...", flush=True)
    n_cells = GRID_SIZE * GRID_SIZE
    n_feat = len(FEATURE_NAMES)
    X_train = np.zeros((len(train_samples) * n_cells, n_feat), dtype=np.float32)
    Y_train = np.zeros((len(train_samples) * n_cells, N_CLASSES), dtype=np.float32)

    for i, s in enumerate(train_samples):
        flat_feats, _ = extract_features(s["grid"], s["ss"], s["st"], s["pa"])
        X_train[i*n_cells:(i+1)*n_cells] = flat_feats
        Y_train[i*n_cells:(i+1)*n_cells] = s["gt"].reshape(n_cells, N_CLASSES)

    gbm_models = train_gbm(X_train, Y_train)

    predictions = []
    for s in test_samples:
        flat_feats, _ = extract_features(s["grid"], s["ss"], s["st"], s["pa"])
        pred = predict_gbm(gbm_models, flat_feats, s["grid"])
        predictions.append(pred)

    print(f"    Fold done in {time.time()-fold_t0:.1f}s", flush=True)
    return predictions


if __name__ == "__main__":
    print("=" * 60)
    print("Experiment 1: CNN Residual on GBM")
    print("=" * 60)

    if "--gbm-only" in sys.argv:
        print("\n--- GBM-only baseline ---")
        run_loo_cv(train_and_predict_gbm_only)
    else:
        print("\n--- GBM + CNN Residual ---")
        score = run_loo_cv(train_and_predict)
        print(f"\nFinal LOO score: {score:.1f}")
