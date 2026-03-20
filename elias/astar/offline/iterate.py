"""Run 5 iterations across all rounds with different sim/prior weight configs."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import get_rounds
from offline.run_local import backtest_full_pipeline, load_custom_params

CONFIGS = [
    # iter, label, sim_weight, prior_weight, n_sims
    (1, "baseline_dist", 0.5, 4.0, 20),
    (2, "low_sim_dist", 0.1, 4.0, 20),
    (3, "no_sim_dist", 0.0, 4.0, 20),
    (4, "high_sim_dist", 1.0, 4.0, 20),
    (5, "med_sim_hi_prior", 0.3, 6.0, 20),
]


def main():
    params = load_custom_params()
    rounds = get_rounds()
    completed = [r for r in rounds if r["status"] == "completed"]
    completed.sort(key=lambda r: r.get("round_number", 0))

    print(f"Iterations: {len(CONFIGS)} configs x {len(completed)} rounds")
    print()

    results_summary = []
    total = len(CONFIGS) * len(completed)
    done = 0

    for cfg_idx, label, sim_w, prior_w, n_sims in CONFIGS:
        for rd in completed:
            round_id = rd["id"]
            round_num = rd["round_number"]
            iteration_id = f"R{round_num}_distv6_iter{cfg_idx}_{label}"

            config = {
                "label": label,
                "sim_weight": sim_w,
                "prior_weight": prior_w,
                "n_sims": n_sims,
                "iteration": cfg_idx,
                "feature": "distance_aware_priors",
            }

            done += 1
            print(f"[{done}/{total}] R{round_num} {label} (sw={sim_w}, pw={prior_w})")

            t0 = time.time()
            _, round_score = backtest_full_pipeline(
                round_id, round_num, n_sims, params,
                sim_weight=sim_w, prior_weight=prior_w,
                iteration_id=iteration_id, config=config,
                quiet=True,
            )
            elapsed = time.time() - t0

            results_summary.append({
                "iteration_id": iteration_id,
                "round": round_num,
                "label": label,
                "score": round_score,
                "elapsed": round(elapsed, 1),
            })
            print(f"  score={round_score:.1f}  ({elapsed:.0f}s)")

    # Print summary
    print("\n" + "=" * 90)
    print("SUMMARY — Score per config per round:")
    print("=" * 90)

    round_nums = sorted(set(r["round"] for r in results_summary))
    header = f"{'Config':<25}"
    for rn in round_nums:
        header += f" {'R'+str(rn):>6}"
    header += f" {'Avg':>6}"
    print(header)
    print("-" * 90)

    config_scores = {}
    for r in results_summary:
        label = r["label"]
        if label not in config_scores:
            config_scores[label] = {}
        config_scores[label][r["round"]] = r["score"]

    ranked = sorted(config_scores.items(),
                    key=lambda x: -sum(x[1].values()) / len(x[1]))
    for label, per_round in ranked:
        row = f"{label:<25}"
        scores = []
        for rn in round_nums:
            s = per_round.get(rn, 0)
            row += f" {s:>6.1f}"
            scores.append(s)
        avg = sum(scores) / len(scores)
        row += f" {avg:>6.1f}"
        print(row)


if __name__ == "__main__":
    main()
