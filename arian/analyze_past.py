"""
Pull ground truth from completed rounds to understand where our simulator is wrong.

Usage:
    AINM_TOKEN=<token> python analyze_past.py [--round-id <uuid>]
"""
import argparse
import numpy as np
from api_client import get_my_rounds, get_analysis


def analyze_round(round_id: str, n_seeds: int = 5):
    """Pull ground truth for a completed round and analyze prediction errors."""
    print(f"Analyzing round {round_id}...")

    for seed_index in range(n_seeds):
        try:
            data = get_analysis(round_id, seed_index)
        except Exception as e:
            print(f"  Seed {seed_index}: FAILED ({e})")
            continue

        gt = np.array(data["ground_truth"])     # (H, W, 6)
        pred = np.array(data["prediction"])     # (H, W, 6)
        score = data.get("score")
        init_grid = np.array(data.get("initial_grid", []))

        print(f"\n  === Seed {seed_index} (score: {score}) ===")
        print(f"  Shape: {gt.shape}")

        # Per-class analysis: how does ground truth distribute?
        gt_argmax = gt.argmax(axis=2)  # (H, W)
        pred_argmax = pred.argmax(axis=2)

        class_names = ["Empty/Ocean/Plains", "Settlement", "Port", "Ruin", "Forest", "Mountain"]
        print(f"\n  Ground truth class distribution (argmax):")
        for c in range(6):
            gt_count = (gt_argmax == c).sum()
            pred_count = (pred_argmax == c).sum()
            print(f"    Class {c} ({class_names[c]:20s}): GT={gt_count:4d}  Pred={pred_count:4d}  diff={pred_count-gt_count:+4d}")

        # Entropy analysis: which cells are most uncertain in ground truth?
        eps = 1e-10
        gt_safe = np.maximum(gt, eps)
        entropy = -np.sum(gt_safe * np.log(gt_safe), axis=2)  # (H, W)
        print(f"\n  Ground truth entropy: mean={entropy.mean():.4f}  max={entropy.max():.4f}")
        print(f"  Static cells (entropy < 0.01): {(entropy < 0.01).sum()}")
        print(f"  Dynamic cells (entropy >= 0.1): {(entropy >= 0.1).sum()}")
        print(f"  Highly dynamic (entropy >= 0.5): {(entropy >= 0.5).sum()}")

        # Where are we most wrong? (highest KL per cell)
        pred_safe = np.maximum(pred, eps)
        kl = np.sum(gt_safe * np.log(gt_safe / pred_safe), axis=2)  # (H, W)

        # Focus on dynamic cells only
        dynamic_mask = entropy >= 0.1
        if dynamic_mask.sum() > 0:
            dynamic_kl = kl[dynamic_mask]
            print(f"\n  Dynamic cell KL: mean={dynamic_kl.mean():.4f}  median={np.median(dynamic_kl):.4f}  max={dynamic_kl.max():.4f}")

            # Worst cells
            flat_indices = np.argsort(kl.ravel())[-10:][::-1]
            print(f"\n  Top 10 worst cells (highest KL):")
            for idx in flat_indices:
                y, x = divmod(idx, kl.shape[1])
                print(f"    ({x:2d},{y:2d}): KL={kl[y,x]:.4f} entropy={entropy[y,x]:.4f} "
                      f"GT={gt[y,x].round(2)} Pred={pred[y,x].round(2)}")

        # Ground truth confidence analysis
        gt_max_prob = gt.max(axis=2)
        dynamic_confidence = gt_max_prob[dynamic_mask] if dynamic_mask.sum() > 0 else np.array([])
        if len(dynamic_confidence) > 0:
            print(f"\n  Dynamic cell GT confidence (max prob):")
            for threshold in [0.5, 0.7, 0.8, 0.9, 0.95]:
                pct = (dynamic_confidence >= threshold).mean() * 100
                print(f"    >= {threshold:.2f}: {pct:.1f}%")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-id", help="Specific round to analyze (otherwise analyzes all completed)")
    args = parser.parse_args()

    if args.round_id:
        analyze_round(args.round_id)
    else:
        print("Fetching all rounds...")
        rounds = get_my_rounds()
        completed = [r for r in rounds if r["status"] in ("completed", "scoring")]
        print(f"Found {len(completed)} completed rounds\n")

        for r in completed:
            rid = r["id"]
            rnum = r.get("round_number", "?")
            rscore = r.get("round_score", "?")
            seeds_count = r.get("seeds_count", 5)
            print(f"=== Round {rnum} (score: {rscore}) ===")
            analyze_round(rid, n_seeds=seeds_count)
            print()


if __name__ == "__main__":
    main()
