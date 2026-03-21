"""
Submit predictions for the active round.

Flow:
1. Fetch active round + per-seed initial grids
2. Run queries (10 per seed, tiled viewports)
3. Aggregate observations
4. Predict with LightGBM model
5. Submit predictions

Usage:
    python3 submit_round.py                # full pipeline
    python3 submit_round.py --dry-run      # everything except actual submit
    python3 submit_round.py --no-query     # skip queries, use existing observations
"""

import sys
import os
import json
import time
import math
import numpy as np
from pathlib import Path

# Use Elias's API utils
sys.path.insert(0, str(Path(__file__).parent / "../../elias"))
from shared.utils import (
    get_active_round, get_round, simulate, submit,
    get_budget, get_my_rounds,
)

# Use our model
import solve

# ============================================================
# Config
# ============================================================
QUERIES_PER_SEED = 10
N_SEEDS = 5
GRID_SIZE = 40
VIEWPORT = 15
TERRAIN_TO_CLASS = {0: 0, 10: 0, 11: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}

# Token - same as in fetch_rounds.ts
TOKEN = "REDACTED_TOKEN"
os.environ["AINM_TOKEN"] = TOKEN


# ============================================================
# Viewport tiling
# ============================================================
def tile_viewports(map_size=GRID_SIZE, vp_size=VIEWPORT):
    """Generate viewport positions that tile the map with overlap."""
    positions = []
    step = vp_size - 1  # slight overlap
    for y in range(0, map_size, step):
        for x in range(0, map_size, step):
            # Clamp to map bounds
            x = min(x, map_size - vp_size)
            y = min(y, map_size - vp_size)
            positions.append((x, y))
    # Deduplicate
    return list(set(positions))


def select_viewports(n_queries, map_size=GRID_SIZE, vp_size=VIEWPORT):
    """Select n_queries viewports for good coverage."""
    all_vps = tile_viewports(map_size, vp_size)
    if n_queries >= len(all_vps):
        return all_vps[:n_queries]
    # Spread evenly
    step = max(1, len(all_vps) // n_queries)
    selected = all_vps[::step][:n_queries]
    return selected


# ============================================================
# Query and aggregate
# ============================================================
def run_queries(round_id, seed_index, viewports):
    """Run simulation queries and return observation data."""
    obs_counts = np.zeros((GRID_SIZE, GRID_SIZE, 6), dtype=np.int32)
    n_obs = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.int32)
    query_grids = []

    for i, (vp_x, vp_y) in enumerate(viewports):
        print(f"    Query {i+1}/{len(viewports)}: seed={seed_index} vp=({vp_x},{vp_y})")
        try:
            result = simulate(round_id, seed_index, vp_x, vp_y, VIEWPORT, VIEWPORT)
            grid = result.get("grid") or result.get("terrain_grid")
            if grid is None:
                print(f"    WARNING: No grid in response: {list(result.keys())}")
                continue

            grid = np.array(grid)
            query_grids.append({"viewport": {"x": vp_x, "y": vp_y, "w": VIEWPORT, "h": VIEWPORT}, "grid": grid.tolist()})

            for dr in range(min(VIEWPORT, grid.shape[0])):
                for dc in range(min(VIEWPORT, grid.shape[1])):
                    r, c = vp_y + dr, vp_x + dc
                    if 0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE:
                        code = int(grid[dr, dc])
                        cls = TERRAIN_TO_CLASS.get(code, 0)
                        obs_counts[r, c, cls] += 1
                        n_obs[r, c] += 1

            time.sleep(0.2)  # rate limit
        except Exception as e:
            print(f"    ERROR: {e}")

    obs_probs = np.zeros((GRID_SIZE, GRID_SIZE, 6), dtype=np.float32)
    mask = n_obs > 0
    if mask.any():
        obs_probs[mask] = obs_counts[mask] / n_obs[mask, None]

    coverage = mask.sum()
    print(f"    Coverage: {coverage}/{GRID_SIZE*GRID_SIZE} ({100*coverage/(GRID_SIZE*GRID_SIZE):.0f}%)")

    return obs_probs, n_obs, query_grids


# ============================================================
# Config estimation from observations
# ============================================================
def estimate_config(initial_grid, obs_probs, n_obs):
    """Estimate warmth and expansion_rate from observations."""
    grid = np.array(initial_grid)
    settle_mask = grid == 1
    observed_settle = settle_mask & (n_obs > 0)

    if observed_settle.sum() > 3:
        # Settlement survival rate from observations
        settle_survive = obs_probs[observed_settle, 1].mean()
        if settle_survive < 0.05:
            print(f"  Config estimate: COLD (settle_survive={settle_survive:.3f})")
            return False, 0.02
        else:
            exp_rate = max(0.05, min(0.4, settle_survive * 0.5))
            print(f"  Config estimate: WARM (settle_survive={settle_survive:.3f}, exp={exp_rate:.3f})")
            return True, exp_rate

    print("  Config estimate: DEFAULT WARM (insufficient observations)")
    return True, 0.15


# ============================================================
# Main pipeline
# ============================================================
def main():
    dry_run = "--dry-run" in sys.argv
    no_query = "--no-query" in sys.argv

    print("=" * 60)
    print("ASTAR ISLAND — SUBMIT PIPELINE")
    print("=" * 60)

    # Step 1: Find active round
    print("\n[1] Finding active round...")
    active = get_active_round()
    if active is None:
        print("  No active round found!")
        return
    round_id = active["id"]
    round_number = active.get("round_number", "?")
    print(f"  Round {round_number} ({round_id})")
    print(f"  Map: {active.get('map_width')}x{active.get('map_height')}")
    print(f"  Budget: {active.get('queries_max', 50)} queries")

    # Step 2: Fetch per-seed grids
    print("\n[2] Fetching round details (per-seed grids)...")
    round_data = get_round(round_id)
    initial_states = round_data.get("initial_states", [])
    if len(initial_states) < N_SEEDS:
        print(f"  WARNING: Only {len(initial_states)} initial states (expected {N_SEEDS})")
        # Fallback to single grid
        fallback_grid = round_data.get("initial_grid") or active.get("initial_grid")
        while len(initial_states) < N_SEEDS:
            initial_states.append({"grid": fallback_grid})

    seed_grids = {}
    for i, state in enumerate(initial_states[:N_SEEDS]):
        grid = state.get("grid") or state.get("terrain")
        if grid is not None:
            seed_grids[i] = np.array(grid, dtype=np.int32)
            print(f"  Seed {i}: grid loaded ({seed_grids[i].shape})")
        else:
            print(f"  Seed {i}: WARNING no grid, using seed 0")
            seed_grids[i] = seed_grids.get(0, np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.int32))

    # Step 3: Run queries
    viewports = select_viewports(QUERIES_PER_SEED)
    print(f"\n[3] Queries: {QUERIES_PER_SEED} per seed x {N_SEEDS} seeds = {QUERIES_PER_SEED * N_SEEDS} total")
    print(f"  Viewports: {viewports}")

    seed_obs = {}
    if no_query:
        print("  SKIPPING queries (--no-query)")
    else:
        for seed_idx in range(N_SEEDS):
            print(f"\n  --- Seed {seed_idx} ---")
            if dry_run:
                print(f"    DRY RUN: would query {len(viewports)} viewports")
                seed_obs[seed_idx] = (None, None, [])
            else:
                obs_probs, n_obs, query_grids = run_queries(round_id, seed_idx, viewports)
                seed_obs[seed_idx] = (obs_probs, n_obs, query_grids)

    # Step 4: Predict and submit
    print(f"\n[4] Predicting and submitting...")
    solve._ensure_models()

    for seed_idx in range(N_SEEDS):
        grid = seed_grids[seed_idx]
        obs_probs, n_obs = None, None

        if seed_idx in seed_obs:
            obs_probs, n_obs, _ = seed_obs[seed_idx]

        # Estimate config from observations
        if obs_probs is not None and n_obs is not None:
            is_warm, exp_rate = estimate_config(grid, obs_probs, n_obs)
        else:
            is_warm, exp_rate = True, 0.15

        # Predict
        pred = solve.predict_grid(solve._models, grid, is_warm, exp_rate, obs_probs, n_obs)
        print(f"  Seed {seed_idx}: pred shape={pred.shape}, sum check={pred.sum(axis=-1).mean():.4f}")

        # Submit
        if dry_run:
            print(f"  Seed {seed_idx}: DRY RUN — not submitting")
        else:
            try:
                result = submit(round_id, seed_idx, pred.tolist())
                print(f"  Seed {seed_idx}: SUBMITTED — {result}")
            except Exception as e:
                print(f"  Seed {seed_idx}: SUBMIT ERROR — {e}")

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
