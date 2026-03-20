"""
Astar Island — basic observation + prediction pipeline (v1).
See STRATEGY.md for the full approach.
"""

import json
import os
import time
from datetime import datetime, timezone

from utils import (
    get_active_round,
    get_round,
    get_budget,
    simulate,
    submit,
    floor_and_normalize,
)

# --- Constants ---
DEFAULT_MAP_W = 40
DEFAULT_MAP_H = 40
N_CLASSES = 6
N_SEEDS = 5
VIEWPORT = 15
RATE_LIMIT_DELAY = 0.25  # stay under 5 req/s

# Terrain code → prediction class mapping
TERRAIN_TO_CLASS = {
    0: 0,   # Empty → Empty
    10: 0,  # Ocean → Empty
    11: 0,  # Plains → Empty
    1: 1,   # Settlement
    2: 2,   # Port
    3: 3,   # Ruin
    4: 4,   # Forest
    5: 5,   # Mountain
}


# --- Logging ---
# Logs are split: one index file (logs/index.json) listing round IDs,
# and one file per round (logs/rounds/<round_id>.json) with all data.

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
INDEX_FILE = os.path.join(LOG_DIR, "index.json")


def _load_index():
    """Load the round index, or create empty."""
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE) as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {"rounds": []}


def _save_index(index):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f, indent=2)


def _round_file(round_id):
    return os.path.join(LOG_DIR, "rounds", f"{round_id}.json")


def _load_round(round_id):
    path = _round_file(round_id)
    if os.path.exists(path):
        with open(path) as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return None


def _save_round(round_id, round_data):
    path = _round_file(round_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(round_data, f, indent=2)


def _ensure_round(round_id, map_width=DEFAULT_MAP_W, map_height=DEFAULT_MAP_H):
    """Ensure a round entry exists on disk and in the index."""
    index = _load_index()
    if round_id not in [r["id"] for r in index["rounds"]]:
        index["rounds"].append({
            "id": round_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        _save_index(index)

    round_data = _load_round(round_id)
    if round_data is None:
        round_data = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "map_width": map_width,
            "map_height": map_height,
            "queries": [],
            "submissions": [],
            "actions": [],
        }
        _save_round(round_id, round_data)
    return round_data


def log_action(round_id, action, details=None):
    """Log a general action for a round."""
    round_data = _ensure_round(round_id)
    round_data["actions"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "details": details or {},
    })
    _save_round(round_id, round_data)


def log_query(round_id, seed_index, viewport, grid, budget_remaining):
    """Log a simulate query with its grid result."""
    round_data = _ensure_round(round_id)
    round_data["queries"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed_index": seed_index,
        "viewport": viewport,
        "grid": grid,
        "budget_remaining": budget_remaining,
    })
    _save_round(round_id, round_data)


def log_submission(round_id, seed_index, result):
    """Log a prediction submission."""
    round_data = _ensure_round(round_id)
    round_data["submissions"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed_index": seed_index,
        "result": result,
    })
    _save_round(round_id, round_data)


# --- Map helpers ---

def tile_positions(map_size, vp_size):
    """Generate viewport start positions to tile a map axis with minimal overlap."""
    positions = []
    pos = 0
    while pos < map_size:
        positions.append(pos)
        pos += vp_size
    if positions[-1] + vp_size > map_size:
        positions[-1] = max(0, map_size - vp_size)
    return list(dict.fromkeys(positions))


def build_tiling(map_w, map_h):
    """Return list of (x, y) viewport origins that cover the full map."""
    xs = tile_positions(map_w, VIEWPORT)
    ys = tile_positions(map_h, VIEWPORT)
    return [(x, y) for y in ys for x in xs]


def extract_map_dimensions(round_data):
    """Read map width/height from round data, falling back to defaults."""
    w = round_data.get("map_width") or round_data.get("width") or DEFAULT_MAP_W
    h = round_data.get("map_height") or round_data.get("height") or DEFAULT_MAP_H
    return int(w), int(h)


def parse_initial_state(round_data, map_w, map_h):
    """Extract static terrain from round initial states.

    Returns a map_h x map_w grid where each cell is either:
      - a known static class (4=forest, 5=mountain, 0=ocean/plains), or
      - None if the cell is dynamic (settlement/port area).
    """
    static_grid = [[None] * map_w for _ in range(map_h)]

    initial_states = round_data.get("initial_states") or []
    for state in initial_states:
        terrain = state.get("terrain") or state.get("grid") or []
        for r, row in enumerate(terrain):
            for c, val in enumerate(row):
                cls = TERRAIN_TO_CLASS.get(val, 0)
                if cls in (5, 4):
                    static_grid[r][c] = cls
                elif val == 10:
                    static_grid[r][c] = 0
    return static_grid


def observe_seed(round_id, seed_index, viewports, map_w, map_h):
    """Run simulate queries for one seed and return observation counts."""
    counts = [[[0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]

    for vx, vy in viewports:
        print(f"  simulate seed={seed_index} viewport=({vx},{vy})")
        try:
            result = simulate(round_id, seed_index, vx, vy, VIEWPORT, VIEWPORT)
        except Exception as e:
            print(f"    ERROR: {e}")
            log_action(round_id, "simulate_error", {
                "seed_index": seed_index,
                "viewport": {"x": vx, "y": vy, "w": VIEWPORT, "h": VIEWPORT},
                "error": str(e),
            })
            continue

        queries_used = result.get("queries_used")
        queries_max = result.get("queries_max")
        budget = queries_max - queries_used if queries_used is not None and queries_max is not None else None
        grid = result.get("grid") or result.get("terrain") or []
        settlements = result.get("settlements") or result.get("settlement_details") or []

        log_query(round_id, seed_index,
                  {"x": vx, "y": vy, "w": VIEWPORT, "h": VIEWPORT},
                  grid, budget)
        # Log the full simulate response (settlements, any extra fields)
        log_action(round_id, "simulate_response", {
            "seed_index": seed_index,
            "viewport": {"x": vx, "y": vy, "w": VIEWPORT, "h": VIEWPORT},
            "settlements": settlements,
            "response_keys": list(result.keys()),
        })

        for r, row in enumerate(grid):
            for c, val in enumerate(row):
                map_r = vy + r
                map_c = vx + c
                if 0 <= map_r < map_h and 0 <= map_c < map_w:
                    cls = TERRAIN_TO_CLASS.get(val, 0)
                    counts[map_r][map_c][cls] += 1

        print(f"    budget remaining: {budget}")
        time.sleep(RATE_LIMIT_DELAY)

    return counts


def counts_to_prediction(counts, static_grid, map_w, map_h):
    """Convert observation counts into a probability prediction tensor."""
    prediction = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]

    for r in range(map_h):
        for c in range(map_w):
            if static_grid[r][c] is not None:
                cls = static_grid[r][c]
                prediction[r][c] = [0.0] * N_CLASSES
                prediction[r][c][cls] = 1.0
                continue

            total = sum(counts[r][c])
            if total > 0:
                prediction[r][c] = [n / total for n in counts[r][c]]
            else:
                prediction[r][c] = [1.0 / N_CLASSES] * N_CLASSES

    return prediction


def merge_counts(a, b, map_w, map_h):
    """Element-wise add two count grids."""
    for r in range(map_h):
        for c in range(map_w):
            for k in range(N_CLASSES):
                a[r][c][k] += b[r][c][k]
    return a


def main():
    # 1. Find active round
    print("Fetching active round...")
    active = get_active_round()
    if not active:
        print("No active round found. Exiting.")
        log_action("no_round", "no_active_round_found")
        return

    round_id = active["id"]
    print(f"Active round: {round_id}")
    log_action(round_id, "fetch_active_round", {
        "round": active,
    })

    # 2. Get round details for initial state
    round_data = get_round(round_id)
    map_w, map_h = extract_map_dimensions(round_data)
    _ensure_round(round_id, map_w, map_h)
    log_action(round_id, "fetch_round_details", {
        "raw_response": round_data,
    })
    print(f"Map: {map_w}x{map_h}")

    static_grid = parse_initial_state(round_data, map_w, map_h)
    static_count = sum(
        1 for r in range(map_h) for c in range(map_w)
        if static_grid[r][c] is not None
    )
    log_action(round_id, "parse_initial_state", {
        "static_cells": static_count,
        "dynamic_cells": map_w * map_h - static_count,
    })
    print(f"Static cells: {static_count}, Dynamic: {map_w * map_h - static_count}")

    # 3. Check budget
    budget_info = get_budget()
    log_action(round_id, "check_budget", {
        "raw_response": budget_info,
    })
    print(f"Budget: {budget_info}")

    # 4. Plan queries
    full_tiling = build_tiling(map_w, map_h)
    queries_per_seed = len(full_tiling)
    total_planned = queries_per_seed * N_SEEDS
    log_action(round_id, "plan_tiling", {
        "viewports_per_seed": queries_per_seed,
        "total_planned": total_planned,
        "tiling": full_tiling,
    })
    print(f"Full tiling: {queries_per_seed} viewports/seed, {total_planned} total")

    # 5. Observe each seed with one full tiling pass
    seed_counts = {}
    for seed_idx in range(N_SEEDS):
        print(f"\n--- Seed {seed_idx} ---")
        log_action(round_id, "start_seed_observation",
                   {"seed_index": seed_idx})
        seed_counts[seed_idx] = observe_seed(
            round_id, seed_idx, full_tiling, map_w, map_h)

    # 6. Use remaining budget for extra observations on seed 0
    extra_viewports = [
        (map_w // 3, map_h // 3),
        (0, 0),
        (max(0, map_w - VIEWPORT), max(0, map_h - VIEWPORT)),
        (0, max(0, map_h - VIEWPORT)),
        (max(0, map_w - VIEWPORT), 0),
    ]
    print("\n--- Extra observations on seed 0 ---")
    budget_check = get_budget()
    log_action(round_id, "check_budget_for_extras", {
        "raw_response": budget_check,
    })
    used = budget_check.get("queries_used", 0)
    max_q = budget_check.get("queries_max", 50)
    remaining = int(max_q) - int(used)
    extra_to_run = extra_viewports[:remaining]
    log_action(round_id, "plan_extra_observations", {
        "budget_remaining": remaining,
        "extra_queries_planned": len(extra_to_run),
    })
    if extra_to_run:
        extra_counts = observe_seed(
            round_id, 0, extra_to_run, map_w, map_h)
        seed_counts[0] = merge_counts(seed_counts[0], extra_counts, map_w, map_h)

    # 7. Build predictions and submit for each seed
    for seed_idx in range(N_SEEDS):
        print(f"\nBuilding prediction for seed {seed_idx}...")
        prediction = counts_to_prediction(
            seed_counts[seed_idx], static_grid, map_w, map_h)
        prediction = floor_and_normalize(prediction)
        log_action(round_id, "build_prediction", {
            "seed_index": seed_idx,
            "prediction": prediction,
        })

        print(f"Submitting seed {seed_idx}...")
        try:
            result = submit(round_id, seed_idx, prediction)
            log_submission(round_id, seed_idx, result)
            print(f"  Submit result: {result}")
        except Exception as e:
            print(f"  Submit ERROR: {e}")
            log_action(round_id, "submit_error", {
                "seed_index": seed_idx,
                "error": str(e),
            })
        time.sleep(0.6)

    log_action(round_id, "run_complete",
               {"seeds_submitted": N_SEEDS})
    print("\nDone! All 5 seeds submitted.")


if __name__ == "__main__":
    main()
