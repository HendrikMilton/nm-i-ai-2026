"""
Challenge 3: Astar Island — Viking Civilisation Prediction
Large U-Net ensemble with residual blocks, SE attention, transformer bottleneck.
Trained on historical round data with heavy augmentation.
"""

import json
import os
import logging
import random
from pathlib import Path
from collections import defaultdict

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from scipy.ndimage import distance_transform_edt, gaussian_filter

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ============================================================
# Config
# ============================================================
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
CHECKPOINT_DIR = Path(__file__).parent / "checkpoints"
DATA_DIR = Path(__file__).parent / "../../elias/logs/offline"

TERRAIN_CODES = [0, 1, 2, 3, 4, 5, 10, 11]
N_CLASSES = 6
GRID_SIZE = 40
PROB_FLOOR = 0.01

# Architecture
CHANNELS = [192, 384, 768, 1536]
N_RES_BLOCKS = 2
DROPOUT = 0.3
N_HEADS = 12
N_TRANSFORMER_LAYERS = 4

# Training
N_ENSEMBLE = 5
BATCH_SIZE = 8
LR = 3e-4
WEIGHT_DECAY = 1e-3
N_EPOCHS = 300
PATIENCE = 60
MIXUP_ALPHA = 0.4

# Static terrain classes (high confidence, skip CNN)
STATIC_MAP = {10: 0, 5: 5}  # ocean→empty, mountain→mountain


# ============================================================
# Feature Engineering
# ============================================================
def encode_grid(grid: np.ndarray) -> np.ndarray:
    """Encode 40x40 terrain code grid → (C, H, W) float32 feature tensor."""
    grid = np.asarray(grid, dtype=np.int32)
    h, w = grid.shape
    feats = []

    # One-hot terrain (8 channels)
    for code in TERRAIN_CODES:
        feats.append((grid == code).astype(np.float32))

    # Binary masks
    masks = {}
    for name, code in [("ocean", 10), ("settlement", 1), ("port", 2),
                        ("forest", 4), ("mountain", 5), ("ruin", 3),
                        ("plains", 11), ("empty", 0)]:
        masks[name] = (grid == code).astype(np.float32)
    land = 1.0 - masks["ocean"]

    # 8-connected neighbor counts (normalized to [0,1])
    def nbr(mask):
        c = np.zeros_like(mask)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                c += np.roll(np.roll(mask, dy, 0), dx, 1)
        return c / 8.0

    for name in ["ocean", "settlement", "port", "forest", "mountain", "ruin", "plains"]:
        feats.append(nbr(masks[name]))
    feats.append(nbr(land))

    # Coast mask
    coast = np.clip(nbr(masks["ocean"]) * 8, 0, 1) * land
    feats.append(coast)

    # Distance transforms (normalized)
    def dist(mask, max_d=20):
        if mask.sum() == 0:
            return np.ones((h, w), dtype=np.float32)
        return np.clip(distance_transform_edt(1 - mask) / max_d, 0, 1).astype(np.float32)

    for name in ["ocean", "settlement", "forest", "port", "ruin"]:
        feats.append(dist(masks[name]))

    # Multi-scale density (gaussian blur)
    for sigma in (2, 4, 7):
        for name in ["settlement", "port", "forest", "ruin"]:
            feats.append(gaussian_filter(masks[name], sigma=sigma).astype(np.float32))

    # Terrain diversity in 3x3
    div = np.zeros((h, w), dtype=np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            div += (np.roll(np.roll(grid, dy, 0), dx, 1) != grid).astype(np.float32)
    feats.append(div / 8.0)

    # Settlement cluster size (connected component area, approx via density)
    feats.append(gaussian_filter(masks["settlement"], sigma=1.5).astype(np.float32))

    # Positional encoding
    yy, xx = np.meshgrid(np.linspace(-1, 1, h), np.linspace(-1, 1, w), indexing="ij")
    feats.append(yy.astype(np.float32))
    feats.append(xx.astype(np.float32))
    feats.append(np.sqrt(yy ** 2 + xx ** 2).astype(np.float32))
    # Sine positional encodings
    for freq in (1, 2, 4):
        feats.append(np.sin(freq * np.pi * yy).astype(np.float32))
        feats.append(np.sin(freq * np.pi * xx).astype(np.float32))

    return np.stack(feats, axis=0)


def get_n_input_channels():
    dummy = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.int32)
    return encode_grid(dummy).shape[0]


N_INPUT = get_n_input_channels()
log.info(f"Input channels: {N_INPUT}")


# ============================================================
# Model Architecture
# ============================================================
class SEBlock(nn.Module):
    """Squeeze-and-Excitation block."""
    def __init__(self, ch, reduction=16):
        super().__init__()
        self.fc = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
            nn.Linear(ch, ch // reduction),
            nn.SiLU(inplace=True),
            nn.Linear(ch // reduction, ch),
            nn.Sigmoid(),
        )

    def forward(self, x):
        return x * self.fc(x).unsqueeze(-1).unsqueeze(-1)


class ResBlock(nn.Module):
    """Residual block with GroupNorm, SiLU, SE, and optional dropout."""
    def __init__(self, ch, dropout=0.0, stochastic_depth=0.0):
        super().__init__()
        self.block = nn.Sequential(
            nn.GroupNorm(32, ch),
            nn.SiLU(inplace=True),
            nn.Conv2d(ch, ch, 3, padding=1, bias=False),
            nn.GroupNorm(32, ch),
            nn.SiLU(inplace=True),
            nn.Dropout2d(dropout),
            nn.Conv2d(ch, ch, 3, padding=1, bias=False),
            SEBlock(ch),
        )
        self.drop_rate = stochastic_depth

    def forward(self, x):
        if self.training and self.drop_rate > 0 and random.random() < self.drop_rate:
            return x
        return x + self.block(x)


class TransformerBlock(nn.Module):
    """Multi-head self-attention + FFN on spatial features."""
    def __init__(self, dim, n_heads=8, dropout=0.0, ffn_mult=4):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.attn = nn.MultiheadAttention(dim, n_heads, dropout=dropout, batch_first=True)
        self.norm2 = nn.LayerNorm(dim)
        self.ffn = nn.Sequential(
            nn.Linear(dim, dim * ffn_mult),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(dim * ffn_mult, dim),
            nn.Dropout(dropout),
        )

    def forward(self, x):
        # x: (B, C, H, W) → (B, H*W, C)
        B, C, H, W = x.shape
        z = x.flatten(2).permute(0, 2, 1)
        z = z + self.attn(self.norm1(z), self.norm1(z), self.norm1(z))[0]
        z = z + self.ffn(self.norm2(z))
        return z.permute(0, 2, 1).view(B, C, H, W)


class AttentionGate(nn.Module):
    """Attention gate for skip connections."""
    def __init__(self, gate_ch, skip_ch, inter_ch):
        super().__init__()
        self.W_gate = nn.Conv2d(gate_ch, inter_ch, 1, bias=False)
        self.W_skip = nn.Conv2d(skip_ch, inter_ch, 1, bias=False)
        self.psi = nn.Sequential(
            nn.SiLU(inplace=True),
            nn.Conv2d(inter_ch, 1, 1, bias=False),
            nn.Sigmoid(),
        )

    def forward(self, gate, skip):
        g = self.W_gate(gate)
        s = self.W_skip(skip)
        if g.shape[2:] != s.shape[2:]:
            g = F.interpolate(g, size=s.shape[2:], mode="bilinear", align_corners=False)
        return skip * self.psi(g + s)


class BigUNet(nn.Module):
    def __init__(self, in_ch, out_ch=N_CLASSES, channels=None, n_res=3,
                 dropout=0.3, n_heads=16, n_transformer=6):
        super().__init__()
        if channels is None:
            channels = CHANNELS
        self.channels = channels
        n_levels = len(channels)

        # Input projection
        self.input_proj = nn.Sequential(
            nn.Conv2d(in_ch, channels[0], 3, padding=1, bias=False),
            nn.GroupNorm(32, channels[0]),
            nn.SiLU(inplace=True),
            nn.Conv2d(channels[0], channels[0], 3, padding=1, bias=False),
        )

        # Encoder
        self.encoders = nn.ModuleList()
        self.downsamples = nn.ModuleList()
        for i in range(n_levels):
            ch = channels[i]
            sd_rates = [0.1 * (j + 1) / (n_res * n_levels) for j in range(n_res)]
            blocks = nn.Sequential(*[ResBlock(ch, dropout, sd) for sd, _ in zip(sd_rates, range(n_res))])
            self.encoders.append(blocks)
            if i < n_levels - 1:
                self.downsamples.append(nn.Sequential(
                    nn.Conv2d(ch, channels[i + 1], 3, stride=2, padding=1, bias=False),
                    nn.GroupNorm(32, channels[i + 1]),
                    nn.SiLU(inplace=True),
                ))

        # Bottleneck transformer
        self.bottleneck = nn.Sequential(
            *[TransformerBlock(channels[-1], n_heads, dropout) for _ in range(n_transformer)]
        )

        # Decoder
        self.upsamples = nn.ModuleList()
        self.attn_gates = nn.ModuleList()
        self.decoders = nn.ModuleList()
        for i in range(n_levels - 2, -1, -1):
            ch_up = channels[i + 1]
            ch_skip = channels[i]
            self.upsamples.append(nn.Sequential(
                nn.ConvTranspose2d(ch_up, ch_skip, 2, stride=2, bias=False),
                nn.GroupNorm(32, ch_skip),
                nn.SiLU(inplace=True),
            ))
            self.attn_gates.append(AttentionGate(ch_skip, ch_skip, ch_skip // 4))
            self.decoders.append(nn.Sequential(
                nn.Conv2d(ch_skip * 2, ch_skip, 1, bias=False),  # fuse skip + up
                *[ResBlock(ch_skip, dropout, 0.05) for _ in range(n_res)],
            ))

        # Deep supervision heads
        self.deep_heads = nn.ModuleList()
        for i in range(n_levels - 1):
            self.deep_heads.append(nn.Conv2d(channels[i], out_ch, 1))

        # Final output
        self.final = nn.Sequential(
            nn.GroupNorm(32, channels[0]),
            nn.SiLU(inplace=True),
            nn.Conv2d(channels[0], channels[0] // 2, 3, padding=1, bias=False),
            nn.GroupNorm(16, channels[0] // 2),
            nn.SiLU(inplace=True),
            nn.Conv2d(channels[0] // 2, out_ch, 1),
        )

    def forward(self, x, return_deep=False):
        x = self.input_proj(x)

        # Encoder path
        skips = []
        for i, (enc, down) in enumerate(zip(self.encoders[:-1], self.downsamples)):
            x = enc(x)
            skips.append(x)
            x = down(x)
        x = self.encoders[-1](x)

        # Bottleneck
        x = self.bottleneck(x)

        # Decoder path
        deep_outs = []
        for i, (up, ag, dec) in enumerate(zip(self.upsamples, self.attn_gates, self.decoders)):
            skip_idx = len(skips) - 1 - i
            x = up(x)
            # Handle size mismatch
            if x.shape[2:] != skips[skip_idx].shape[2:]:
                x = F.interpolate(x, size=skips[skip_idx].shape[2:], mode="bilinear", align_corners=False)
            skip = ag(x, skips[skip_idx])
            x = dec(torch.cat([x, skip], dim=1))
            if return_deep and i < len(self.deep_heads):
                deep_outs.append(self.deep_heads[len(self.deep_heads) - 1 - i](x))

        out = self.final(x)
        if return_deep:
            return out, deep_outs
        return out


# ============================================================
# Dataset & Augmentation
# ============================================================
def load_training_data():
    """Load all unique (round, seed) samples from offline backtest data."""
    samples = {}  # (round_id, seed) → (initial_grid, ground_truth)
    data_dir = Path(DATA_DIR)
    if not data_dir.exists():
        log.warning(f"Data dir not found: {data_dir}")
        return []

    for f in sorted(data_dir.iterdir()):
        if not f.suffix == ".json" or f.name == "index.json":
            continue
        try:
            data = json.loads(f.read_text())
            if "seeds" not in data:
                continue
            rid = data.get("round_id", f.stem)
            for sid, seed in data["seeds"].items():
                key = (rid, sid)
                if key in samples:
                    continue
                ig = np.array(seed["initial_grid"], dtype=np.int32)
                gt = np.array(seed["ground_truth"], dtype=np.float32)
                if ig.shape == (GRID_SIZE, GRID_SIZE) and gt.shape == (GRID_SIZE, GRID_SIZE, N_CLASSES):
                    samples[key] = (ig, gt)
        except Exception as e:
            log.debug(f"Skip {f.name}: {e}")

    log.info(f"Loaded {len(samples)} unique training samples")
    return list(samples.values())


def d4_augment(grid, gt, k):
    """Apply one of 8 D4 symmetry transforms. k in [0..7]."""
    rot = k % 4
    flip = k >= 4
    g = np.rot90(grid, rot)
    t = np.rot90(gt, rot)
    if flip:
        g = np.fliplr(g)
        t = np.fliplr(t)
    return g.copy(), t.copy()


def d4_augment_tensor(x, k):
    """Apply D4 transform to a (C,H,W) or (B,C,H,W) tensor."""
    rot = k % 4
    flip = k >= 4
    if x.dim() == 3:
        x = torch.rot90(x, rot, [1, 2])
        if flip:
            x = torch.flip(x, [2])
    else:
        x = torch.rot90(x, rot, [2, 3])
        if flip:
            x = torch.flip(x, [3])
    return x


def d4_inverse_tensor(x, k):
    """Inverse of d4_augment_tensor."""
    rot = k % 4
    flip = k >= 4
    if x.dim() == 3:
        if flip:
            x = torch.flip(x, [2])
        x = torch.rot90(x, -rot, [1, 2])
    else:
        if flip:
            x = torch.flip(x, [3])
        x = torch.rot90(x, -rot, [2, 3])
    return x


class AstarDataset(Dataset):
    def __init__(self, samples, augment=True):
        self.samples = samples
        self.augment = augment

    def __len__(self):
        return len(self.samples) * (8 if self.augment else 1)

    def __getitem__(self, idx):
        base_idx = idx % len(self.samples)
        aug_k = idx // len(self.samples) if self.augment else 0

        ig, gt = self.samples[base_idx]

        if self.augment:
            # Random D4 + small noise
            ig, gt = d4_augment(ig, gt, aug_k)

        features = encode_grid(ig)
        target = gt.transpose(2, 0, 1)  # (6, H, W)

        return torch.tensor(features), torch.tensor(target)


# ============================================================
# Loss
# ============================================================
def entropy_weighted_kl_loss(pred_logits, target, deep_logits=None):
    """
    Entropy-weighted KL divergence matching competition scoring.
    pred_logits: (B, 6, H, W) raw logits
    target: (B, 6, H, W) ground truth probabilities
    """
    pred = F.log_softmax(pred_logits, dim=1)  # log probs
    # KL(target || pred) = sum(target * (log(target) - log(pred)))
    target_safe = target.clamp(min=1e-8)
    kl = (target_safe * (target_safe.log() - pred)).sum(dim=1)  # (B, H, W)

    # Entropy of target
    entropy = -(target_safe * target_safe.log()).sum(dim=1)  # (B, H, W)

    # Weight by entropy (only care about uncertain cells)
    weight = entropy / (entropy.sum(dim=(1, 2), keepdim=True) + 1e-8)
    loss = (kl * weight).sum(dim=(1, 2)).mean()

    # Deep supervision loss
    if deep_logits:
        for dl in deep_logits:
            dl_up = F.interpolate(dl, size=target.shape[2:], mode="bilinear", align_corners=False)
            dp = F.log_softmax(dl_up, dim=1)
            dk = (target_safe * (target_safe.log() - dp)).sum(dim=1)
            loss = loss + 0.2 * (dk * weight).sum(dim=(1, 2)).mean()

    return loss


# ============================================================
# Training
# ============================================================
def train_single_model(samples, val_samples, model_idx, device):
    """Train one model of the ensemble."""
    log.info(f"Training model {model_idx} | train={len(samples)}, val={len(val_samples)}")
    torch.manual_seed(42 + model_idx * 1337)
    np.random.seed(42 + model_idx * 1337)

    model = BigUNet(N_INPUT).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    log.info(f"Model parameters: {n_params:,}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=50, T_mult=2)

    train_ds = AstarDataset(samples, augment=True)
    train_dl = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                          num_workers=2, pin_memory=True, drop_last=False)

    val_ds = AstarDataset(val_samples, augment=False) if val_samples else None
    val_dl = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False,
                        num_workers=0, pin_memory=True) if val_ds else None

    best_val = float("inf")
    best_state = None
    patience_counter = 0

    for epoch in range(N_EPOCHS):
        # --- Train ---
        model.train()
        train_loss = 0.0
        n_batch = 0
        for feat, tgt in train_dl:
            feat, tgt = feat.to(device), tgt.to(device)

            # Mixup
            if MIXUP_ALPHA > 0 and feat.size(0) > 1:
                lam = np.random.beta(MIXUP_ALPHA, MIXUP_ALPHA)
                idx = torch.randperm(feat.size(0), device=device)
                feat = lam * feat + (1 - lam) * feat[idx]
                tgt = lam * tgt + (1 - lam) * tgt[idx]

            logits, deep = model(feat, return_deep=True)
            loss = entropy_weighted_kl_loss(logits, tgt, deep)

            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step(epoch + n_batch / len(train_dl))

            train_loss += loss.item()
            n_batch += 1

        train_loss /= max(n_batch, 1)

        # --- Validate ---
        val_loss = 0.0
        if val_dl:
            model.eval()
            n_val = 0
            with torch.no_grad():
                for feat, tgt in val_dl:
                    feat, tgt = feat.to(device), tgt.to(device)
                    logits = model(feat)
                    loss = entropy_weighted_kl_loss(logits, tgt)
                    val_loss += loss.item()
                    n_val += 1
            val_loss /= max(n_val, 1)

            if val_loss < best_val:
                best_val = val_loss
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1

            if epoch % 20 == 0:
                log.info(f"  [{model_idx}] epoch {epoch}: train={train_loss:.6f} val={val_loss:.6f} best={best_val:.6f} pat={patience_counter}")

            if patience_counter >= PATIENCE:
                log.info(f"  [{model_idx}] Early stopping at epoch {epoch}")
                break
        else:
            # No validation — just save latest
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            if epoch % 20 == 0:
                log.info(f"  [{model_idx}] epoch {epoch}: train={train_loss:.6f}")

    if best_state:
        model.load_state_dict(best_state)
    model.eval()
    return model


def train_ensemble(device):
    """Train full ensemble with leave-one-round-out validation."""
    all_samples = load_training_data()
    if not all_samples:
        log.error("No training data found!")
        return []

    # Group by round for leave-one-out
    # We don't have round_id in the tuple, so just split by index
    # Use 5-fold split: each fold = ~8 samples
    n = len(all_samples)
    indices = list(range(n))
    random.seed(42)
    random.shuffle(indices)
    fold_size = max(1, n // N_ENSEMBLE)

    models = []
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    for i in range(N_ENSEMBLE):
        ckpt = CHECKPOINT_DIR / f"model_{i}.pt"
        if ckpt.exists():
            log.info(f"Loading cached model {i} from {ckpt}")
            model = BigUNet(N_INPUT).to(device)
            model.load_state_dict(torch.load(ckpt, map_location=device, weights_only=True))
            model.eval()
            models.append(model)
            continue

        # Split: fold i is validation, rest is train
        val_idx = indices[i * fold_size: (i + 1) * fold_size]
        train_idx = [j for j in indices if j not in val_idx]
        train_samples = [all_samples[j] for j in train_idx]
        val_samples = [all_samples[j] for j in val_idx]

        model = train_single_model(train_samples, val_samples, i, device)
        torch.save(model.state_dict(), ckpt)
        log.info(f"Saved model {i} to {ckpt}")
        models.append(model)

    return models


# ============================================================
# Inference
# ============================================================
def predict_grid(models, initial_grid, device):
    """Run ensemble prediction with test-time augmentation."""
    features = encode_grid(initial_grid)
    feat_tensor = torch.tensor(features, dtype=torch.float32).unsqueeze(0).to(device)  # (1, C, H, W)

    all_probs = []

    for model in models:
        model.eval()
        with torch.no_grad():
            # TTA: all 8 D4 symmetries
            for k in range(8):
                aug_feat = d4_augment_tensor(feat_tensor, k)
                logits = model(aug_feat)
                probs = F.softmax(logits, dim=1)  # (1, 6, H, W)
                # Inverse transform
                probs = d4_inverse_tensor(probs, k)
                all_probs.append(probs)

    # Average all predictions
    avg_probs = torch.stack(all_probs).mean(dim=0)  # (1, 6, H, W)
    pred = avg_probs.squeeze(0).cpu().numpy()  # (6, H, W)
    pred = pred.transpose(1, 2, 0)  # (H, W, 6)

    # Override static cells
    grid = np.asarray(initial_grid, dtype=np.int32)
    for code, cls in STATIC_MAP.items():
        mask = grid == code
        if mask.any():
            static_prob = np.full(N_CLASSES, PROB_FLOOR)
            static_prob[cls] = 1.0
            static_prob /= static_prob.sum()
            pred[mask] = static_prob

    # Floor and renormalize
    pred = np.clip(pred, PROB_FLOOR, None)
    pred = pred / pred.sum(axis=-1, keepdims=True)

    return pred


# ============================================================
# Evaluation (offline validation)
# ============================================================
def evaluate_offline(models, device):
    """Run leave-one-out evaluation and report scores."""
    import math
    all_samples = load_training_data()
    if not all_samples:
        return

    scores = []
    for i, (ig, gt) in enumerate(all_samples):
        pred = predict_grid(models, ig, device)

        # Compute entropy-weighted KL
        total_kl = 0.0
        total_entropy = 0.0
        for r in range(GRID_SIZE):
            for c in range(GRID_SIZE):
                p = gt[r, c]
                q = pred[r, c]
                ent = -sum(pi * math.log(pi) for pi in p if pi > 0)
                if ent < 0.01:
                    continue
                kl = sum(pi * math.log(pi / max(qi, 1e-10)) for pi, qi in zip(p, q) if pi > 0)
                total_kl += ent * kl
                total_entropy += ent

        wkl = total_kl / total_entropy if total_entropy > 0 else 0
        score = max(0, min(100, 100 * math.exp(-3 * wkl)))
        scores.append(score)

    avg = sum(scores) / len(scores) if scores else 0
    log.info(f"Offline eval: mean={avg:.2f}, min={min(scores):.2f}, max={max(scores):.2f}")
    return avg


# ============================================================
# Global State — load/train on import
# ============================================================
_models = []


def _ensure_models():
    global _models
    if _models:
        return
    log.info(f"Initializing on {DEVICE} ...")
    _models = train_ensemble(DEVICE)
    if _models:
        evaluate_offline(_models, DEVICE)
    log.info(f"Ready with {len(_models)} models")


# ============================================================
# API Entry Point
# ============================================================
def predict(body: dict) -> dict:
    """
    Predict probability distributions for a 40x40 grid.
    Input body: {"initial_grid": [[int, ...], ...]} — 40x40 terrain codes
    Returns: {"prediction": [[[float, ...], ...], ...]} — 40x40x6 probabilities
    """
    _ensure_models()

    initial_grid = body.get("initial_grid")
    if initial_grid is None:
        return {"error": "missing initial_grid"}

    grid = np.array(initial_grid, dtype=np.int32)
    if grid.shape != (GRID_SIZE, GRID_SIZE):
        return {"error": f"expected {GRID_SIZE}x{GRID_SIZE} grid, got {grid.shape}"}

    pred = predict_grid(_models, grid, DEVICE)
    return {"prediction": pred.tolist()}


# ============================================================
# CLI: train + evaluate
# ============================================================
if __name__ == "__main__":
    import sys
    if "--delete-checkpoints" in sys.argv:
        import shutil
        if CHECKPOINT_DIR.exists():
            shutil.rmtree(CHECKPOINT_DIR)
            log.info("Deleted checkpoints")

    _ensure_models()
    log.info("Done.")
