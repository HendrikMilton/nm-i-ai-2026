"""
Experiment 2: Direct Small U-Net for 40x40x6 probability prediction.
Replaces per-cell LightGBM with a spatial CNN.
"""
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from scipy.ndimage import distance_transform_edt, gaussian_filter
from eval_common import run_loo_cv, GRID_SIZE, N_CLASSES, PROB_FLOOR

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Terrain codes present in the data
TERRAIN_CODES = [0, 1, 2, 3, 4, 5, 10, 11]
CODE_TO_IDX = {c: i for i, c in enumerate(TERRAIN_CODES)}
N_TERRAIN = len(TERRAIN_CODES)

# ============================================================
# Feature extraction: grid -> (C, 40, 40) tensor
# ============================================================
def extract_input_channels(grid, ss, st, pa):
    """Build input tensor: terrain one-hot + spatial features + hidden params.
    Returns (C, 40, 40) numpy array.
    """
    h, w = grid.shape
    channels = []

    # 1. Terrain one-hot (8 channels)
    for code in TERRAIN_CODES:
        channels.append((grid == code).astype(np.float32))

    # 2. Neighbor counts (7 channels) - settlement, port, forest, mountain, ruin, plains, ocean
    masks = {
        "settlement": (grid == 1).astype(np.float32),
        "port": (grid == 2).astype(np.float32),
        "forest": (grid == 4).astype(np.float32),
        "mountain": (grid == 5).astype(np.float32),
        "ruin": (grid == 3).astype(np.float32),
        "plains": (grid == 11).astype(np.float32),
        "ocean": (grid == 10).astype(np.float32),
    }

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

    for name in ["settlement", "port", "forest", "mountain", "ruin", "plains", "ocean"]:
        channels.append(nbr_count(masks[name]))

    # 3. Distance transforms (4 channels) - settlement, ocean, port, forest
    def dist_norm(mask, max_d=20):
        if mask.sum() == 0:
            return np.ones((h, w), dtype=np.float32)
        return np.clip(distance_transform_edt(1 - mask) / max_d, 0, 1).astype(np.float32)

    channels.append(dist_norm(masks["settlement"]))
    channels.append(dist_norm(masks["ocean"]))
    channels.append(dist_norm(masks["port"]))
    channels.append(dist_norm(masks["forest"]))

    # 4. Densities (6 channels) - settle r3/r5/r7, forest r3/r5, port r3
    channels.append(gaussian_filter(masks["settlement"], sigma=3).astype(np.float32))
    channels.append(gaussian_filter(masks["settlement"], sigma=5).astype(np.float32))
    channels.append(gaussian_filter(masks["settlement"], sigma=7).astype(np.float32))
    channels.append(gaussian_filter(masks["forest"], sigma=3).astype(np.float32))
    channels.append(gaussian_filter(masks["forest"], sigma=5).astype(np.float32))
    channels.append(gaussian_filter(masks["port"], sigma=3).astype(np.float32))

    # 5. Hidden params (3 channels) - broadcast
    channels.append(np.full((h, w), ss, dtype=np.float32))
    channels.append(np.full((h, w), st, dtype=np.float32))
    channels.append(np.full((h, w), pa, dtype=np.float32))

    # 6. Coordinate channels (2 channels) - normalized x, y position
    yy, xx = np.meshgrid(np.linspace(0, 1, h), np.linspace(0, 1, w), indexing='ij')
    channels.append(yy.astype(np.float32))
    channels.append(xx.astype(np.float32))

    return np.stack(channels, axis=0)  # (C, 40, 40)


# ============================================================
# D4 augmentation (dihedral group of the square)
# ============================================================
def d4_augment(x, gt):
    """Generate all 8 D4 transformations of (x, gt).
    x: (C, H, W), gt: (H, W, 6) -> list of (x', gt') tuples.
    """
    augmented = []
    for k in range(4):
        xr = np.rot90(x, k, axes=(1, 2)).copy()
        gr = np.rot90(gt, k, axes=(0, 1)).copy()
        augmented.append((xr, gr))
        # Flip horizontally
        xf = np.flip(xr, axis=2).copy()
        gf = np.flip(gr, axis=1).copy()
        augmented.append((xf, gf))
    return augmented


# ============================================================
# U-Net architecture
# ============================================================
class ConvBlock(nn.Module):
    def __init__(self, in_ch, out_ch, dropout=0.0):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
            nn.GroupNorm(min(8, out_ch), out_ch),
            nn.SiLU(inplace=True),
            nn.Dropout2d(dropout),
            nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
            nn.GroupNorm(min(8, out_ch), out_ch),
            nn.SiLU(inplace=True),
        )
        self.skip = nn.Conv2d(in_ch, out_ch, 1) if in_ch != out_ch else nn.Identity()

    def forward(self, x):
        return self.conv(x) + self.skip(x)


class SmallUNet(nn.Module):
    def __init__(self, in_channels, out_channels=6, dropout=0.1):
        super().__init__()
        # Encoder
        self.enc1 = ConvBlock(in_channels, 32, dropout)
        self.enc2 = ConvBlock(32, 64, dropout)
        self.enc3 = ConvBlock(64, 128, dropout)

        self.pool = nn.MaxPool2d(2)

        # Decoder
        self.up2 = nn.ConvTranspose2d(128, 64, 2, stride=2)
        self.dec2 = ConvBlock(128, 64, dropout)
        self.up1 = nn.ConvTranspose2d(64, 32, 2, stride=2)
        self.dec1 = ConvBlock(64, 32, dropout)

        self.final = nn.Conv2d(32, out_channels, 1)

    def forward(self, x):
        # Encoder
        e1 = self.enc1(x)          # (B, 32, 40, 40)
        e2 = self.enc2(self.pool(e1))  # (B, 64, 20, 20)
        e3 = self.enc3(self.pool(e2))  # (B, 128, 10, 10)

        # Decoder
        d2 = self.up2(e3)          # (B, 64, 20, 20)
        d2 = self.dec2(torch.cat([d2, e2], dim=1))  # (B, 64, 20, 20)
        d1 = self.up1(d2)          # (B, 32, 40, 40)
        d1 = self.dec1(torch.cat([d1, e1], dim=1))  # (B, 32, 40, 40)

        return self.final(d1)       # (B, 6, 40, 40)


# ============================================================
# Loss: entropy-weighted KL divergence
# ============================================================
def entropy_weighted_kl_loss(pred_logits, gt):
    """
    pred_logits: (B, 6, H, W) raw logits
    gt: (B, 6, H, W) ground truth probabilities
    """
    pred_log_probs = F.log_softmax(pred_logits, dim=1)

    # KL(gt || pred) = sum_c gt_c * (log(gt_c) - log(pred_c))
    gt_safe = gt.clamp(min=1e-10)
    kl = (gt_safe * (gt_safe.log() - pred_log_probs)).sum(dim=1)  # (B, H, W)

    # Entropy of GT
    entropy = -(gt_safe * gt_safe.log()).sum(dim=1)  # (B, H, W)

    # Weighted KL
    total_entropy = entropy.sum()
    if total_entropy < 1e-8:
        return torch.tensor(0.0, device=pred_logits.device)

    weighted_kl = (entropy * kl).sum() / total_entropy

    return weighted_kl


# ============================================================
# Training + prediction function for LOO CV
# ============================================================
_fold_times = []

def train_and_predict(train_samples, test_samples):
    """Train U-Net on train_samples, predict on test_samples.
    Uses a round-based val split from train_samples for early stopping.
    """
    import time as _time
    fold_start = _time.time()
    in_channels = 30  # 8 + 7 + 4 + 6 + 3 + 2 (coord)

    # Use all training data (no val split) — rely on dropout + weight decay for regularization
    train_x_list = []
    train_y_list = []
    for s in train_samples:
        x = extract_input_channels(s["grid"], s["ss"], s["st"], s["pa"])
        gt = s["gt"]
        for xa, ga in d4_augment(x, gt):
            train_x_list.append(xa)
            train_y_list.append(ga.transpose(2, 0, 1))  # (6, H, W)

    train_x = torch.tensor(np.stack(train_x_list), dtype=torch.float32)
    train_y = torch.tensor(np.stack(train_y_list), dtype=torch.float32)

    # Model
    model = SmallUNet(in_channels, N_CLASSES).to(DEVICE)
    n_epochs = 80
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-2)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)

    batch_size = min(32, len(train_x))

    dataset = torch.utils.data.TensorDataset(train_x, train_y)
    loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True,
                                          pin_memory=True, num_workers=0)

    for epoch in range(n_epochs):
        model.train()
        for bx, by in loader:
            bx, by = bx.to(DEVICE), by.to(DEVICE)
            optimizer.zero_grad()
            logits = model(bx)
            loss = entropy_weighted_kl_loss(logits, by)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        scheduler.step()

    fold_elapsed = _time.time() - fold_start
    _fold_times.append(fold_elapsed)
    avg_fold = np.mean(_fold_times)
    remaining = 21 - len(_fold_times)
    print(f"    Fold done in {fold_elapsed:.0f}s (avg {avg_fold:.0f}s), ~{remaining} folds left, ETA ~{avg_fold*remaining:.0f}s")

    model.eval()

    # Predict test samples with TTA (D4 augmentation at test time)
    predictions = []
    with torch.no_grad():
        for s in test_samples:
            x = extract_input_channels(s["grid"], s["ss"], s["st"], s["pa"])
            # TTA: average predictions over all 8 D4 transforms
            avg_pred = np.zeros((GRID_SIZE, GRID_SIZE, N_CLASSES), dtype=np.float32)
            for k in range(4):
                for flip in [False, True]:
                    xa = np.rot90(x, k, axes=(1, 2)).copy()
                    if flip:
                        xa = np.flip(xa, axis=2).copy()
                    xt = torch.tensor(xa[None], dtype=torch.float32).to(DEVICE)
                    logits = model(xt)
                    probs = F.softmax(logits, dim=1)[0].cpu().numpy()  # (6, H, W)
                    p = probs.transpose(1, 2, 0)  # (H, W, 6)
                    # Undo flip
                    if flip:
                        p = np.flip(p, axis=1).copy()
                    # Undo rotation
                    p = np.rot90(p, -k, axes=(0, 1)).copy()
                    avg_pred += p
            pred = avg_pred / 8.0

            # Static overrides
            grid = s["grid"]
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
            predictions.append(pred)

    return predictions


if __name__ == "__main__":
    print(f"Device: {DEVICE}")
    score = run_loo_cv(train_and_predict)
    print(f"\nFinal LOO Score: {score:.1f}")
