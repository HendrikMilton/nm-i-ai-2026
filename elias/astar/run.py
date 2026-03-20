"""
Astar Island — observation + prediction pipeline (v2).
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

# Priors learned from Rounds 1-4 ground truth analysis (averaged across all seeds).
# Maps initial terrain code → expected class distribution [empty, settlement, port, ruin, forest, mountain]
TERRAIN_PRIORS = {
    10: [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],             # Ocean → 100% empty
    11: [0.8384, 0.1099, 0.009, 0.0102, 0.0325, 0.0], # Plains → 84% empty, 11% settlement
    5:  [0.0, 0.0, 0.0, 0.0, 0.0, 1.0],               # Mountain → 100% mountain
    4:  [0.0694, 0.1116, 0.0084, 0.0102, 0.8005, 0.0], # Forest → 80% forest, 11% settlement
    1:  [0.4794, 0.27, 0.0042, 0.0227, 0.2237, 0.0],  # Settlement → 48% empty, 27% settlement
    2:  [0.4911, 0.0757, 0.1821, 0.0214, 0.2296, 0.0], # Port → 49% empty, 18% port
    0:  [0.8384, 0.1099, 0.009, 0.0102, 0.0325, 0.0],  # Empty → like plains
    3:  [0.4794, 0.27, 0.0042, 0.0227, 0.2237, 0.0],  # Ruin → like settlement
}

# How many focus seeds to observe heavily
N_FOCUS_SEEDS = 2


# --- Logging ---
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
INDEX_FILE = os.path.join(LOG_DIR, "index.json")


def _load_index():
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
    round_data = _ensure_round(round_id)
    round_data["actions"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "details": details or {},
    })
    _save_round(round_id, round_data)


def log_query(round_id, seed_index, viewport, grid, budget_remaining):
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
    round_data = _ensure_round(round_id)
    round_data["submissions"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed_index": seed_index,
        "result": result,
    })
    _save_round(round_id, round_data)


# --- Map helpers ---

def tile_positions(map_size, vp_size):
    positions = []
    pos = 0
    while pos < map_size:
        positions.append(pos)
        pos += vp_size
    if positions[-1] + vp_size > map_size:
        positions[-1] = max(0, map_size - vp_size)
    return list(dict.fromkeys(positions))


def build_tiling(map_w, map_h):
    xs = tile_positions(map_w, VIEWPORT)
    ys = tile_positions(map_h, VIEWPORT)
    return [(x, y) for y in ys for x in xs]


def extract_map_dimensions(round_data):
    w = round_data.get("map_width") or round_data.get("width") or DEFAULT_MAP_W
    h = round_data.get("map_height") or round_data.get("height") or DEFAULT_MAP_H
    return int(w), int(h)


def parse_initial_grid(round_data, map_w, map_h):
    """Get the full initial terrain grid (raw terrain codes)."""
    initial_states = round_data.get("initial_states") or []
    for state in initial_states:
        grid = state.get("grid") or state.get("terrain") or []
        if grid and len(grid) == map_h and len(grid[0]) == map_w:
            return grid
    # Fallback: return None grid
    return [[11] * map_w for _ in range(map_h)]


def find_dynamic_viewports(initial_grid, map_w, map_h):
    """Find viewports that contain settlements, ports, or other dynamic cells."""
    dynamic_vps = []
    tiling = build_tiling(map_w, map_h)

    for vx, vy in tiling:
        has_dynamic = False
        for r in range(vy, min(vy + VIEWPORT, map_h)):
            for c in range(vx, min(vx + VIEWPORT, map_w)):
                if initial_grid[r][c] in (1, 2, 3):  # Settlement, Port, Ruin
                    has_dynamic = True
                    break
            if has_dynamic:
                break
        if has_dynamic:
            dynamic_vps.append((vx, vy))

    return dynamic_vps


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
        grid = result.get("grid") or []
        settlements = result.get("settlements") or []

        log_query(round_id, seed_index,
                  {"x": vx, "y": vy, "w": VIEWPORT, "h": VIEWPORT},
                  grid, budget)
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


def counts_to_prediction_v2(counts, initial_grid, map_w, map_h):
    """Build predictions using observations + learned priors.

    - Cells with multiple observations: blend empirical counts with prior
    - Cells with 1 observation: heavy prior weight
    - Cells with 0 observations: pure prior from initial terrain
    """
    prediction = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]

    for r in range(map_h):
        for c in range(map_w):
            init_terrain = initial_grid[r][c]
            prior = TERRAIN_PRIORS.get(init_terrain, [1/N_CLASSES] * N_CLASSES)
            obs_total = sum(counts[r][c])

            if obs_total == 0:
                # No observations — use pure prior
                prediction[r][c] = list(prior)
            else:
                # Blend observations with prior using pseudo-count
                # More observations → trust observations more
                # prior_weight acts like a pseudo-count of "prior observations"
                prior_weight = 2.0  # equivalent to 2 prior observations
                blended = [0.0] * N_CLASSES
                for k in range(N_CLASSES):
                    blended[k] = (counts[r][c][k] + prior_weight * prior[k]) / (obs_total + prior_weight)
                prediction[r][c] = blended

    return prediction


def merge_counts(a, b, map_w, map_h):
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
    log_action(round_id, "fetch_active_round", {"round": active})

    # 2. Get round details
    round_data = get_round(round_id)
    map_w, map_h = extract_map_dimensions(round_data)
    _ensure_round(round_id, map_w, map_h)
    log_action(round_id, "fetch_round_details", {"raw_response": round_data})
    print(f"Map: {map_w}x{map_h}")

    initial_grid = parse_initial_grid(round_data, map_w, map_h)
    dynamic_count = sum(
        1 for r in range(map_h) for c in range(map_w)
        if initial_grid[r][c] in (1, 2, 3)
    )
    log_action(round_id, "parse_initial_state", {
        "dynamic_cells": dynamic_count,
        "total_cells": map_w * map_h,
    })
    print(f"Dynamic cells (settlements/ports/ruins): {dynamic_count}")

    # 3. Check budget
    budget_info = get_budget()
    log_action(round_id, "check_budget", {"raw_response": budget_info})
    used = budget_info.get("queries_used", 0)
    max_q = budget_info.get("queries_max", 50)
    total_budget = int(max_q) - int(used)
    print(f"Budget: {total_budget} remaining ({used} used / {max_q} max)")

    # 4. Plan query allocation
    full_tiling = build_tiling(map_w, map_h)
    dynamic_vps = find_dynamic_viewports(initial_grid, map_w, map_h)

    # Focus seeds get: 1 full tiling + repeat observations of dynamic areas
    # Other seeds get: only dynamic area observations
    queries_for_tiling = len(full_tiling)  # 9
    queries_per_focus_seed = queries_for_tiling + len(dynamic_vps)  # 9 + dynamic repeats
    focus_total = queries_per_focus_seed * N_FOCUS_SEEDS
    remaining_for_others = total_budget - focus_total

    # If not enough budget, reduce repeat observations
    if focus_total > total_budget:
        # Cut repeats to fit
        repeats_per_focus = (total_budget // N_FOCUS_SEEDS) - queries_for_tiling
        repeats_per_focus = max(0, repeats_per_focus)
        dynamic_vps_trimmed = dynamic_vps[:repeats_per_focus]
        remaining_for_others = total_budget - (queries_for_tiling + len(dynamic_vps_trimmed)) * N_FOCUS_SEEDS
    else:
        dynamic_vps_trimmed = dynamic_vps

    # Distribute remaining budget to other seeds
    other_seeds = list(range(N_FOCUS_SEEDS, N_SEEDS))
    queries_per_other = max(0, remaining_for_others // len(other_seeds)) if other_seeds else 0
    other_vps = dynamic_vps[:queries_per_other]

    log_action(round_id, "plan_v2", {
        "total_budget": total_budget,
        "focus_seeds": list(range(N_FOCUS_SEEDS)),
        "queries_per_focus": queries_for_tiling + len(dynamic_vps_trimmed),
        "dynamic_viewports": len(dynamic_vps),
        "dynamic_viewports_trimmed": len(dynamic_vps_trimmed),
        "other_seeds": other_seeds,
        "queries_per_other": len(other_vps),
    })
    print(f"Focus seeds 0-{N_FOCUS_SEEDS-1}: {queries_for_tiling} tiling + {len(dynamic_vps_trimmed)} repeats each")
    print(f"Other seeds {N_FOCUS_SEEDS}-4: {len(other_vps)} queries each")
    print(f"Dynamic viewports found: {len(dynamic_vps)}")

    # 5. Observe focus seeds (full tiling + repeat dynamic areas)
    seed_counts = {}
    for seed_idx in range(N_FOCUS_SEEDS):
        print(f"\n--- Focus Seed {seed_idx} (tiling) ---")
        log_action(round_id, "start_seed_observation", {
            "seed_index": seed_idx, "phase": "tiling"})
        seed_counts[seed_idx] = observe_seed(
            round_id, seed_idx, full_tiling, map_w, map_h)

        if dynamic_vps_trimmed:
            print(f"--- Focus Seed {seed_idx} (repeats) ---")
            log_action(round_id, "start_seed_observation", {
                "seed_index": seed_idx, "phase": "repeats"})
            repeat_counts = observe_seed(
                round_id, seed_idx, dynamic_vps_trimmed, map_w, map_h)
            seed_counts[seed_idx] = merge_counts(
                seed_counts[seed_idx], repeat_counts, map_w, map_h)

    # 6. Observe other seeds (dynamic areas only)
    for seed_idx in other_seeds:
        if not other_vps:
            seed_counts[seed_idx] = [[[0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
            continue
        print(f"\n--- Other Seed {seed_idx} ---")
        log_action(round_id, "start_seed_observation", {
            "seed_index": seed_idx, "phase": "dynamic_only"})
        seed_counts[seed_idx] = observe_seed(
            round_id, seed_idx, other_vps, map_w, map_h)

    # 7. Build predictions and submit
    # For focus seeds: use their own observations + priors
    # For other seeds: average the focus seed counts as a proxy + priors
    avg_focus_counts = [[[0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
    for r in range(map_h):
        for c in range(map_w):
            for k in range(N_CLASSES):
                total = sum(seed_counts[s][r][c][k] for s in range(N_FOCUS_SEEDS))
                avg_focus_counts[r][c][k] = total

    for seed_idx in range(N_SEEDS):
        print(f"\nBuilding prediction for seed {seed_idx}...")

        if seed_idx < N_FOCUS_SEEDS:
            # Focus seed: use own observations
            counts = seed_counts[seed_idx]
        else:
            # Other seed: blend own sparse observations with focus seed average
            counts = [[[0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
            for r in range(map_h):
                for c in range(map_w):
                    own_total = sum(seed_counts[seed_idx][r][c])
                    if own_total > 0:
                        # Has own observation — use it
                        counts[r][c] = list(seed_counts[seed_idx][r][c])
                    else:
                        # No own observation — use focus seed average
                        counts[r][c] = list(avg_focus_counts[r][c])

        prediction = counts_to_prediction_v2(counts, initial_grid, map_w, map_h)
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

    log_action(round_id, "run_complete", {"seeds_submitted": N_SEEDS})
    print("\nDone! All 5 seeds submitted.")


if __name__ == "__main__":
    main()
