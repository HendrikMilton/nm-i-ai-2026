"""
Parameter sweep — run 50 iterations across completed rounds to find optimal settings.
10 iterations per round, 5 rounds = 50 total.

Each iteration varies:
  - sim_weight: how much to trust the simulator
  - prior_weight: how much to trust learned priors
  - n_sims: number of Monte Carlo simulations

Results are saved to logs/offline/ with unique iteration IDs visible in the dashboard.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import get_rounds
from offline.run_local import backtest_round, load_custom_params

CONFIGS = [
    # iter, label, sim_weight, prior_weight, n_sims
    (1,  "prior_only",        0.0,  1.0,  10),
    (2,  "sw0.1_pw4",         0.1,  4.0,  100),
    (3,  "sw0.25_pw4",        0.25, 4.0,  100),
    (4,  "sw0.5_pw4",         0.5,  4.0,  100),
    (5,  "sw1_pw4",           1.0,  4.0,  100),
    (6,  "sw0.5_pw2",         0.5,  2.0,  100),
    (7,  "sw0.5_pw6",         0.5,  6.0,  100),
    (8,  "sw0.5_pw8",         0.5,  8.0,  100),
    (9,  "sw0.25_pw6",        0.25, 6.0,  100),
    (10, "sw0.1_pw8",         0.1,  8.0,  100),
]


def main():
    params = load_custom_params()
    rounds = get_rounds()
    completed = [r for r in rounds if r["status"] == "completed"]
    completed.sort(key=lambda r: r.get("round_number", 0))

    print(f"Sweep: {len(CONFIGS)} configs × {len(completed)} rounds = {len(CONFIGS) * len(completed)} iterations")
    print(f"Rounds: {[r['round_number'] for r in completed]}")
    print()

    results_summary = []
    total = len(CONFIGS) * len(completed)
    done = 0

    for cfg_idx, label, sim_w, prior_w, n_sims in CONFIGS:
        for rd in completed:
            round_id = rd["id"]
            round_num = rd["round_number"]
            iteration_id = f"R{round_num}_iter{cfg_idx}_{label}"

            config = {
                "label": label,
                "sim_weight": sim_w,
                "prior_weight": prior_w,
                "n_sims": n_sims,
                "iteration": cfg_idx,
            }

            done += 1
            print(f"[{done}/{total}] R{round_num} {label} (sw={sim_w}, pw={prior_w}, sims={n_sims})")

            t0 = time.time()
            _, round_score = backtest_round(
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

    # Print summary table
    print("\n" + "=" * 80)
    print("SUMMARY — Average score across all rounds per config:")
    print("=" * 80)

    config_scores = {}
    for r in results_summary:
        label = r["label"]
        if label not in config_scores:
            config_scores[label] = []
        config_scores[label].append(r["score"])

    ranked = sorted(config_scores.items(), key=lambda x: -sum(x[1])/len(x[1]))
    print(f"{'Config':<20} {'Avg':>6} {'R1':>6} {'R2':>6} {'R3':>6} {'R4':>6} {'R5':>6}")
    print("-" * 80)
    for label, scores in ranked:
        avg = sum(scores) / len(scores)
        per_round = {r["round"]: r["score"] for r in results_summary if r["label"] == label}
        row = f"{label:<20} {avg:>6.1f}"
        for rn in sorted(per_round.keys()):
            row += f" {per_round[rn]:>6.1f}"
        print(row)


if __name__ == "__main__":
    main()
