"""
Common evaluation harness for experiments.
Each experiment's solve.py must export: predict_grid(grid, ss, st, pa, obs_probs, n_obs, settlement_stats)
Evaluates on all rounds with GT using leave-one-round-out and holdout on latest rounds.
"""
import json
import sys
import math
import time
import numpy as np
from pathlib import Path

GRID_SIZE = 40
N_CLASSES = 6
PROB_FLOOR = 0.01

# Paths relative to challenge3/
CHALLENGE3_DIR = Path(__file__).parent.parent
V2_DATA_DIR = CHALLENGE3_DIR / "../../elias/logs/offline"
ROUND_DATA_DIR = CHALLENGE3_DIR / "round_data"


def score_prediction(pred, gt):
    pred = np.clip(pred, PROB_FLOOR, None)
    pred /= pred.sum(axis=-1, keepdims=True)
    gt_s = np.clip(gt, 1e-10, None)
    pred_s = np.clip(pred, 1e-10, None)
    entropy = -(gt_s * np.log(gt_s)).sum(axis=-1)
    kl = (gt_s * (np.log(gt_s) - np.log(pred_s))).sum(axis=-1)
    total_entropy = entropy.sum()
    if total_entropy < 1e-8: return 100.0
    weighted_kl = (entropy * kl).sum() / total_entropy
    return max(0, min(100, 100 * math.exp(-3 * weighted_kl)))


def load_all_samples():
    """Load all rounds with per-seed grids + GT + hidden params."""
    from scipy.ndimage import distance_transform_edt
    import glob as glob_module

    samples = []

    def compute_hidden_params(grid, gt):
        sm = grid == 1
        om = grid == 10
        land = ~om
        ptm = grid == 2
        ss = gt[sm, 1].mean() if sm.sum() > 0 else 0.3
        if sm.sum() > 0:
            dist = distance_transform_edt(~sm).astype(int)
            d0 = gt[(dist == 0) & land, 1].mean() if ((dist == 0) & land).sum() > 0 else 0.001
            d2 = gt[(dist == 2) & land, 1].mean() if ((dist == 2) & land).sum() > 0 else 0
            st = d2 / max(d0, 0.001)
        else:
            st = 0.45
        pa = gt[ptm, 2].mean() if ptm.sum() > 0 else 0.15
        return float(ss), float(st), float(pa)

    seen = set()

    # v2_R files (R1-R12)
    for f in sorted(V2_DATA_DIR.glob("v2_R*.json")):
        if f.stem.count("_") > 1: continue
        with open(f) as fh: d = json.load(fh)
        rn = d["round_number"]
        if rn in seen: continue
        seen.add(rn)
        for sid in ["0","1","2","3","4"]:
            s = d["seeds"][sid]
            ig = np.array(s["initial_grid"], dtype=np.int32)
            gt = np.array(s["ground_truth"], dtype=np.float32)
            if ig.shape != (40,40) or gt.shape != (40,40,6): continue
            ss, st, pa = compute_hidden_params(ig, gt)
            samples.append({"grid": ig, "gt": gt, "ss": ss, "st": st, "pa": pa, "round": rn, "seed": int(sid)})

    # Extra v2 files
    for extra in ["v2_R13_baseline.json", "v2_depth_R14.json", "v2_R16.json"]:
        path = V2_DATA_DIR / extra
        if not path.exists(): continue
        with open(path) as fh: d = json.load(fh)
        rn = d["round_number"]
        if rn in seen: continue
        seen.add(rn)
        for sid in ["0","1","2","3","4"]:
            s = d["seeds"][sid]
            ig = np.array(s["initial_grid"], dtype=np.int32)
            gt = np.array(s["ground_truth"], dtype=np.float32)
            if ig.shape != (40,40) or gt.shape != (40,40,6): continue
            ss, st, pa = compute_hidden_params(ig, gt)
            samples.append({"grid": ig, "gt": gt, "ss": ss, "st": st, "pa": pa, "round": rn, "seed": int(sid)})

    # round_data + submit files
    for f in sorted(ROUND_DATA_DIR.glob("round_*.json")):
        if "_submit" in f.name: continue
        with open(f) as fh: d = json.load(fh)
        rn = d.get("round_number")
        if rn is None or rn in seen: continue
        seeds = d.get("seeds", [])
        if isinstance(seeds, dict): seeds = list(seeds.values())
        has_gt = any(s.get("ground_truth") is not None for s in seeds if isinstance(s, dict))
        if not has_gt: continue

        submit_path = ROUND_DATA_DIR / f"round_{rn:02d}_submit.json"
        sub_seeds = {}
        if submit_path.exists():
            try:
                with open(submit_path) as fh: sub_seeds = json.load(fh).get("seeds", {})
            except: pass

        seen.add(rn)
        for s in seeds:
            if not isinstance(s, dict): continue
            gt = s.get("ground_truth")
            if gt is None: continue
            gt = np.array(gt, dtype=np.float32)
            sid = s.get("seed_index", 0)
            sub_seed = sub_seeds.get(str(sid), {})
            ig_raw = sub_seed.get("initial_grid") or s.get("initial_grid") or d.get("initial_grid")
            ig = np.array(ig_raw, dtype=np.int32)
            if ig.shape != (40,40) or gt.shape != (40,40,6): continue
            ss, st, pa = compute_hidden_params(ig, gt)
            sett_stats = sub_seed.get("settlement_stats")
            samples.append({"grid": ig, "gt": gt, "ss": ss, "st": st, "pa": pa,
                            "settlement_stats": sett_stats, "round": rn, "seed": sid})

    return samples


def run_loo_cv(train_and_predict_fn):
    """Leave-one-round-out CV. train_and_predict_fn(train_samples, test_samples) -> list of predictions."""
    samples = load_all_samples()
    rounds = {}
    for s in samples:
        rounds.setdefault(s["round"], []).append(s)
    round_nums = sorted(rounds.keys())

    print(f"LOO CV on {len(round_nums)} rounds, {len(samples)} total samples")
    all_scores = []
    t0 = time.time()

    for fold_i, test_rn in enumerate(round_nums):
        train = [s for rn in round_nums if rn != test_rn for s in rounds[rn]]
        test = rounds[test_rn]

        predictions = train_and_predict_fn(train, test)

        seed_scores = []
        for pred, s in zip(predictions, test):
            seed_scores.append(score_prediction(pred, s["gt"]))

        mean = np.mean(seed_scores)
        all_scores.append(mean)
        elapsed = time.time() - t0
        eta = elapsed / (fold_i + 1) * (len(round_nums) - fold_i - 1)
        print(f"  R{test_rn:2d}: {mean:.1f}  seeds=[{' '.join(f'{s:.1f}' for s in seed_scores)}]  [ETA {eta:.0f}s]")

    overall = np.mean(all_scores)
    print(f"\n  LOO Mean: {overall:.1f} (total {time.time()-t0:.0f}s)")
    return overall
