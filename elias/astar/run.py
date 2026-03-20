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

# Fallback priors (used when contextual lookup misses)
TERRAIN_PRIORS = {
    10: [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],             # Ocean → 100% empty
    11: [0.8384, 0.1099, 0.009, 0.0102, 0.0325, 0.0], # Plains
    5:  [0.0, 0.0, 0.0, 0.0, 0.0, 1.0],               # Mountain
    4:  [0.0694, 0.1116, 0.0084, 0.0102, 0.8005, 0.0], # Forest
    1:  [0.4794, 0.27, 0.0042, 0.0227, 0.2237, 0.0],  # Settlement
    2:  [0.4911, 0.0757, 0.1821, 0.0214, 0.2296, 0.0], # Port
    0:  [0.8384, 0.1099, 0.009, 0.0102, 0.0325, 0.0],  # Empty
    3:  [0.4794, 0.27, 0.0042, 0.0227, 0.2237, 0.0],  # Ruin
}

# Context-aware priors: (terrain, n_forest_neighbors, is_coastal) → [6] probs
# Learned from R1-R5 ground truth. Falls back to TERRAIN_PRIORS if no match.
_CONTEXTUAL_PRIORS_PATH = os.path.join(os.path.dirname(__file__), "contextual_priors.json")
_CONTEXTUAL_PRIORS = {}
if os.path.exists(_CONTEXTUAL_PRIORS_PATH):
    with open(_CONTEXTUAL_PRIORS_PATH) as _f:
        _CONTEXTUAL_PRIORS = json.load(_f)


def get_contextual_prior(initial_grid, r, c, map_h, map_w):
    """Get the best prior for a cell based on its terrain and neighborhood."""
    terrain = initial_grid[r][c]

    # Static terrain — no context needed
    if terrain == 10:
        return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    if terrain == 5:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]

    # Count neighbors
    n_forest = 0
    is_coastal = False
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < map_h and 0 <= nc < map_w:
                if initial_grid[nr][nc] == 4:
                    n_forest += 1
                if initial_grid[nr][nc] == 10:
                    is_coastal = True

    n_forest = min(n_forest, 4)  # capped in training data

    # Try exact match, then relax features
    key = f"{terrain}_{n_forest}_{1 if is_coastal else 0}"
    if key in _CONTEXTUAL_PRIORS:
        return list(_CONTEXTUAL_PRIORS[key])

    # Relax: ignore coastal
    key = f"{terrain}_{n_forest}_0"
    if key in _CONTEXTUAL_PRIORS:
        return list(_CONTEXTUAL_PRIORS[key])

    # Relax: ignore forest count
    key = f"{terrain}_0_{1 if is_coastal else 0}"
    if key in _CONTEXTUAL_PRIORS:
        return list(_CONTEXTUAL_PRIORS[key])

    # Fallback to global prior
    return list(TERRAIN_PRIORS.get(terrain, [1/N_CLASSES] * N_CLASSES))


# Minimum observations before we trust data over priors
MIN_OBS_TO_BLEND = 3


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
    """Place fewest 15x15 viewports to cover all dynamic cells (greedy set cover)."""
    dynamic_cells = set()
    for r in range(map_h):
        for c in range(map_w):
            if initial_grid[r][c] in (1, 2, 3):
                dynamic_cells.add((r, c))

    if not dynamic_cells:
        return []

    viewports = []
    uncovered = set(dynamic_cells)

    while uncovered:
        best_origin = None
        best_covered = set()

        # Candidate viewport origins that could cover uncovered cells
        candidate_xs = set()
        candidate_ys = set()
        for r, c in uncovered:
            for vx in range(max(0, c - VIEWPORT + 1), min(map_w - VIEWPORT + 1, c + 1)):
                candidate_xs.add(vx)
            for vy in range(max(0, r - VIEWPORT + 1), min(map_h - VIEWPORT + 1, r + 1)):
                candidate_ys.add(vy)

        for vx in candidate_xs:
            for vy in candidate_ys:
                covered = set()
                for r, c in uncovered:
                    if vy <= r < vy + VIEWPORT and vx <= c < vx + VIEWPORT:
                        covered.add((r, c))
                if len(covered) > len(best_covered):
                    best_covered = covered
                    best_origin = (vx, vy)

        if best_origin is None:
            break

        viewports.append(best_origin)
        uncovered -= best_covered

    return viewports


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


def counts_to_prediction_v4(counts, initial_grid, map_w, map_h):
    """Blend observations with contextual priors using adaptive weighting.

    prior_weight decays as observations increase:
      0 obs → pure prior
      1 obs → pw=8  (prior dominates, obs nudges)
      2 obs → pw=5
      3 obs → pw=3  (roughly 50/50)
      5 obs → pw=2
      10 obs → pw=1.5
    """
    prediction = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]

    for r in range(map_h):
        for c in range(map_w):
            prior = get_contextual_prior(initial_grid, r, c, map_h, map_w)
            obs_total = sum(counts[r][c])

            if obs_total == 0:
                prediction[r][c] = prior
            else:
                prior_weight = 12.0 / (1.0 + obs_total / 1.5)
                blended = [0.0] * N_CLASSES
                for k in range(N_CLASSES):
                    blended[k] = (counts[r][c][k] + prior_weight * prior[k]) / (obs_total + prior_weight)
                prediction[r][c] = blended

    return prediction

# Keep v3 as alias for backward compat with offline code
counts_to_prediction_v3 = counts_to_prediction_v4


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

    # Each seed has its own initial grid — parse all of them
    initial_states = round_data.get("initial_states") or []
    seed_grids = {}
    for i, state in enumerate(initial_states):
        grid = state.get("grid") or state.get("terrain") or []
        if grid:
            seed_grids[i] = grid

    # Use seed 0 grid as reference for query planning (settlement locations are similar)
    initial_grid = seed_grids.get(0, parse_initial_grid(round_data, map_w, map_h))
    dynamic_count = sum(
        1 for r in range(map_h) for c in range(map_w)
        if initial_grid[r][c] in (1, 2, 3)
    )
    log_action(round_id, "parse_initial_state", {
        "num_seeds": len(seed_grids),
        "dynamic_cells_seed0": dynamic_count,
        "total_cells": map_w * map_h,
    })
    print(f"Seeds with grids: {len(seed_grids)}")
    print(f"Dynamic cells (seed 0): {dynamic_count}")

    # 3. Check budget
    budget_info = get_budget()
    log_action(round_id, "check_budget", {"raw_response": budget_info})
    used = budget_info.get("queries_used", 0)
    max_q = budget_info.get("queries_max", 50)
    total_budget = int(max_q) - int(used)
    print(f"Budget: {total_budget} remaining ({used} used / {max_q} max)")

    # 4. Plan query allocation
    #
    # Strategy v3: spread queries evenly across all seeds.
    # Each seed has a DIFFERENT map — never share observations across seeds.
    # Maximize repeat observations on dynamic viewports to get >= MIN_OBS_TO_BLEND
    # per cell. Cells with fewer observations use pure priors.
    #
    # Each seed gets: dynamic viewports repeated as many times as budget allows.
    # We skip full tiling — priors handle static cells perfectly.

    # Per-seed viewport planning using greedy set cover
    seed_dynamic_vps = {}
    for s in range(N_SEEDS):
        grid = seed_grids.get(s, initial_grid)
        seed_dynamic_vps[s] = find_dynamic_viewports(grid, map_w, map_h)

    # Phase 1: every seed gets 1 pass through its viewports
    phase1_total = sum(len(seed_dynamic_vps[s]) for s in range(N_SEEDS))

    log_action(round_id, "plan_v4", {
        "total_budget": total_budget,
        "per_seed_dynamic_vps": {s: len(v) for s, v in seed_dynamic_vps.items()},
        "phase1_queries": phase1_total,
        "phase2_budget": max(0, total_budget - phase1_total),
        "strategy": "all_seeds_then_hardest",
    })
    print(f"Per-seed viewports (set cover): {[len(seed_dynamic_vps[s]) for s in range(N_SEEDS)]}")
    print(f"Phase 1: {phase1_total} queries (1 pass all seeds)")
    print(f"Phase 2: {max(0, total_budget - phase1_total)} queries (extra on hardest)")

    # 5. Phase 1 — observe every seed once
    seed_counts = {}
    budget_spent = 0
    for seed_idx in range(N_SEEDS):
        dvps = seed_dynamic_vps[seed_idx]
        if not dvps:
            seed_counts[seed_idx] = [[[0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
            print(f"\n--- Seed {seed_idx}: no dynamic cells ---")
            continue
        print(f"\n--- Seed {seed_idx} Phase 1 ({len(dvps)} queries) ---")
        log_action(round_id, "start_seed_observation", {
            "seed_index": seed_idx, "phase": "1_coverage", "num_queries": len(dvps),
        })
        seed_counts[seed_idx] = observe_seed(
            round_id, seed_idx, dvps, map_w, map_h)
        budget_spent += len(dvps)

    # 6. Phase 2 — compute per-seed surprise and allocate remaining budget
    remaining = total_budget - budget_spent
    if remaining > 0:
        seed_surprise = {}
        for s in range(N_SEEDS):
            grid = seed_grids.get(s, initial_grid)
            surprise = 0.0
            n_cells = 0
            for r in range(map_h):
                for c in range(map_w):
                    obs_total = sum(seed_counts[s][r][c])
                    if obs_total == 0:
                        continue
                    prior = get_contextual_prior(grid, r, c, map_h, map_w)
                    for k in range(N_CLASSES):
                        obs_frac = seed_counts[s][r][c][k] / obs_total
                        surprise += abs(obs_frac - prior[k])
                    n_cells += 1
            seed_surprise[s] = surprise / max(n_cells, 1)

        priority = sorted(range(N_SEEDS),
                          key=lambda s: seed_surprise.get(s, 0), reverse=True)

        log_action(round_id, "phase2_allocation", {
            "remaining_budget": remaining,
            "seed_surprise": {s: round(seed_surprise.get(s, 0), 4) for s in range(N_SEEDS)},
            "priority_order": priority,
        })
        print(f"\nPhase 2: {remaining} queries remaining")
        print(f"Surprise: {', '.join(f's{s}={seed_surprise.get(s,0):.3f}' for s in priority)}")

        while remaining > 0:
            allocated = False
            for s in priority:
                dvps = seed_dynamic_vps[s]
                if not dvps:
                    continue
                can_add = min(len(dvps), remaining)
                print(f"  Extra pass seed {s} ({can_add} queries)")
                log_action(round_id, "start_seed_observation", {
                    "seed_index": s, "phase": "2_extra", "num_queries": can_add,
                })
                extra_counts = observe_seed(
                    round_id, s, dvps[:can_add], map_w, map_h)
                merge_counts(seed_counts[s], extra_counts, map_w, map_h)
                remaining -= can_add
                allocated = True
                if remaining <= 0:
                    break
            if not allocated:
                break

    # 7. Build predictions and submit — each seed uses own observations + own grid
    for seed_idx in range(N_SEEDS):
        print(f"\nBuilding prediction for seed {seed_idx}...")
        seed_grid = seed_grids.get(seed_idx, initial_grid)

        prediction = counts_to_prediction_v4(
            seed_counts[seed_idx], seed_grid, map_w, map_h)
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
