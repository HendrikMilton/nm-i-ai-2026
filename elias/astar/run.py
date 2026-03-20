"""
Astar Island — simulator + prior prediction pipeline (v5).
Uses offline Monte Carlo simulator blended with contextual priors.
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
from offline.simulator import run_monte_carlo, DEFAULT_PARAMS

# --- Constants ---
DEFAULT_MAP_W = 40
DEFAULT_MAP_H = 40
N_CLASSES = 6
N_SEEDS = 5
VIEWPORT = 15
RATE_LIMIT_DELAY = 0.25  # stay under 5 req/s

# Blending parameters
# Observations are blended with distance-aware priors when enough samples exist.
# obs_weight is per-observation; total obs influence = obs_weight * sqrt(n_obs).
# Simulator is enabled with safety net: auto-disabled when it disagrees with observations.
SIM_WEIGHT = 0.3
PRIOR_WEIGHT = 4.0
OBS_WEIGHT = 0.5
N_SIMS = 100

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
# Three prior tables: average (all rounds), warm (R1-R7 excl R3), cold (R3 only).
# The appropriate table is selected based on observed expansion rate.
_PRIORS_DIR = os.path.dirname(__file__)

def _load_priors(filename):
    path = os.path.join(_PRIORS_DIR, filename)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

_CONTEXTUAL_PRIORS = _load_priors("contextual_priors.json")
_CONTEXTUAL_PRIORS_WARM = _load_priors("contextual_priors_warm.json")
_CONTEXTUAL_PRIORS_COLD = _load_priors("contextual_priors_cold.json")

# Expansion rate threshold for warm/cold classification.
# Below this → cold priors. Above → warm priors.
# R3 had expansion rate ~0.003. All other rounds >= 0.10.
WARM_COLD_THRESHOLD = 0.05


def classify_round_warmth(expansion_rate):
    """Classify a round as 'warm' or 'cold' based on observed expansion rate.

    Returns the appropriate contextual prior table.
    """
    if expansion_rate < WARM_COLD_THRESHOLD:
        return _CONTEXTUAL_PRIORS_COLD, "cold"
    else:
        return _CONTEXTUAL_PRIORS_WARM, "warm"


def get_contextual_prior(initial_grid, r, c, map_h, map_w, prior_table=None):
    """Get the best prior for a cell based on its terrain and neighborhood.

    If prior_table is provided, uses it instead of the default (all-rounds) table.
    """
    terrain = initial_grid[r][c]

    # Static terrain — no context needed
    if terrain == 10:
        return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    if terrain == 5:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]

    table = prior_table or _CONTEXTUAL_PRIORS

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
    if key in table:
        return list(table[key])

    # Relax: ignore coastal
    key = f"{terrain}_{n_forest}_0"
    if key in table:
        return list(table[key])

    # Relax: ignore forest count
    key = f"{terrain}_0_{1 if is_coastal else 0}"
    if key in table:
        return list(table[key])

    # Fallback to default table, then global prior
    if prior_table is not None and key not in prior_table:
        # Try the all-rounds table as fallback
        for fallback_key in [f"{terrain}_{n_forest}_{1 if is_coastal else 0}",
                             f"{terrain}_{n_forest}_0",
                             f"{terrain}_0_{1 if is_coastal else 0}"]:
            if fallback_key in _CONTEXTUAL_PRIORS:
                return list(_CONTEXTUAL_PRIORS[fallback_key])

    return list(TERRAIN_PRIORS.get(terrain, [1/N_CLASSES] * N_CLASSES))


# --- Distance-aware priors ---

def compute_settlement_distances(initial_grid, map_h, map_w):
    """Compute Chebyshev distance from each cell to nearest initial settlement.

    Returns: H x W grid of distances (999 if no settlements).
    """
    dist = [[999] * map_w for _ in range(map_h)]
    # BFS from all settlement cells simultaneously
    queue = []
    for r in range(map_h):
        for c in range(map_w):
            if initial_grid[r][c] in (1, 2):  # settlement or port
                dist[r][c] = 0
                queue.append((r, c))

    head = 0
    while head < len(queue):
        r, c = queue[head]
        head += 1
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if 0 <= nr < map_h and 0 <= nc < map_w:
                    if dist[nr][nc] > dist[r][c] + 1:
                        dist[nr][nc] = dist[r][c] + 1
                        queue.append((nr, nc))
    return dist


def estimate_expansion_rate(obs_counts, initial_grid, dist_map, map_h, map_w):
    """Estimate the round's expansion rate from observation counts.

    Looks at cells near settlements (dist 1-3) and counts how often
    they were observed as settlements vs other classes.

    Returns: expansion_rate (0.0 to 1.0), n_samples
    """
    settle_obs = 0
    total_obs = 0

    for r in range(map_h):
        for c in range(map_w):
            n_obs = sum(obs_counts[r][c])
            if n_obs == 0:
                continue
            terrain = initial_grid[r][c]
            # Only count non-settlement cells near settlements
            if terrain in (10, 5, 1, 2):  # skip ocean, mountain, existing settlements
                continue
            d = dist_map[r][c]
            if d < 1 or d > 3:  # only cells in expansion range
                continue
            total_obs += n_obs
            settle_obs += obs_counts[r][c][1]  # class 1 = settlement

    if total_obs == 0:
        return 0.10, 0  # default fallback

    return settle_obs / total_obs, total_obs


# Default distance decay multipliers — used as fallback when no observations
# are available. These are the average across R1-R7 ground truth.
_DIST_DECAY_DEFAULT = {
    0: 0.0,
    1: 1.20,
    2: 1.00,
    3: 0.70,
    4: 0.50,
    5: 0.30,
    6: 0.20,
    7: 0.10,
}


def estimate_dist_decay(initial_grid, obs_counts, dist_map, map_h, map_w):
    """Estimate per-distance settlement rate directly from observations.

    Returns: dict of {distance: settlement_rate} and the base_rate (avg of d1-3).
    The rates are absolute (not multipliers) — settlement probability at each distance.
    """
    dist_settle = {}  # dist -> (settle_count, total_count)
    for r in range(map_h):
        for c in range(map_w):
            n_obs = sum(obs_counts[r][c])
            if n_obs == 0:
                continue
            terrain = initial_grid[r][c]
            if terrain in (10, 5, 1, 2):  # skip ocean, mountain, existing settlements
                continue
            d = dist_map[r][c]
            if d < 1 or d > 7:
                continue
            if d not in dist_settle:
                dist_settle[d] = [0, 0]
            dist_settle[d][0] += obs_counts[r][c][1]  # settlement class
            dist_settle[d][1] += n_obs

    # Compute per-distance rates
    rates = {}
    for d in range(1, 8):
        if d in dist_settle and dist_settle[d][1] >= 5:
            rates[d] = dist_settle[d][0] / dist_settle[d][1]
        else:
            rates[d] = None  # not enough data

    # Base rate = average of d1-3
    d13_settle = sum(dist_settle.get(d, [0, 0])[0] for d in [1, 2, 3])
    d13_total = sum(dist_settle.get(d, [0, 0])[1] for d in [1, 2, 3])
    base_rate = d13_settle / d13_total if d13_total > 0 else 0.10

    # Convert to multipliers relative to base_rate
    multipliers = {}
    for d in range(1, 8):
        if rates[d] is not None and base_rate > 0:
            multipliers[d] = rates[d] / base_rate
        else:
            multipliers[d] = _DIST_DECAY_DEFAULT.get(d, 0.0)

    return multipliers, base_rate


def estimate_port_ruin_ratios(seed_grids, seed_counts, map_h, map_w):
    """Estimate port/settle and ruin/settle ratios from observations.

    Returns: (port_ratio, ruin_ratio) — observed ratios to use instead of fixed defaults.
    """
    port_obs = 0
    ruin_obs = 0
    settle_obs = 0
    total_coastal = 0
    total_inland = 0

    for s in seed_grids:
        grid = seed_grids[s]
        counts = seed_counts.get(s)
        if counts is None:
            continue
        for r in range(map_h):
            for c in range(map_w):
                n_obs = sum(counts[r][c])
                if n_obs == 0:
                    continue
                terrain = grid[r][c]
                if terrain in (10, 5, 1, 2):
                    continue

                # Check coastal
                is_coastal = False
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < map_h and 0 <= nc < map_w and grid[nr][nc] == 10:
                            is_coastal = True
                            break
                    if is_coastal:
                        break

                settle_obs += counts[r][c][1]
                ruin_obs += counts[r][c][3]
                if is_coastal:
                    port_obs += counts[r][c][2]
                    total_coastal += n_obs
                total_inland += n_obs

    # Compute ratios with fallback defaults
    port_ratio = port_obs / max(settle_obs, 1) if settle_obs > 10 else 0.35
    ruin_ratio = ruin_obs / max(settle_obs, 1) if settle_obs > 10 else 0.15

    return port_ratio, ruin_ratio


def get_distance_aware_prior(initial_grid, r, c, map_h, map_w, dist_map, expansion_rate,
                              dist_multipliers=None, port_ratio=0.75, ruin_ratio=0.10,
                              prior_table=None):
    """Get prior adjusted for distance to nearest settlement and round's expansion rate.

    Directly sets settlement+port probability to the distance-based target,
    then redistributes remaining probability among other classes proportionally
    to the base contextual prior.

    If dist_multipliers is provided (from estimate_dist_decay), uses the
    observation-derived per-distance multipliers instead of the fixed curve.
    If prior_table is provided, uses warm/cold-specific contextual priors.
    """
    terrain = initial_grid[r][c]

    # Static terrain — no adjustment
    if terrain == 10:
        return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    if terrain == 5:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]

    # Start from contextual prior (warm/cold-aware if table provided)
    prior = get_contextual_prior(initial_grid, r, c, map_h, map_w, prior_table=prior_table)

    dist = dist_map[r][c]

    # For existing settlements, don't adjust — they have their own dynamics
    if terrain in (1, 2):
        return prior

    # Compute target settlement probability based on distance and expansion rate
    mults = dist_multipliers or _DIST_DECAY_DEFAULT
    if dist <= 7:
        decay = mults.get(dist, _DIST_DECAY_DEFAULT.get(dist, 0.0))
    else:
        decay = max(0.02, 0.5 / max(dist, 1)) if dist <= 10 else 0.0
    target_settle = expansion_rate * decay

    # Port probability for coastal cells
    is_coastal = False
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            nr, nc = r + dr, c + dc
            if 0 <= nr < map_h and 0 <= nc < map_w and initial_grid[nr][nc] == 10:
                is_coastal = True
                break
        if is_coastal:
            break

    target_port = target_settle * port_ratio if is_coastal else 0.0

    # Ruin probability scales with expansion (more activity = more collapses)
    target_ruin = target_settle * ruin_ratio

    # Total probability allocated to settlement-related classes
    target_dynamic = target_settle + target_port + target_ruin

    # Remaining probability goes to the "static" classes (empty, forest, mountain)
    # distributed proportionally to the base prior
    remaining = max(0.01, 1.0 - target_dynamic)
    static_classes = [0, 4, 5]  # empty, forest, mountain
    base_static = sum(prior[k] for k in static_classes)

    adjusted = [0.0] * 6
    adjusted[1] = target_settle
    adjusted[2] = target_port
    adjusted[3] = target_ruin

    if base_static > 0:
        for k in static_classes:
            adjusted[k] = remaining * (prior[k] / base_static)
    else:
        adjusted[0] = remaining  # fallback: all to empty

    # Normalize (should already sum to ~1.0)
    total = sum(adjusted)
    if total > 0:
        adjusted = [v / total for v in adjusted]

    return adjusted


# Minimum observations before we trust data over priors
MIN_OBS_TO_BLEND = 1


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
    """Place fewest 15x15 viewports to cover all dynamic cells (greedy set cover).

    Viewport origins are constrained to avoid the ocean border (row/col 0 and
    map_h-1/map_w-1 are always ocean), so no queries are wasted on guaranteed-static cells.
    """
    dynamic_cells = set()
    for r in range(map_h):
        for c in range(map_w):
            if initial_grid[r][c] in (1, 2, 3):
                dynamic_cells.add((r, c))

    if not dynamic_cells:
        return []

    # Viewport placement bounds: skip the ocean border (1 cell on each edge)
    min_vx = 1
    min_vy = 1
    max_vx = max(min_vx, map_w - VIEWPORT - 1)  # so viewport ends before last ocean col
    max_vy = max(min_vy, map_h - VIEWPORT - 1)

    viewports = []
    uncovered = set(dynamic_cells)

    while uncovered:
        best_origin = None
        best_covered = set()

        # Candidate viewport origins that could cover uncovered cells
        candidate_xs = set()
        candidate_ys = set()
        for r, c in uncovered:
            for vx in range(max(min_vx, c - VIEWPORT + 1), min(max_vx + 1, c + 1)):
                candidate_xs.add(vx)
            for vy in range(max(min_vy, r - VIEWPORT + 1), min(max_vy + 1, r + 1)):
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
    """Blend observations with contextual priors using conservative adaptive weighting.

    prior_weight decays slowly as observations increase, keeping the prior
    dominant when few observations exist (where sampling noise is high):
      0 obs → pure prior
      1 obs → pw=20  (prior ~95%, obs ~5%)
      2 obs → pw=13  (prior ~87%, obs ~13%)
      5 obs → pw=8   (prior ~62%, obs ~38%)
      10 obs → pw=5.7 (prior ~36%, obs ~64%)
    """
    prediction = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]

    for r in range(map_h):
        for c in range(map_w):
            prior = get_contextual_prior(initial_grid, r, c, map_h, map_w)
            obs_total = sum(counts[r][c])

            if obs_total == 0:
                prediction[r][c] = prior
            else:
                prior_weight = 40.0 / (1.0 + obs_total / 2.0)
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


def extract_grid_and_settlements(round_data, seed_index):
    """Extract initial grid and settlement data for a specific seed."""
    initial_states = round_data.get("initial_states") or []
    if seed_index >= len(initial_states):
        raise ValueError(
            f"Seed index {seed_index} not found (only {len(initial_states)} seeds)")

    state = initial_states[seed_index]
    grid = state.get("grid") or state.get("terrain") or []
    settlements = state.get("settlements") or []

    if not settlements:
        for r in range(len(grid)):
            for c in range(len(grid[0])):
                if grid[r][c] in (1, 2):
                    settlements.append({
                        "x": c, "y": r,
                        "has_port": grid[r][c] == 2,
                        "alive": True,
                        "owner_id": len(settlements),
                    })

    return grid, settlements


def generate_prediction(grid, settlements, n_sims, params, base_seed, map_w, map_h,
                        sim_weight=SIM_WEIGHT, prior_weight=PRIOR_WEIGHT,
                        obs_counts=None, obs_weight=OBS_WEIGHT,
                        expansion_rate=None, dist_multipliers=None,
                        port_ratio=0.75, ruin_ratio=0.10,
                        prior_table=None):
    """Generate prediction by blending observations + simulator + distance-aware priors.

    Three signal sources, blended per-cell:
      - obs_counts: real API observations (weighted by obs_weight per observation)
      - sim_pred:   Monte Carlo simulator output (weighted by sim_weight)
      - prior:      distance-aware contextual priors (weighted by prior_weight)

    If expansion_rate is provided, priors are adjusted based on each cell's
    distance to the nearest settlement and the round's expansion aggressiveness.

    When sim_weight=0, skips the expensive Monte Carlo entirely.
    """
    # Skip Monte Carlo if sim has zero weight
    sim_pred = None
    if sim_weight > 0:
        sim_pred = run_monte_carlo(grid, settlements, n_sims=n_sims, params=params, base_seed=base_seed)

        # Simulator safety net: compare sim output to observations.
        # If the sim's most-likely class disagrees with observations on too many
        # cells, the sim's hidden params are wrong for this round — disable it.
        if sim_pred is not None and obs_counts is not None:
            agree = 0
            total = 0
            for r in range(map_h):
                for c in range(map_w):
                    n_obs = sum(obs_counts[r][c])
                    if n_obs < 1:
                        continue
                    # Observed most-common class
                    obs_argmax = max(range(N_CLASSES), key=lambda k: obs_counts[r][c][k])
                    # Sim's most-likely class
                    sim_argmax = max(range(N_CLASSES), key=lambda k: sim_pred[r][c][k])
                    total += 1
                    if obs_argmax == sim_argmax:
                        agree += 1
            if total > 0:
                agreement = agree / total
                # If sim agrees on fewer than 60% of observed cells, disable it
                if agreement < 0.60:
                    sim_pred = None
                    sim_weight = 0.0

    # Precompute distance map if we have an expansion rate
    dist_map = None
    if expansion_rate is not None:
        dist_map = compute_settlement_distances(grid, map_h, map_w)

    prediction = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
    for r in range(map_h):
        for c in range(map_w):
            if dist_map is not None:
                prior = get_distance_aware_prior(grid, r, c, map_h, map_w, dist_map, expansion_rate,
                                                 dist_multipliers=dist_multipliers,
                                                 port_ratio=port_ratio, ruin_ratio=ruin_ratio,
                                                 prior_table=prior_table)
            else:
                prior = get_contextual_prior(grid, r, c, map_h, map_w, prior_table=prior_table)

            n_obs = sum(obs_counts[r][c]) if obs_counts else 0
            # Only blend observations when we have enough samples
            use_obs = n_obs >= MIN_OBS_TO_BLEND and obs_weight > 0
            # Sub-linear scaling: sqrt(n_obs) prevents many observations from
            # completely drowning out the prior
            ow = obs_weight * (n_obs ** 0.5) if use_obs else 0

            if ow > 0 or sim_weight > 0:
                total_w = ow + sim_weight + prior_weight
                for k in range(N_CLASSES):
                    val = prior_weight * prior[k]
                    if ow > 0:
                        val += ow * (obs_counts[r][c][k] / n_obs)
                    if sim_pred is not None:
                        val += sim_weight * sim_pred[r][c][k]
                    prediction[r][c][k] = val / total_w
            else:
                prediction[r][c] = prior

    return floor_and_normalize(prediction)


def run_observation_phases(seed_grids, seed_dynamic_vps, total_budget, map_w, map_h,
                           observe_fn, print_fn=print):
    """Run Phase 1 (coverage) and Phase 2 (surprise-based) observation allocation.

    This is the shared query strategy used by both the live pipeline and offline backtest.

    Args:
        seed_grids: dict of seed_index → initial grid
        seed_dynamic_vps: dict of seed_index → list of (vx, vy) viewports
        total_budget: total queries available
        map_w, map_h: map dimensions
        observe_fn: callable(seed_index, viewports) → counts grid
            Live pipeline passes a wrapper around observe_seed().
            Backtest passes a wrapper around observe_seed_local().
        print_fn: print function (use lambda *a: None to suppress)

    Returns:
        seed_counts: dict of seed_index → H x W x N_CLASSES counts grid
        expansion_rate: estimated round expansion rate
    """
    initial_grid = seed_grids.get(0, [[11] * map_w for _ in range(map_h)])

    # Phase 1 — observe every seed once
    seed_counts = {}
    budget_spent = 0
    for seed_idx in range(N_SEEDS):
        dvps = seed_dynamic_vps[seed_idx]
        if not dvps or budget_spent >= total_budget:
            seed_counts[seed_idx] = [[[0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
            continue
        queries_to_use = dvps[:max(0, total_budget - budget_spent)]
        if not queries_to_use:
            seed_counts[seed_idx] = [[[0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
            continue
        print_fn(f"  Seed {seed_idx} Phase 1 ({len(queries_to_use)} queries)")
        seed_counts[seed_idx] = observe_fn(seed_idx, queries_to_use)
        budget_spent += len(queries_to_use)

    # Phase 2 — compute per-seed surprise and allocate remaining budget
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

        print_fn(f"  Phase 2: {remaining} queries, priority: {priority}")

        while remaining > 0:
            allocated = False
            for s in priority:
                dvps = seed_dynamic_vps[s]
                if not dvps:
                    continue
                can_add = min(len(dvps), remaining)
                extra_counts = observe_fn(s, dvps[:can_add])
                merge_counts(seed_counts[s], extra_counts, map_w, map_h)
                remaining -= can_add
                allocated = True
                if remaining <= 0:
                    break
            if not allocated:
                break

    # Estimate expansion rate and per-distance multipliers from observations
    # Aggregate observation counts across all seeds for per-distance estimation
    agg_dist_settle = {}  # dist -> [settle_count, total_count]
    expansion_rates = []
    for s in range(N_SEEDS):
        grid = seed_grids.get(s, initial_grid)
        dist_map = compute_settlement_distances(grid, map_h, map_w)
        rate, n_samples = estimate_expansion_rate(
            seed_counts[s], grid, dist_map, map_h, map_w)
        if n_samples > 0:
            expansion_rates.append((rate, n_samples))

        # Accumulate per-distance stats for decay estimation
        for r in range(map_h):
            for c in range(map_w):
                n_obs = sum(seed_counts[s][r][c])
                if n_obs == 0:
                    continue
                terrain = grid[r][c]
                if terrain in (10, 5, 1, 2):
                    continue
                d = dist_map[r][c]
                if d < 1 or d > 7:
                    continue
                if d not in agg_dist_settle:
                    agg_dist_settle[d] = [0, 0]
                agg_dist_settle[d][0] += seed_counts[s][r][c][1]
                agg_dist_settle[d][1] += n_obs

    if expansion_rates:
        total_samples = sum(n for _, n in expansion_rates)
        avg_expansion = sum(r * n for r, n in expansion_rates) / total_samples
    else:
        avg_expansion = 0.10

    # Compute per-distance multipliers from aggregated observations
    d13_settle = sum(agg_dist_settle.get(d, [0, 0])[0] for d in [1, 2, 3])
    d13_total = sum(agg_dist_settle.get(d, [0, 0])[1] for d in [1, 2, 3])
    base_rate = d13_settle / d13_total if d13_total > 0 else avg_expansion

    dist_multipliers = {}
    for d in range(1, 8):
        if d in agg_dist_settle and agg_dist_settle[d][1] >= 10 and base_rate > 0.001:
            dist_multipliers[d] = (agg_dist_settle[d][0] / agg_dist_settle[d][1]) / base_rate
        else:
            dist_multipliers[d] = _DIST_DECAY_DEFAULT.get(d, 0.0)

    # Classify round warmth and select appropriate prior table
    prior_table, warmth = classify_round_warmth(avg_expansion)

    print_fn(f"  Expansion rate: {avg_expansion:.3f} → {warmth} round")
    print_fn(f"  Dist multipliers: " + " ".join(f"d{d}={dist_multipliers.get(d, 0):.2f}" for d in range(1, 8)))

    return seed_counts, avg_expansion, dist_multipliers, prior_table


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

    # Parse per-seed grids
    initial_states = round_data.get("initial_states") or []
    seed_grids = {}
    for i, state in enumerate(initial_states):
        grid = state.get("grid") or state.get("terrain") or []
        if grid:
            seed_grids[i] = grid
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

    # 4. Plan viewports per seed
    seed_dynamic_vps = {}
    for s in range(N_SEEDS):
        grid = seed_grids.get(s, initial_grid)
        seed_dynamic_vps[s] = find_dynamic_viewports(grid, map_w, map_h)

    phase1_total = sum(len(seed_dynamic_vps[s]) for s in range(N_SEEDS))
    log_action(round_id, "plan_v5", {
        "strategy": "observations_plus_simulator_plus_priors",
        "total_budget": total_budget,
        "per_seed_dynamic_vps": {s: len(v) for s, v in seed_dynamic_vps.items()},
        "phase1_queries": phase1_total,
        "phase2_budget": max(0, total_budget - phase1_total),
        "n_sims": N_SIMS,
        "sim_weight": SIM_WEIGHT,
        "prior_weight": PRIOR_WEIGHT,
    })
    print(f"Per-seed viewports (set cover): {[len(seed_dynamic_vps[s]) for s in range(N_SEEDS)]}")
    print(f"Phase 1: {phase1_total} queries (1 pass all seeds)")
    print(f"Phase 2: {max(0, total_budget - phase1_total)} queries (extra on hardest)")

    # 5-7. Run observations + estimate expansion rate (shared logic)
    def live_observe(seed_idx, viewports):
        print(f"\n--- Seed {seed_idx} ({len(viewports)} queries) ---")
        log_action(round_id, "start_seed_observation", {
            "seed_index": seed_idx, "num_queries": len(viewports),
        })
        return observe_seed(round_id, seed_idx, viewports, map_w, map_h)

    seed_counts, avg_expansion, dist_multipliers, prior_table = run_observation_phases(
        seed_grids, seed_dynamic_vps, total_budget, map_w, map_h,
        observe_fn=live_observe,
    )

    log_action(round_id, "expansion_rate_estimate", {
        "pooled_rate": round(avg_expansion, 4),
        "dist_multipliers": {str(k): round(v, 3) for k, v in dist_multipliers.items()},
    })
    print(f"\nExpansion rate estimate: {avg_expansion:.3f}")

    # 8. Run simulator + blend with observations + distance-aware priors, then submit
    params = DEFAULT_PARAMS.copy()
    for seed_idx in range(N_SEEDS):
        print(f"\nBuilding prediction for seed {seed_idx}...")

        grid, settlements = extract_grid_and_settlements(round_data, seed_idx)

        t0 = time.time()
        prediction = generate_prediction(
            grid, settlements, N_SIMS, params,
            base_seed=seed_idx * 10000,
            map_w=map_w, map_h=map_h,
            obs_counts=seed_counts[seed_idx],
            expansion_rate=avg_expansion,
            dist_multipliers=dist_multipliers,
            prior_table=prior_table,
        )
        elapsed = time.time() - t0
        print(f"  Prediction built in {elapsed:.1f}s")

        log_action(round_id, "build_prediction", {
            "seed_index": seed_idx,
            "method": "obs_sim_prior_v5",
            "n_sims": N_SIMS,
            "elapsed_s": round(elapsed, 1),
            "prediction": prediction,
        })

        print(f"  Submitting seed {seed_idx}...")
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
