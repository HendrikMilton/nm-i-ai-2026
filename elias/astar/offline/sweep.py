"""
Astar Island — Sweep runner for iterative improvement.

Runs backtest_full_pipeline with configurable overrides and saves each
iteration with a named ID for the frontend.

Usage:
  python offline/sweep.py --round 7 --iterations 10 --label strategy_v2
  python offline/sweep.py --round 7 --label strategy_v2 --start 11 --obs-weight 0.5
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.utils import get_rounds, get_round
from offline.simulator import DEFAULT_PARAMS
from offline.run_local import backtest_full_pipeline, load_custom_params


def run_sweep(round_num, iterations, label, start_iter=1, budget=50,
              obs_weight=None, sim_weight=None, prior_weight=None, n_sims=None):
    """Run multiple backtest iterations with overrides, logging each one."""

    rounds = get_rounds()
    completed = [r for r in rounds if r["status"] == "completed"]
    target = next((r for r in completed if r["round_number"] == round_num), None)
    if not target:
        print(f"Round {round_num} not found or not completed.")
        return

    round_id = target["id"]
    from run import N_SIMS as DEFAULT_N_SIMS
    eff_sims = n_sims if n_sims is not None else DEFAULT_N_SIMS

    print(f"Sweep: {label} on Round {round_num}")
    print(f"  Weights: obs={obs_weight} sim={sim_weight} prior={prior_weight} n_sims={eff_sims}")
    print(f"  Budget: {budget}, Iterations: {start_iter}-{start_iter + iterations - 1}")
    print()

    params = DEFAULT_PARAMS.copy()
    all_scores = []

    for it in range(start_iter, start_iter + iterations):
        iter_id = f"{label}.{it:02d}"
        print(f"--- {iter_id} ---")

        config = {
            "label": iter_id,
            "budget": budget,
            "mode": "sweep",
            "round_number": round_num,
            "obs_weight": obs_weight,
            "sim_weight": sim_weight,
            "prior_weight": prior_weight,
            "n_sims": eff_sims,
        }

        t0 = time.time()
        seed_results, round_score = backtest_full_pipeline(
            round_id, round_num, eff_sims, params, budget=budget,
            quiet=True, iteration_id=iter_id, config=config,
            obs_weight=obs_weight, sim_weight=sim_weight,
            prior_weight=prior_weight,
            rng_seed=round_num * 7919 + it * 131,
        )
        elapsed = time.time() - t0

        all_scores.append(round_score)
        seed_str = " ".join(
            f"s{s}={seed_results[s]['obs_score']:.1f}" for s in range(5))
        print(f"  Score: {round_score:.1f}  ({seed_str})  [{elapsed:.0f}s]")

    print(f"\n=== Summary ===")
    print(f"  Scores: {[f'{s:.1f}' for s in all_scores]}")
    print(f"  Mean: {sum(all_scores)/len(all_scores):.1f}")
    print(f"  Min: {min(all_scores):.1f}  Max: {max(all_scores):.1f}")


def main():
    parser = argparse.ArgumentParser(description="Astar sweep runner")
    parser.add_argument("--round", type=int, required=True, help="Round number")
    parser.add_argument("--iterations", type=int, default=10, help="Number of iterations")
    parser.add_argument("--label", type=str, default="strategy_v2", help="Label prefix")
    parser.add_argument("--start", type=int, default=1, help="Starting iteration number")
    parser.add_argument("--budget", type=int, default=50, help="Query budget")
    parser.add_argument("--obs-weight", type=float, default=None)
    parser.add_argument("--sim-weight", type=float, default=None)
    parser.add_argument("--prior-weight", type=float, default=None)
    parser.add_argument("--n-sims", type=int, default=None)
    args = parser.parse_args()

    run_sweep(
        round_num=args.round,
        iterations=args.iterations,
        label=args.label,
        start_iter=args.start,
        budget=args.budget,
        obs_weight=args.obs_weight,
        sim_weight=args.sim_weight,
        prior_weight=args.prior_weight,
        n_sims=args.n_sims,
    )


if __name__ == "__main__":
    main()
