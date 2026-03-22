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

# Set token BEFORE any imports that load shared.utils
TOKEN = "REDACTED_TOKEN"
os.environ["AINM_TOKEN"] = TOKEN

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
TOTAL_BUDGET = 50
N_SEEDS = 5
GRID_SIZE = 40
VIEWPORT = 15
TERRAIN_TO_CLASS = {0: 0, 10: 0, 11: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}


# ============================================================
# Viewport tiling (same as Elias's run.py)
# ============================================================
def build_tiling():
    """Build full-coverage tiling that skips the 1-cell ocean border.
    Returns 9 viewports that cover the 40x40 interior."""
    def tile_positions(map_size, vp_size):
        n_tiles = -(-map_size // vp_size)  # ceil division
        if n_tiles <= 1:
            return [0]
        step = (map_size - vp_size) / (n_tiles - 1)
        return sorted(set(int(i * step + 0.5) for i in range(n_tiles)))

    interior_w = GRID_SIZE - 2
    interior_h = GRID_SIZE - 2
    xs = [x + 1 for x in tile_positions(interior_w, VIEWPORT)]
    ys = [y + 1 for y in tile_positions(interior_h, VIEWPORT)]
    return [(x, y) for y in ys for x in xs]


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
            settlements = result.get("settlements", [])
            query_grids.append({
                "viewport": {"x": vp_x, "y": vp_y, "w": VIEWPORT, "h": VIEWPORT},
                "grid": grid.tolist(),
                "settlements": settlements,
            })

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
    queries_only = "--queries-only" in sys.argv

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
    budget_info = get_budget()
    queries_used = budget_info.get("queries_used", 0)
    queries_max = budget_info.get("queries_max", 50)
    queries_remaining = queries_max - queries_used
    print(f"  Round {round_number} ({round_id})")
    print(f"  Map: {active.get('map_width')}x{active.get('map_height')}")
    print(f"  Budget: {queries_used}/{queries_max} used, {queries_remaining} remaining")

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

    # Step 3: Run queries — Phase 1 (tiled coverage) + Phase 2 (remaining budget)
    tiling = build_tiling()  # 9 viewports
    phase1_total = len(tiling) * N_SEEDS  # 45
    phase2_total = max(0, queries_remaining - phase1_total)
    if queries_remaining < phase1_total:
        print(f"  WARNING: Only {queries_remaining} queries remaining, need {phase1_total} for Phase 1")
        print(f"  Reducing to {queries_remaining // N_SEEDS} viewports per seed")
        tiling = tiling[:queries_remaining // N_SEEDS]
        phase1_total = len(tiling) * N_SEEDS
        phase2_total = max(0, queries_remaining - phase1_total)
    print(f"\n[3] Query plan:")
    print(f"  Phase 1: {len(tiling)} viewports x {N_SEEDS} seeds = {phase1_total} queries")
    print(f"  Phase 2: {phase2_total} remaining queries (spread across seeds)")
    print(f"  Tiling: {tiling}")

    save_path = Path(f"round_data/round_{round_number:02d}_submit.json")
    save_path.parent.mkdir(parents=True, exist_ok=True)

    def _save_progress(seed_obs_dict):
        """Save query results after each seed — crash-safe."""
        existing = {}
        if save_path.exists():
            try:
                with open(save_path) as f:
                    existing = json.load(f)
            except Exception:
                pass
        data = {
            "round_id": round_id,
            "round_number": round_number,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "seeds": existing.get("seeds", {}),
        }
        for sid in range(N_SEEDS):
            if str(sid) not in data["seeds"]:
                data["seeds"][str(sid)] = {}
            data["seeds"][str(sid)]["initial_grid"] = seed_grids[sid].tolist()
            if sid in seed_obs_dict:
                obs_probs, n_obs, query_grids = seed_obs_dict[sid]
                if obs_probs is not None and query_grids:
                    data["seeds"][str(sid)]["query_grids"] = query_grids
                    data["seeds"][str(sid)]["observed_probs"] = obs_probs.tolist()
                    data["seeds"][str(sid)]["n_observations"] = n_obs.tolist()
        with open(save_path, "w") as f:
            json.dump(data, f)

    seed_obs = {}
    if no_query:
        print("  SKIPPING queries (--no-query)")
    else:
        # Phase 1: full tiling per seed
        for seed_idx in range(N_SEEDS):
            print(f"\n  --- Seed {seed_idx} Phase 1 ({len(tiling)} queries) ---")
            if dry_run:
                print(f"    DRY RUN: would query {len(tiling)} viewports")
                seed_obs[seed_idx] = (None, None, [])
            else:
                obs_probs, n_obs, query_grids = run_queries(round_id, seed_idx, tiling)
                seed_obs[seed_idx] = (obs_probs, n_obs, query_grids)
                _save_progress(seed_obs)
                print(f"    Saved progress after seed {seed_idx}")

        # Phase 2: spread remaining queries across seeds (round-robin)
        if phase2_total > 0 and not dry_run:
            print(f"\n  --- Phase 2: {phase2_total} extra queries ---")
            center_vp = tiling[len(tiling) // 2]
            for i in range(phase2_total):
                seed_idx = i % N_SEEDS
                print(f"    Extra query: seed={seed_idx} vp={center_vp}")
                extra_probs, extra_nobs, extra_grids = run_queries(round_id, seed_idx, [center_vp])
                obs_probs, n_obs, query_grids = seed_obs[seed_idx]
                if obs_probs is not None:
                    total = n_obs + extra_nobs
                    new_probs = np.zeros_like(obs_probs)
                    has_data = total > 0
                    new_probs[has_data] = (
                        obs_probs[has_data] * n_obs[has_data, None] +
                        extra_probs[has_data] * extra_nobs[has_data, None]
                    ) / total[has_data, None]
                    seed_obs[seed_idx] = (new_probs, total, query_grids + extra_grids)
            _save_progress(seed_obs)
            print(f"    Saved progress after phase 2")

    # Step 3.5: Final save (already saved incrementally, but do one more with settlement_stats)
    _save_progress(seed_obs)
    print(f"\n[3.5] Saved to {save_path}")

    if queries_only:
        print("\n[DONE] --queries-only: saved query results, skipping prediction and submission.")
        return

    # Step 4: Predict and submit
    print(f"\n[4] Predicting and submitting...")
    solve._ensure_models()

    for seed_idx in range(N_SEEDS):
        grid = seed_grids[seed_idx]

        # Extract settlement_stats from query responses
        settlement_stats = None
        if seed_idx in seed_obs:
            _, _, query_grids = seed_obs[seed_idx]
            if query_grids:
                # Aggregate settlement stats from all query responses
                all_settlements = []
                for qg in query_grids:
                    all_settlements.extend(qg.get("settlements", []))
                if all_settlements:
                    alive = [s for s in all_settlements if s.get("alive", True)]
                    if alive:
                        settlement_stats = {
                            "mean_population": np.mean([s["population"] for s in alive]),
                            "mean_food": np.mean([s["food"] for s in alive]),
                            "mean_wealth": np.mean([s["wealth"] for s in alive]),
                            "mean_defense": np.mean([s["defense"] for s in alive]),
                            "n_factions": len(set(s.get("owner_id", 0) for s in alive)),
                            "port_ratio": np.mean([1 if s.get("has_port") else 0 for s in alive]),
                            "alive_ratio": len(alive) / max(len(all_settlements), 1),
                            "n_settlements": len(all_settlements),
                        }
                        print(f"  Seed {seed_idx}: settlement_stats extracted (n_sett={settlement_stats['n_settlements']})")

        # Save settlement_stats to submit file
        if settlement_stats:
            try:
                existing = json.load(open(save_path))
                existing["seeds"][str(seed_idx)]["settlement_stats"] = settlement_stats
                with open(save_path, "w") as f:
                    json.dump(existing, f)
            except Exception:
                pass

        # Get observation data for Bayesian update
        obs_probs_arr, n_obs_arr = None, None
        if seed_idx in seed_obs:
            obs_probs_arr, n_obs_arr, _ = seed_obs[seed_idx]

        pred = solve.predict_grid(solve._models, grid, settlement_stats=settlement_stats,
                                   obs_probs=obs_probs_arr, n_obs=n_obs_arr)
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
