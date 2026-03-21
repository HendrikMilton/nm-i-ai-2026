"""
Auto-submit loop for Challenge 3: Astar Island.

Flow per iteration:
1. Fetch rounds, check for new active round
2. Run queries (9 tiled viewports × 5 seeds = 45 queries)
3. Estimate hidden params from observations
4. Predict with LightGBM model
5. Submit predictions
6. If previous round completed: retrain model
   a. Holdout eval (train on all except latest, compare with actual score)
   b. Full retrain (train on all rounds with GT)
7. Wait 1 hour, repeat

Usage:
    python3 auto_loop.py                # run loop
    python3 auto_loop.py --once         # single iteration, no loop
    python3 auto_loop.py --interval 1800  # 30 min interval
"""

import sys
import os
import json
import time
import math
import logging
import numpy as np
from pathlib import Path
from datetime import datetime

# Set API token before any imports
TOKEN = "REDACTED_TOKEN"
os.environ["AINM_TOKEN"] = TOKEN

sys.path.insert(0, str(Path(__file__).parent / "../../elias"))
from shared.utils import get_active_round, get_round, simulate, submit, get_budget

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
LOG_DIR = SCRIPT_DIR / "logs" / "auto_loop"
TRAIN_LOG_DIR = SCRIPT_DIR / "logs" / "training"
EVAL_LOG_DIR = SCRIPT_DIR / "logs" / "eval"
ROUND_DATA_DIR = SCRIPT_DIR / "round_data"
CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints"

GRID_SIZE = 40
VIEWPORT = 15
N_SEEDS = 5
TERRAIN_TO_CLASS = {0: 0, 10: 0, 11: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}


# ============================================================
# State tracking
# ============================================================
def load_state():
    state_file = SCRIPT_DIR / "auto_state.json"
    if state_file.exists():
        with open(state_file) as f:
            return json.load(f)
    return {"last_submitted_round": None, "last_trained_round": None}


def save_state(state):
    with open(SCRIPT_DIR / "auto_state.json", "w") as f:
        json.dump(state, f, indent=2)


# ============================================================
# Query logic (same tiling as Elias)
# ============================================================
def build_tiling():
    def tile_positions(map_size, vp_size):
        n_tiles = -(-map_size // vp_size)
        if n_tiles <= 1: return [0]
        step = (map_size - vp_size) / (n_tiles - 1)
        return sorted(set(int(i * step + 0.5) for i in range(n_tiles)))
    xs = [x + 1 for x in tile_positions(GRID_SIZE - 2, VIEWPORT)]
    ys = [y + 1 for y in tile_positions(GRID_SIZE - 2, VIEWPORT)]
    return [(x, y) for y in ys for x in xs]


def run_queries(round_id, seed_idx, viewports):
    obs_counts = np.zeros((GRID_SIZE, GRID_SIZE, 6), dtype=np.int32)
    n_obs = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.int32)
    query_grids = []
    all_settlements = []  # collect settlement stats from all queries

    for vp_x, vp_y in viewports:
        try:
            result = simulate(round_id, seed_idx, vp_x, vp_y, VIEWPORT, VIEWPORT)
            grid = result.get("grid") or result.get("terrain_grid")
            if grid is None: continue
            grid = np.array(grid)
            query_grids.append({"viewport": {"x": vp_x, "y": vp_y, "w": VIEWPORT, "h": VIEWPORT}, "grid": grid.tolist()})
            # Save settlement stats
            settlements = result.get("settlements", [])
            all_settlements.extend(settlements)
            for dr in range(min(VIEWPORT, grid.shape[0])):
                for dc in range(min(VIEWPORT, grid.shape[1])):
                    r, c = vp_y + dr, vp_x + dc
                    if 0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE:
                        cls = TERRAIN_TO_CLASS.get(int(grid[dr, dc]), 0)
                        obs_counts[r, c, cls] += 1
                        n_obs[r, c] += 1
            time.sleep(0.15)
        except Exception as e:
            log.warning(f"Query error seed={seed_idx} vp=({vp_x},{vp_y}): {e}")

    obs_probs = np.zeros((GRID_SIZE, GRID_SIZE, 6), dtype=np.float32)
    mask = n_obs > 0
    if mask.any():
        obs_probs[mask] = obs_counts[mask] / n_obs[mask, None]

    # Aggregate settlement stats (deduplicate by position)
    settlement_stats = aggregate_settlement_stats(all_settlements)

    return obs_probs, n_obs, query_grids, settlement_stats


def aggregate_settlement_stats(settlements):
    """Aggregate settlement stats from all queries into round-level features.
    Deduplicates by (x,y) position, keeps last seen values."""
    if not settlements:
        return None

    # Deduplicate: same settlement seen in multiple queries
    by_pos = {}
    for s in settlements:
        key = (s["x"], s["y"])
        by_pos[key] = s

    unique = list(by_pos.values())
    alive = [s for s in unique if s.get("alive", True)]

    if not alive:
        return {
            "mean_population": 0, "mean_food": 0, "mean_wealth": 0,
            "mean_defense": 0, "n_factions": 0, "port_ratio": 0,
            "alive_ratio": 0, "n_settlements": len(unique),
        }

    return {
        "mean_population": np.mean([s["population"] for s in alive]),
        "mean_food": np.mean([s["food"] for s in alive]),
        "mean_wealth": np.mean([s["wealth"] for s in alive]),
        "mean_defense": np.mean([s["defense"] for s in alive]),
        "n_factions": len(set(s["owner_id"] for s in alive)),
        "port_ratio": np.mean([1 if s.get("has_port") else 0 for s in alive]),
        "alive_ratio": len(alive) / max(len(unique), 1),
        "n_settlements": len(unique),
    }


# ============================================================
# Save round data (merge, never overwrite obs)
# ============================================================
def save_round_data(round_number, round_id, seed_grids, seed_obs):
    save_path = ROUND_DATA_DIR / f"round_{round_number:02d}_submit.json"

    existing = {}
    if save_path.exists():
        try:
            with open(save_path) as f:
                existing = json.load(f)
        except: pass

    save_data = {
        "round_id": round_id,
        "round_number": round_number,
        "timestamp": datetime.now().isoformat(),
        "seeds": {},
    }

    for seed_idx in range(N_SEEDS):
        existing_seed = existing.get("seeds", {}).get(str(seed_idx), {})
        seed_save = dict(existing_seed)
        seed_save["initial_grid"] = seed_grids[seed_idx].tolist()

        if seed_idx in seed_obs:
            obs_probs, n_obs, query_grids, settlement_stats = seed_obs[seed_idx]
            if obs_probs is not None and query_grids:
                seed_save["query_grids"] = query_grids
                seed_save["observed_probs"] = obs_probs.tolist()
                seed_save["n_observations"] = n_obs.tolist()
            if settlement_stats is not None:
                seed_save["settlement_stats"] = settlement_stats

        save_data["seeds"][str(seed_idx)] = seed_save

    with open(save_path, "w") as f:
        json.dump(save_data, f)
    log.info(f"Saved to {save_path}")


# ============================================================
# Fetch latest round data (for retraining)
# ============================================================
def fetch_round_data():
    """Run fetch_rounds.ts to update round_data with GT from completed rounds."""
    import subprocess
    try:
        result = subprocess.run(
            ["npx", "tsx", str(SCRIPT_DIR / "fetch_rounds.ts")],
            cwd=str(SCRIPT_DIR), capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            log.info("Fetched latest round data")
        else:
            log.warning(f"fetch_rounds failed: {result.stderr[:200]}")
    except Exception as e:
        log.warning(f"fetch_rounds error: {e}")


# ============================================================
# Retrain model
# ============================================================
def retrain_model(exclude_round=None):
    """Retrain LightGBM model on all available data."""
    import solve
    # Force reimport to pick up any code changes
    import importlib
    importlib.reload(solve)

    samples = solve.load_v2_data(exclude_rounds=[exclude_round] if exclude_round else None)
    if not samples:
        log.error("No training data!")
        return None

    X, Y = solve.build_training_arrays(samples)
    log.info(f"Training: {len(samples)} samples, X={X.shape}")
    models = solve.train_models(X, Y)
    return models


def holdout_eval(holdout_round):
    """Train on all except holdout_round, eval on it. Writes detailed eval log."""
    EVAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    eval_log_path = EVAL_LOG_DIR / f"holdout_R{holdout_round:02d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    log.info(f"Holdout eval: excluding R{holdout_round}")
    lines = [f"=== Holdout Eval: R{holdout_round} ===", f"Timestamp: {datetime.now().isoformat()}", ""]

    models = retrain_model(exclude_round=holdout_round)
    if models is None:
        return

    import solve

    # Load holdout round
    rd_path = ROUND_DATA_DIR / f"round_{holdout_round:02d}.json"
    if not rd_path.exists():
        log.warning(f"No round data for R{holdout_round}")
        return

    with open(rd_path) as f:
        rd = json.load(f)

    seeds = rd.get("seeds", [])
    if isinstance(seeds, dict): seeds = list(seeds.values())

    actual_score = rd.get("round_score")
    actual_seed_scores = rd.get("seed_scores", [])
    lines.append(f"Actual round score: {actual_score}")
    lines.append(f"Actual seed scores: {actual_seed_scores}")
    lines.append("")

    seed_scores_default = []
    seed_scores_obs = []

    for s in seeds:
        if not isinstance(s, dict): continue
        gt = s.get("ground_truth")
        if gt is None: continue
        gt = np.array(gt, dtype=np.float32)
        ig = np.array(s.get("initial_grid", rd.get("initial_grid")), dtype=np.int32)
        sid = s.get("seed_index", "?")

        # Approach A: default params
        pred_default = solve.predict_grid(models, ig)
        sc_default = solve.score_prediction(pred_default, gt)
        seed_scores_default.append(sc_default)

        # Approach B: obs-derived params (if available)
        obs_p = np.array(s["observed_probs"], dtype=np.float32) if s.get("observed_probs") else None
        n_obs_arr = np.array(s["n_observations"], dtype=np.float32) if s.get("n_observations") else None
        sett_stats = s.get("settlement_stats")

        if obs_p is not None:
            pred_obs = solve.predict_grid(models, ig, obs_probs=obs_p, n_obs=n_obs_arr, settlement_stats=sett_stats)
            sc_obs = solve.score_prediction(pred_obs, gt)
        else:
            sc_obs = sc_default
        seed_scores_obs.append(sc_obs)

        actual_s = actual_seed_scores[sid] if isinstance(actual_seed_scores, list) and sid < len(actual_seed_scores) else "?"
        lines.append(f"  Seed {sid}: default={sc_default:.1f}  obs={sc_obs:.1f}  actual={actual_s}")

    mean_default = np.mean(seed_scores_default) if seed_scores_default else 0
    mean_obs = np.mean(seed_scores_obs) if seed_scores_obs else 0
    lines.append("")
    lines.append(f"Mean: default={mean_default:.1f}  obs={mean_obs:.1f}  actual={actual_score}")
    lines.append(f"Delta vs actual: default={mean_default - (actual_score or 0):+.1f}  obs={mean_obs - (actual_score or 0):+.1f}")

    log.info(f"Holdout R{holdout_round}: default={mean_default:.1f}, obs={mean_obs:.1f}, actual={actual_score}")
    log.info(f"  seeds: [{' '.join(f'{s:.1f}' for s in seed_scores_default)}]")

    # Write eval log
    with open(eval_log_path, "w") as f:
        f.write("\n".join(lines))
    log.info(f"Eval log: {eval_log_path}")

    return models


def full_retrain():
    """Train on everything, save to checkpoints. Writes training log."""
    import solve
    TRAIN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    train_log_path = TRAIN_LOG_DIR / f"full_retrain_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    log.info("Full retrain on all data...")
    lines = [f"=== Full Retrain ===", f"Timestamp: {datetime.now().isoformat()}", ""]

    t0 = time.time()
    models = retrain_model()
    train_time = time.time() - t0

    if models:
        solve.save_models(models)
        solve._models = models

        # Log feature importances
        lines.append(f"Training time: {train_time:.1f}s")
        lines.append(f"Features: {len(solve.FEATURE_NAMES)}")
        lines.append("")
        for k, model in enumerate(models):
            imp = model.feature_importances_
            pairs = sorted(zip(solve.FEATURE_NAMES, imp), key=lambda x: -x[1])
            top = ", ".join(f"{n}={v:.0f}" for n, v in pairs[:8])
            lines.append(f"Class {k}: {top}")

        # Quick train-on-all eval
        lines.append("")
        lines.append("=== Train-on-all scores (sanity check) ===")
        samples = solve.load_v2_data()
        rounds = {}
        for s in samples:
            rounds.setdefault(s["round"], []).append(s)
        all_scores = []
        for rn in sorted(rounds):
            seed_scores = []
            for s in rounds[rn]:
                pred = solve.predict_grid(models, s["grid"], s["ss"], s["st"], s["pa"],
                                          settlement_stats=s.get("settlement_stats"))
                seed_scores.append(solve.score_prediction(pred, s["gt"]))
            mean = np.mean(seed_scores)
            all_scores.append(mean)
            lines.append(f"  R{rn:2d}: {mean:.1f}  seeds=[{' '.join(f'{s:.1f}' for s in seed_scores)}]")
        lines.append(f"\n  Train-on-all mean: {np.mean(all_scores):.1f}")

        log.info(f"Full retrain complete: {train_time:.1f}s, {len(solve.FEATURE_NAMES)} features")

        with open(train_log_path, "w") as f:
            f.write("\n".join(lines))
        log.info(f"Training log: {train_log_path}")


# ============================================================
# Submit round
# ============================================================
def submit_round(round_id, round_number, seed_grids, seed_obs):
    """Predict and submit for all seeds. Uses obs to estimate hidden params."""
    import solve
    solve._ensure_models()

    for seed_idx in range(N_SEEDS):
        grid = seed_grids[seed_idx]

        # Get obs data if available
        obs_probs, n_obs_arr, settlement_stats = None, None, None
        if seed_idx in seed_obs:
            obs_probs = seed_obs[seed_idx][0]
            n_obs_arr = seed_obs[seed_idx][1]
            settlement_stats = seed_obs[seed_idx][3] if len(seed_obs[seed_idx]) > 3 else None

        # predict_grid handles param estimation from obs or uses defaults
        pred = solve.predict_grid(solve._models, grid,
                                  obs_probs=obs_probs, n_obs=n_obs_arr,
                                  settlement_stats=settlement_stats)

        try:
            result = submit(round_id, seed_idx, pred.tolist())
            log.info(f"Seed {seed_idx}: SUBMITTED — {result.get('status', result)}")
        except Exception as e:
            log.error(f"Seed {seed_idx}: SUBMIT ERROR — {e}")


# ============================================================
# Main loop iteration
# ============================================================
def run_iteration(state):
    """Single iteration of the auto loop."""

    # 1. Find active round
    log.info("Checking for active round...")
    active = get_active_round()
    if active is None:
        log.info("No active round. Waiting.")
        return state

    round_id = active["id"]
    round_number = active.get("round_number", 0)
    log.info(f"Active round: R{round_number} ({round_id})")

    # 2. Check if already submitted
    if state.get("last_submitted_round") == round_number:
        log.info(f"Already submitted R{round_number}. Checking for completed rounds...")

        # Check if previous round completed (for retraining)
        prev_round = round_number - 1
        if prev_round > 0 and state.get("last_trained_round") != prev_round:
            log.info(f"Fetching latest data to check if R{prev_round} completed...")
            fetch_round_data()

            rd_path = ROUND_DATA_DIR / f"round_{prev_round:02d}.json"
            if rd_path.exists():
                with open(rd_path) as f:
                    rd = json.load(f)
                seeds = rd.get("seeds", [])
                if isinstance(seeds, dict): seeds = list(seeds.values())
                has_gt = any(s.get("ground_truth") is not None for s in seeds if isinstance(s, dict))

                if has_gt and rd.get("round_score") is not None:
                    log.info(f"R{prev_round} completed! Score: {rd.get('round_score')}")

                    # Holdout eval
                    holdout_eval(prev_round)

                    # Full retrain
                    full_retrain()

                    state["last_trained_round"] = prev_round
                    save_state(state)
        return state

    # 3. Fetch per-seed grids
    log.info("Fetching per-seed grids...")
    round_data = get_round(round_id)
    initial_states = round_data.get("initial_states", [])

    seed_grids = {}
    for i, st in enumerate(initial_states[:N_SEEDS]):
        grid = st.get("grid") or st.get("terrain")
        if grid is not None:
            seed_grids[i] = np.array(grid, dtype=np.int32)
    for i in range(N_SEEDS):
        if i not in seed_grids:
            fallback = round_data.get("initial_grid") or active.get("initial_grid")
            seed_grids[i] = np.array(fallback, dtype=np.int32) if fallback else np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.int32)

    log.info(f"Loaded {len(seed_grids)} per-seed grids")

    # 4. Run queries
    budget = get_budget()
    queries_remaining = budget.get("queries_max", 50) - budget.get("queries_used", 0)
    tiling = build_tiling()
    needed = len(tiling) * N_SEEDS

    if queries_remaining < needed:
        log.warning(f"Only {queries_remaining} queries remaining (need {needed})")
        tiling = tiling[:max(1, queries_remaining // N_SEEDS)]

    seed_obs = {}
    if queries_remaining > 0:
        for seed_idx in range(N_SEEDS):
            log.info(f"Querying seed {seed_idx} ({len(tiling)} viewports)...")
            obs_probs, n_obs, query_grids, settlement_stats = run_queries(round_id, seed_idx, tiling)
            seed_obs[seed_idx] = (obs_probs, n_obs, query_grids, settlement_stats)
            coverage = (n_obs > 0).sum()
            log.info(f"  Coverage: {coverage}/{GRID_SIZE*GRID_SIZE}")
            if settlement_stats:
                log.info(f"  Settlements: pop={settlement_stats['mean_population']:.2f} food={settlement_stats['mean_food']:.2f} factions={settlement_stats['n_factions']}")
    else:
        log.warning("No query budget remaining!")

    # 5. Save round data
    save_round_data(round_number, round_id, seed_grids, seed_obs)

    # 6. Submit predictions
    log.info("Submitting predictions...")
    submit_round(round_id, round_number, seed_grids, seed_obs)

    state["last_submitted_round"] = round_number
    save_state(state)

    # 7. Git commit
    try:
        import subprocess
        submit_file = ROUND_DATA_DIR / f"round_{round_number:02d}_submit.json"
        subprocess.run(["git", "add", str(submit_file)], cwd=str(SCRIPT_DIR))
        subprocess.run(["git", "commit", "-m", f"auto: submitted R{round_number}"], cwd=str(SCRIPT_DIR))
        subprocess.run(["git", "pull", "--no-rebase"], cwd=str(SCRIPT_DIR))
        subprocess.run(["git", "push"], cwd=str(SCRIPT_DIR))
    except Exception as e:
        log.warning(f"Git error: {e}")

    return state


# ============================================================
# Main
# ============================================================
def main():
    args = sys.argv[1:]
    once = "--once" in args
    interval = 3600  # default 1 hour
    for i, a in enumerate(args):
        if a == "--interval" and i + 1 < len(args):
            interval = int(args[i + 1])

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    TRAIN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(file_handler)

    log.info(f"Auto-loop started (interval={interval}s, once={once})")

    state = load_state()
    log.info(f"State: {state}")

    while True:
        try:
            state = run_iteration(state)
        except Exception as e:
            log.error(f"Iteration error: {e}", exc_info=True)

        if once:
            log.info("Single iteration complete (--once)")
            break

        log.info(f"Sleeping {interval}s...")
        remaining = interval
        while remaining > 300:
            time.sleep(300)
            remaining -= 300
            log.info(f"  [heartbeat] {remaining}s remaining")
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    main()
