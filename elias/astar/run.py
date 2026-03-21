"""
Astar Island v2 — Clean reimplementation with ABC integrated from the start.

Key improvements over v1:
  - Unified probability floors everywhere (single CLASS_FLOORS constant)
  - ABC parameter fitting is the primary prediction path, not an afterthought
  - Warm/cold-aware weight switching for simulator trust
  - Fixed forest boost double-compute bug from v1
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAP_W = 40
MAP_H = 40
VIEWPORT = 15
N_SEEDS = 5
N_CLASSES = 6

# Unified probability floors — used everywhere (prediction, MC, scoring).
# [empty, settlement, port, ruin, forest, mountain]
# Lower floors reduce probability mass stolen from likely outcomes.
# Validated: +0.3–0.4 points across all tested rounds vs previous [0.005, 0.005, 0.001, 0.002, 0.005, 0.001].
CLASS_FLOORS = [0.001, 0.001, 0.0002, 0.0005, 0.001, 0.0002]

# Terrain code → prediction class
TERRAIN_TO_CLASS = {
    0: 0, 10: 0, 11: 0,   # empty/ocean/plains → class 0
    1: 1, 2: 2, 3: 3, 4: 4, 5: 5,
}

# Warm/cold classification threshold (R3 ≈ 0.003, all others ≥ 0.10)
WARM_COLD_THRESHOLD = 0.05

# Blending weights
PRIOR_WEIGHT = 4.0
OBS_WEIGHT = 0.5
SIM_WEIGHT_WARM = 0.3
SIM_WEIGHT_COLD = 0.0
SIM_SAFETY_THRESHOLD = 0.72  # disable sim below this agreement rate

# ABC-based blending
ABC_PRIOR_WEIGHT = 0.80
ABC_MC_WEIGHT = 0.20
MC_EQUIV_SAMPLES = 18
MC_TOTAL_RUNS = 500

# Observation blending
MIN_OBS_TO_BLEND = 2
OBS_EXPONENT = 0.5  # n_obs ** exponent for observation weight scaling

# Default distance decay multipliers (average across R1-R7 ground truth)
DIST_DECAY_DEFAULT = {
    0: 0.0,  1: 1.20, 2: 1.00, 3: 0.70,
    4: 0.50, 5: 0.30, 6: 0.20, 7: 0.10,
}

# Separate decay curves for warm vs cold rounds
DIST_DECAY_WARM = {
    0: 0.0,  1: 1.30, 2: 1.10, 3: 0.80,
    4: 0.55, 5: 0.35, 6: 0.25, 7: 0.15,
}
DIST_DECAY_COLD = {
    0: 0.0,  1: 0.80, 2: 0.40, 3: 0.15,
    4: 0.05, 5: 0.02, 6: 0.01, 7: 0.005,
}

# Contextual priors (terrain, n_forest_neighbors, is_coastal → [6] probs)
_PRIORS_DIR = os.path.join(os.path.dirname(__file__), "..", "astar")

def _load_priors(filename):
    path = os.path.join(_PRIORS_DIR, filename)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

_CONTEXTUAL_PRIORS = _load_priors("contextual_priors.json")
_CONTEXTUAL_PRIORS_WARM = _load_priors("contextual_priors_warm.json")
_CONTEXTUAL_PRIORS_COLD = _load_priors("contextual_priors_cold.json")

# Fallback priors when contextual lookup misses
TERRAIN_PRIORS = {
    10: [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    11: [0.8384, 0.1099, 0.009, 0.0102, 0.0325, 0.0],
    5:  [0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
    4:  [0.0694, 0.1116, 0.0084, 0.0102, 0.8005, 0.0],
    1:  [0.4794, 0.27, 0.0042, 0.0227, 0.2237, 0.0],
    2:  [0.4911, 0.0757, 0.1821, 0.0214, 0.2296, 0.0],
    0:  [0.8384, 0.1099, 0.009, 0.0102, 0.0325, 0.0],
    3:  [0.4794, 0.27, 0.0042, 0.0227, 0.2237, 0.0],
}

# Hidden parameter defaults for the simulator
HIDDEN_PARAMS = {
    "GROWTH": {
        "EXPANSION_RATE": 0.08,
        "EXPANSION_RANGE": 3,
        "PORT_DEVELOPMENT_CHANCE": 0.15,
        "LONGSHIP_BUILD_CHANCE": 0.10,
    },
    "CONFLICT": {
        "RAID_CHANCE": 0.15,
        "CONQUEST_CHANCE": 0.10,
        "LONGSHIP_RAID_RANGE": 10,
    },
    "TRADE": {
        "TRADE_RANGE": 6,
    },
    "WINTER": {
        "WINTER_HARSHNESS": 0.40,
        "COLLAPSE_CHANCE": 0.30,
    },
    "ENVIRONMENT": {
        "RUIN_TO_SETTLEMENT_RECLAIM_RATE": 0.10,
        "RUIN_TO_PORT_RECLAIM_RATE": 0.10,
        "FOREST_OVERTAKE_RATE": 0.05,
    },
}


# ---------------------------------------------------------------------------
# Floor & normalize (unified)
# ---------------------------------------------------------------------------

def floor_and_normalize(prediction):
    """Apply CLASS_FLOORS and renormalize. Mutates in-place and returns."""
    for row in prediction:
        for cell in row:
            for i in range(len(cell)):
                cell[i] = max(cell[i], CLASS_FLOORS[i])
            total = sum(cell)
            for i in range(len(cell)):
                cell[i] /= total
    return prediction


# ---------------------------------------------------------------------------
# Map helpers
# ---------------------------------------------------------------------------

def tile_positions(map_size, vp_size):
    """Evenly space viewport origins to cover the interior with uniform overlap."""
    n_tiles = -(-map_size // vp_size)  # ceil division
    if n_tiles <= 1:
        return [0]
    step = (map_size - vp_size) / (n_tiles - 1)
    return sorted(set(int(i * step + 0.5) for i in range(n_tiles)))

def build_tiling(map_w=MAP_W, map_h=MAP_H):
    """Build full-coverage tiling that skips the 1-cell ocean border."""
    interior_w = map_w - 2
    interior_h = map_h - 2
    xs = [x + 1 for x in tile_positions(interior_w, VIEWPORT)]
    ys = [y + 1 for y in tile_positions(interior_h, VIEWPORT)]
    return [(x, y) for y in ys for x in xs]

def extract_map_dimensions(round_data):
    w = round_data.get("map_width") or round_data.get("width") or MAP_W
    h = round_data.get("map_height") or round_data.get("height") or MAP_H
    return int(w), int(h)

def extract_grid_and_settlements(round_data, seed_index):
    """Extract initial grid and settlement data for a specific seed."""
    initial_states = round_data.get("initial_states") or []
    if seed_index >= len(initial_states):
        raise ValueError(f"Seed index {seed_index} not found")
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

def merge_counts(a, b, map_w, map_h):
    for r in range(map_h):
        for c in range(map_w):
            for k in range(N_CLASSES):
                a[r][c][k] += b[r][c][k]
    return a


# ---------------------------------------------------------------------------
# Warm/cold classification
# ---------------------------------------------------------------------------

def classify_round_warmth(expansion_rate):
    """Returns (prior_table, warmth_label, dist_decay_defaults)."""
    if expansion_rate < WARM_COLD_THRESHOLD:
        return _CONTEXTUAL_PRIORS_COLD, "cold", DIST_DECAY_COLD
    else:
        return _CONTEXTUAL_PRIORS_WARM, "warm", DIST_DECAY_WARM


# ---------------------------------------------------------------------------
# Contextual priors
# ---------------------------------------------------------------------------

def get_contextual_prior(grid, r, c, map_h, map_w, prior_table=None):
    """Get prior for a cell based on terrain + neighborhood context."""
    terrain = grid[r][c]

    if terrain == 10:
        return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    if terrain == 5:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]

    table = prior_table or _CONTEXTUAL_PRIORS

    n_forest = 0
    is_coastal = False
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < map_h and 0 <= nc < map_w:
                if grid[nr][nc] == 4:
                    n_forest += 1
                if grid[nr][nc] == 10:
                    is_coastal = True

    n_forest = min(n_forest, 4)

    # Try exact, then relax features
    for key in [f"{terrain}_{n_forest}_{1 if is_coastal else 0}",
                f"{terrain}_{n_forest}_0",
                f"{terrain}_0_{1 if is_coastal else 0}"]:
        if key in table:
            return list(table[key])

    # Fallback to all-rounds table
    if prior_table is not None:
        for key in [f"{terrain}_{n_forest}_{1 if is_coastal else 0}",
                    f"{terrain}_{n_forest}_0",
                    f"{terrain}_0_{1 if is_coastal else 0}"]:
            if key in _CONTEXTUAL_PRIORS:
                return list(_CONTEXTUAL_PRIORS[key])

    return list(TERRAIN_PRIORS.get(terrain, [1/N_CLASSES] * N_CLASSES))


def get_distance_aware_prior(grid, r, c, map_h, map_w, dist_map, expansion_rate,
                              dist_multipliers=None, port_ratio=0.75, ruin_ratio=0.10,
                              prior_table=None, survival_rate=None,
                              forest_change_rate=None, coastal_preference=None):
    """Prior adjusted for distance to nearest settlement and expansion rate."""
    terrain = grid[r][c]

    if terrain == 10:
        return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    if terrain == 5:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]

    prior = get_contextual_prior(grid, r, c, map_h, map_w, prior_table=prior_table)
    dist = dist_map[r][c]

    # --- Initial settlements: blend survival_rate with contextual prior ---
    if terrain in (1, 2):
        if survival_rate is not None:
            # Count adjacent forests (food = survival advantage)
            n_forest = sum(
                1 for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                if not (dr == 0 and dc == 0)
                and 0 <= r+dr < map_h and 0 <= c+dc < map_w
                and grid[r+dr][c+dc] == 4
            )
            # Adjust survival based on food and coastal trade
            adj_survival = min(0.95, survival_rate + n_forest * 0.04)
            is_port = terrain == 2
            if is_port:
                adj_survival = min(0.95, adj_survival + 0.03)

            # Build survival-based distribution
            surv = [0.0] * 6
            surv[1] = adj_survival * (0.4 if is_port else 0.85)
            surv[2] = adj_survival * (0.6 if is_port else 0.0)
            death = max(0.02, 1.0 - adj_survival)
            surv[3] = death * 0.3
            surv[0] = death * 0.4
            surv[4] = death * 0.3
            total = sum(surv)
            if total > 0:
                surv = [v / total for v in surv]

            # Blend 40% survival model + 60% contextual prior
            blended = [0.4 * surv[k] + 0.6 * prior[k] for k in range(6)]
            total = sum(blended)
            if total > 0:
                blended = [v / total for v in blended]
            return blended
        return prior

    # --- Forest cells: blend forest_change_rate with contextual prior ---
    if terrain == 4 and forest_change_rate is not None:
        change = forest_change_rate
        if dist <= 2:
            change = min(0.8, change * (2.0 if dist == 1 else 1.5))
        elif dist >= 5:
            change = change * 0.3

        stay_forest = max(0.05, 1.0 - change)
        fc = [0.0] * 6
        fc[4] = stay_forest
        fc[1] = change * 0.5
        fc[0] = change * 0.3
        fc[3] = change * 0.1
        fc[2] = change * 0.1
        total = sum(fc)
        if total > 0:
            fc = [v / total for v in fc]

        # Blend 30% forest model + 70% contextual prior
        blended = [0.3 * fc[k] + 0.7 * prior[k] for k in range(6)]
        total = sum(blended)
        if total > 0:
            blended = [v / total for v in blended]
        return blended

    # --- Expandable land cells (plains, empty, ruin) ---
    # Distance-based settlement probability
    mults = dist_multipliers or DIST_DECAY_DEFAULT
    if dist <= 7:
        decay = mults.get(dist, DIST_DECAY_DEFAULT.get(dist, 0.0))
    else:
        decay = max(0.02, 0.5 / max(dist, 1)) if dist <= 10 else 0.0

    target_settle = expansion_rate * decay

    # Coastal preference boost
    is_coastal = any(
        0 <= r+dr < map_h and 0 <= c+dc < map_w and grid[r+dr][c+dc] == 10
        for dr in (-1, 0, 1) for dc in (-1, 0, 1) if not (dr == 0 and dc == 0)
    )
    if is_coastal and coastal_preference is not None:
        target_settle *= coastal_preference

    # Coastal → ports; activity → ruins
    target_port = target_settle * port_ratio if is_coastal else 0.0
    target_ruin = target_settle * ruin_ratio

    # Total dynamic probability (computed once, after all boosts)
    target_dynamic = target_settle + target_port + target_ruin

    # Distribute remaining probability among static classes proportionally
    remaining = max(0.01, 1.0 - target_dynamic)
    static_classes = [0, 4, 5]
    base_static = sum(prior[k] for k in static_classes)

    adjusted = [0.0] * 6
    adjusted[1] = target_settle
    adjusted[2] = target_port
    adjusted[3] = target_ruin

    if base_static > 0:
        for k in static_classes:
            adjusted[k] = remaining * (prior[k] / base_static)
    else:
        adjusted[0] = remaining

    total = sum(adjusted)
    if total > 0:
        adjusted = [v / total for v in adjusted]

    return adjusted


# ---------------------------------------------------------------------------
# Distance / expansion estimation from observations
# ---------------------------------------------------------------------------

def compute_settlement_distances(grid, map_h, map_w):
    """BFS Chebyshev distance from each cell to nearest initial settlement/port."""
    dist = [[999] * map_w for _ in range(map_h)]
    queue = []
    for r in range(map_h):
        for c in range(map_w):
            if grid[r][c] in (1, 2):  # settlement or port
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
                if 0 <= nr < map_h and 0 <= nc < map_w and dist[nr][nc] > dist[r][c] + 1:
                    dist[nr][nc] = dist[r][c] + 1
                    queue.append((nr, nc))
    return dist


def estimate_seed_expansion_rate(obs_counts, grid, dist_map, map_h, map_w):
    """Estimate expansion rate for a single seed from its observations."""
    settle_obs = 0
    total_obs = 0
    for r in range(map_h):
        for c in range(map_w):
            n_obs = sum(obs_counts[r][c])
            if n_obs == 0:
                continue
            if grid[r][c] in (10, 5, 1, 2):  # skip ocean, mountain, existing settlements
                continue
            d = dist_map[r][c]
            if d < 1 or d > 3:
                continue
            total_obs += n_obs
            settle_obs += obs_counts[r][c][1]
    if total_obs == 0:
        return 0.10, 0
    return settle_obs / total_obs, total_obs


def pick_phase2_viewports(seed_grids, seed_counts, remaining, map_w=MAP_W, map_h=MAP_H):
    """Allocate remaining queries using expansion-rate confidence targeting.

    1. Compute per-seed expansion rate from Phase 1 observations.
    2. If seeds disagree (high variance) → target boundary cells (dist 1-3)
       across multiple seeds to nail down expansion rate.
    3. If seeds agree (low variance) → target the most surprising seed's
       boundary cells for better per-cell estimates.

    Returns: list of (seed_index, vx, vy) tuples.
    """
    if remaining <= 0:
        return []

    # Compute per-seed expansion rates
    seed_rates = {}
    for s in range(N_SEEDS):
        grid = seed_grids.get(s)
        counts = seed_counts.get(s)
        if grid is None or counts is None:
            continue
        dist_map = compute_settlement_distances(grid, map_h, map_w)
        rate, n_samples = estimate_seed_expansion_rate(counts, grid, dist_map, map_h, map_w)
        seed_rates[s] = (rate, n_samples, dist_map)

    if not seed_rates:
        return []

    rates = [r for r, _, _ in seed_rates.values()]
    mean_rate = sum(rates) / len(rates)
    variance = sum((r - mean_rate) ** 2 for r in rates) / len(rates)

    # Find boundary cells (dist 1-3) per seed and score them by surprise
    def boundary_viewport(seed_idx, grid, counts, dist_map):
        """Find the best 15x15 viewport maximizing coverage of boundary cells
        where observation disagreed with prior (high surprise)."""
        best_vp = None
        best_score = -1
        # Score each possible viewport position
        for vy in range(1, map_h - VIEWPORT):
            for vx in range(1, map_w - VIEWPORT):
                score = 0
                for r in range(vy, min(vy + VIEWPORT, map_h)):
                    for c in range(vx, min(vx + VIEWPORT, map_w)):
                        d = dist_map[r][c]
                        if d < 1 or d > 3:
                            continue
                        if grid[r][c] in (10, 5, 1, 2):
                            continue
                        n_obs = sum(counts[r][c])
                        if n_obs == 0:
                            continue
                        obs_settle = counts[r][c][1] / n_obs
                        surprise = abs(obs_settle - mean_rate)
                        score += surprise + 0.5  # bonus for every boundary cell
                if score > best_score:
                    best_score = score
                    best_vp = (vx, vy)
        return best_vp, best_score

    queries = []
    high_variance = variance > 0.005  # seeds disagree on expansion rate

    if high_variance:
        # Target outlier seeds to resolve disagreement
        seed_order = sorted(seed_rates.keys(),
                            key=lambda s: abs(seed_rates[s][0] - mean_rate),
                            reverse=True)
    else:
        # Target most surprising seed for better per-cell estimates
        seed_surprise = {}
        for s in range(N_SEEDS):
            counts = seed_counts.get(s)
            grid = seed_grids.get(s)
            if counts is None or grid is None:
                continue
            surprise = 0.0
            n_cells = 0
            for r in range(map_h):
                for c in range(map_w):
                    n_obs = sum(counts[r][c])
                    if n_obs == 0:
                        continue
                    n_cells += 1
                    obs_frac = [counts[r][c][k] / n_obs for k in range(N_CLASSES)]
                    surprise += sum(abs(obs_frac[k] - 1.0 / N_CLASSES) for k in range(N_CLASSES))
            seed_surprise[s] = surprise / max(n_cells, 1)
        seed_order = sorted(seed_surprise, key=seed_surprise.get, reverse=True)

    used_seeds = set()
    for s in seed_order:
        if remaining <= 0:
            break
        grid = seed_grids[s]
        counts = seed_counts[s]
        _, _, dist_map = seed_rates[s]
        vp, score = boundary_viewport(s, grid, counts, dist_map)
        if vp:
            queries.append((s, vp[0], vp[1]))
            remaining -= 1
            used_seeds.add(s)

    # If we still have budget, cycle through seeds again
    for s in seed_order:
        if remaining <= 0:
            break
        if s in used_seeds:
            continue
        grid = seed_grids[s]
        counts = seed_counts[s]
        _, _, dist_map = seed_rates[s]
        vp, score = boundary_viewport(s, grid, counts, dist_map)
        if vp:
            queries.append((s, vp[0], vp[1]))
            remaining -= 1

    return queries


# ---------------------------------------------------------------------------
# Expansion & distance estimation (aggregated across seeds)
# ---------------------------------------------------------------------------

def estimate_dist_decay(grid, obs_counts, dist_map, map_h, map_w):
    """Per-distance settlement rate from observations for one seed."""
    dist_settle = {}
    for r in range(map_h):
        for c in range(map_w):
            n_obs = sum(obs_counts[r][c])
            if n_obs == 0:
                continue
            terrain = grid[r][c]
            if terrain in (10, 5, 1, 2):
                continue
            d = dist_map[r][c]
            if d < 1 or d > 7:
                continue
            if d not in dist_settle:
                dist_settle[d] = [0, 0]
            dist_settle[d][0] += obs_counts[r][c][1]
            dist_settle[d][1] += n_obs
    return dist_settle


def estimate_port_ruin_ratios(seed_grids, seed_counts, map_h, map_w):
    """Estimate port/settle and ruin/settle ratios from observations."""
    port_obs = ruin_obs = settle_obs = 0
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
                if grid[r][c] in (10, 5, 1, 2):
                    continue
                settle_obs += counts[r][c][1]
                ruin_obs += counts[r][c][3]
                # Check coastal for port
                is_coastal = any(
                    0 <= r+dr < map_h and 0 <= c+dc < map_w and grid[r+dr][c+dc] == 10
                    for dr in (-1, 0, 1) for dc in (-1, 0, 1) if not (dr == 0 and dc == 0)
                )
                if is_coastal:
                    port_obs += counts[r][c][2]
    port_ratio = port_obs / max(settle_obs, 1) if settle_obs > 10 else 0.10
    ruin_ratio = ruin_obs / max(settle_obs, 1) if settle_obs > 10 else 0.10
    return port_ratio, ruin_ratio


def estimate_survival_rate(seed_grids, seed_counts, map_h, map_w):
    """Estimate what fraction of initial settlements survive to year 50.

    Looks at cells that start as settlement/port and counts how often
    they're still settlement/port in observations.
    Returns None if insufficient data (< 20 observations).
    """
    alive_obs = 0
    total_obs = 0
    for s in seed_grids:
        grid = seed_grids[s]
        counts = seed_counts.get(s)
        if counts is None:
            continue
        for r in range(map_h):
            for c in range(map_w):
                if grid[r][c] not in (1, 2):
                    continue
                n_obs = sum(counts[r][c])
                if n_obs == 0:
                    continue
                total_obs += n_obs
                alive_obs += counts[r][c][1] + counts[r][c][2]
    if total_obs < 20:
        return None  # not enough data, fall back to contextual prior
    return alive_obs / total_obs


def estimate_forest_change_rate(seed_grids, seed_counts, map_h, map_w):
    """Estimate what fraction of initial forest cells change to non-forest.

    Returns None if insufficient data (< 30 observations).
    """
    changed_obs = 0
    total_obs = 0
    for s in seed_grids:
        grid = seed_grids[s]
        counts = seed_counts.get(s)
        if counts is None:
            continue
        for r in range(map_h):
            for c in range(map_w):
                if grid[r][c] != 4:
                    continue
                n_obs = sum(counts[r][c])
                if n_obs == 0:
                    continue
                total_obs += n_obs
                changed_obs += n_obs - counts[r][c][4]
    if total_obs < 30:
        return None  # not enough data
    return changed_obs / total_obs


def estimate_coastal_preference(seed_grids, seed_counts, map_h, map_w):
    """Estimate how much more likely expansion targets coastal vs inland cells.

    Returns None if insufficient data (< 10 coastal settlement observations).
    """
    coastal_settle = coastal_total = 0
    inland_settle = inland_total = 0
    for s in seed_grids:
        grid = seed_grids[s]
        counts = seed_counts.get(s)
        if counts is None:
            continue
        for r in range(map_h):
            for c in range(map_w):
                if grid[r][c] in (10, 5, 1, 2):
                    continue
                n_obs = sum(counts[r][c])
                if n_obs == 0:
                    continue
                is_coastal = any(
                    0 <= r+dr < map_h and 0 <= c+dc < map_w and grid[r+dr][c+dc] == 10
                    for dr in (-1, 0, 1) for dc in (-1, 0, 1) if not (dr == 0 and dc == 0)
                )
                settle_obs = counts[r][c][1] + counts[r][c][2]
                if is_coastal:
                    coastal_settle += settle_obs
                    coastal_total += n_obs
                else:
                    inland_settle += settle_obs
                    inland_total += n_obs
    if coastal_settle < 10 or inland_total < 50:
        return None  # not enough coastal data
    coastal_rate = coastal_settle / max(coastal_total, 1)
    inland_rate = inland_settle / max(inland_total, 1)
    if inland_rate < 0.001:
        return None
    return min(5.0, coastal_rate / inland_rate)


def aggregate_expansion_stats(seed_grids, seed_counts, map_h, map_w):
    """Compute expansion rate, distance multipliers, port/ruin ratios from all seeds.

    Returns: (expansion_rate, dist_multipliers, port_ratio, ruin_ratio,
              prior_table, warmth, survival_rate, forest_change_rate, coastal_preference)
    """
    agg_dist_settle = {}
    expansion_rates = []

    initial_grid = seed_grids.get(0, [[11] * map_w for _ in range(map_h)])

    for s in range(N_SEEDS):
        grid = seed_grids.get(s, initial_grid)
        counts = seed_counts.get(s)
        if counts is None:
            continue
        dist_map = compute_settlement_distances(grid, map_h, map_w)
        rate, n_samples = estimate_seed_expansion_rate(counts, grid, dist_map, map_h, map_w)
        if n_samples > 0:
            expansion_rates.append((rate, n_samples))

        seed_dist = estimate_dist_decay(grid, counts, dist_map, map_h, map_w)
        for d, (s_count, t_count) in seed_dist.items():
            if d not in agg_dist_settle:
                agg_dist_settle[d] = [0, 0]
            agg_dist_settle[d][0] += s_count
            agg_dist_settle[d][1] += t_count

    if expansion_rates:
        total_samples = sum(n for _, n in expansion_rates)
        avg_expansion = sum(r * n for r, n in expansion_rates) / total_samples
    else:
        avg_expansion = 0.10

    # Classify warmth and get appropriate defaults
    prior_table, warmth, decay_defaults = classify_round_warmth(avg_expansion)

    # Compute per-distance multipliers from observations
    d13_settle = sum(agg_dist_settle.get(d, [0, 0])[0] for d in [1, 2, 3])
    d13_total = sum(agg_dist_settle.get(d, [0, 0])[1] for d in [1, 2, 3])
    base_rate = d13_settle / d13_total if d13_total > 0 else avg_expansion

    dist_multipliers = {}
    for d in range(1, 8):
        if d in agg_dist_settle and agg_dist_settle[d][1] >= 10 and base_rate > 0.001:
            dist_multipliers[d] = (agg_dist_settle[d][0] / agg_dist_settle[d][1]) / base_rate
        else:
            dist_multipliers[d] = decay_defaults.get(d, 0.0)

    port_ratio, ruin_ratio = estimate_port_ruin_ratios(seed_grids, seed_counts, map_h, map_w)

    # New hidden parameters
    survival_rate = estimate_survival_rate(seed_grids, seed_counts, map_h, map_w)
    forest_change_rate = estimate_forest_change_rate(seed_grids, seed_counts, map_h, map_w)
    coastal_pref = estimate_coastal_preference(seed_grids, seed_counts, map_h, map_w)

    return (avg_expansion, dist_multipliers, port_ratio, ruin_ratio,
            prior_table, warmth, survival_rate, forest_change_rate, coastal_pref)


# ---------------------------------------------------------------------------
# Observation strategy constants
# ---------------------------------------------------------------------------

# How many seeds to observe deeply (the rest get 0 direct observations)
N_DEEP_SEEDS = 3
# Queries per deep seed: coverage (9) + repeated observations for depth
# With budget=50 and 3 deep seeds: ~16 queries per seed
# That gives ~1.8 observations per cell on average (9 tiles cover ~90%)
# Plus ~7 extra queries for repeat coverage of dynamic areas

# ---------------------------------------------------------------------------
# Observation phase runner
# ---------------------------------------------------------------------------

def _pick_deep_seeds(seed_grids, n_deep, map_h, map_w):
    """Pick which seeds to observe deeply based on map diversity.

    Selects seeds whose initial maps are most different from each other,
    maximizing the variety of terrain configurations we learn from.
    """
    if len(seed_grids) <= n_deep:
        return list(range(len(seed_grids)))

    # Compute pairwise terrain difference between seeds
    def terrain_diff(g1, g2):
        diff = 0
        for r in range(min(len(g1), len(g2))):
            for c in range(min(len(g1[0]), len(g2[0]))):
                if g1[r][c] != g2[r][c]:
                    diff += 1
        return diff

    # Greedy: start with seed 0, then pick the seed most different from selected set
    selected = [0]
    remaining = set(range(1, N_SEEDS))
    while len(selected) < n_deep and remaining:
        best_seed = max(remaining, key=lambda s: min(
            terrain_diff(seed_grids.get(s, []), seed_grids.get(sel, []))
            for sel in selected
        ))
        selected.append(best_seed)
        remaining.discard(best_seed)

    return sorted(selected)


def _build_depth_viewports(tiling, n_extra, map_w, map_h, seed_grid=None):
    """Build viewport list: full tiling + extra viewports targeting dynamic areas.

    Extra viewports are placed over areas near initial settlements (distance 1-4)
    where the most uncertain dynamics happen.
    """
    viewports = list(tiling)  # base coverage

    if n_extra <= 0 or seed_grid is None:
        return viewports

    # Score each possible viewport by how many "interesting" cells it covers
    # Interesting = land cells near settlements (distance 1-4)
    dist_map = compute_settlement_distances(seed_grid, map_h, map_w)

    scored_vps = []
    for vy in range(1, map_h - VIEWPORT + 1):
        for vx in range(1, map_w - VIEWPORT + 1):
            score = 0
            for r in range(vy, min(vy + VIEWPORT, map_h)):
                for c in range(vx, min(vx + VIEWPORT, map_w)):
                    d = dist_map[r][c]
                    terrain = seed_grid[r][c]
                    if terrain in (10, 5):  # ocean, mountain — static
                        continue
                    if 1 <= d <= 4:
                        score += 4 - d + 1  # closer to settlement = higher score
            scored_vps.append((score, vx, vy))

    scored_vps.sort(reverse=True)

    # Pick top viewports, avoiding too much overlap with already selected
    for score, vx, vy in scored_vps:
        if len(viewports) >= len(tiling) + n_extra:
            break
        # Check overlap with existing viewports — allow some but not full overlap
        too_close = False
        for evx, evy in viewports[len(tiling):]:  # only check extra vps
            if abs(vx - evx) < VIEWPORT // 2 and abs(vy - evy) < VIEWPORT // 2:
                too_close = True
                break
        if not too_close:
            viewports.append((vx, vy))

    return viewports


def run_observation_phases(seed_grids, total_budget, map_w, map_h,
                           observe_fn, print_fn=print):
    """Depth-over-breadth observation strategy.

    Instead of spreading 50 queries across all 5 seeds (9 each, ~1 obs/cell),
    observe N_DEEP_SEEDS seeds deeply with multiple observations per cell.
    The remaining seeds get 0 direct observations and rely on learned parameters
    + priors + MC simulation.

    Returns: (seed_counts, expansion_rate, dist_multipliers, prior_table,
              port_ratio, ruin_ratio, warmth)
    """
    tiling = build_tiling(map_w, map_h)
    n_tiles = len(tiling)  # typically 9

    # Pick which seeds to observe deeply
    deep_seeds = _pick_deep_seeds(seed_grids, N_DEEP_SEEDS, map_h, map_w)
    print_fn(f"  Deep observation seeds: {deep_seeds} ({N_DEEP_SEEDS} of {N_SEEDS})")

    # Allocate budget across deep seeds
    budget_per_seed = total_budget // len(deep_seeds)
    leftover = total_budget - budget_per_seed * len(deep_seeds)

    seed_counts = {}
    budget_spent = 0

    for seed_idx in range(N_SEEDS):
        if seed_idx not in deep_seeds:
            seed_counts[seed_idx] = [[[0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
            continue

        # This seed gets deep observations
        seed_budget = budget_per_seed + (1 if leftover > 0 else 0)
        if leftover > 0:
            leftover -= 1

        n_extra = seed_budget - n_tiles
        grid = seed_grids.get(seed_idx)
        viewports = _build_depth_viewports(tiling, n_extra, map_w, map_h, seed_grid=grid)
        viewports = viewports[:seed_budget]  # cap to budget

        print_fn(f"  Seed {seed_idx}: {len(viewports)} queries "
                 f"({n_tiles} coverage + {len(viewports) - n_tiles} depth)")
        seed_counts[seed_idx] = observe_fn(seed_idx, viewports)
        budget_spent += len(viewports)

    # Aggregate stats from observed seeds
    (avg_expansion, dist_multipliers, port_ratio, ruin_ratio,
     prior_table, warmth, survival_rate, forest_change_rate, coastal_pref) = \
        aggregate_expansion_stats(seed_grids, seed_counts, map_h, map_w)

    print_fn(f"  Expansion rate: {avg_expansion:.4f} → {warmth} round")
    print_fn(f"  Dist multipliers: " + " ".join(f"d{d}={dist_multipliers.get(d, 0):.2f}" for d in range(1, 8)))
    print_fn(f"  Port ratio: {port_ratio:.3f}, Ruin ratio: {ruin_ratio:.3f}")
    sr_str = f"{survival_rate:.3f}" if survival_rate is not None else "N/A (low data)"
    fc_str = f"{forest_change_rate:.3f}" if forest_change_rate is not None else "N/A (low data)"
    cp_str = f"{coastal_pref:.2f}x" if coastal_pref is not None else "N/A (low data)"
    print_fn(f"  Survival rate: {sr_str}, Forest change: {fc_str}, Coastal pref: {cp_str}")

    return (seed_counts, avg_expansion, dist_multipliers, prior_table,
            port_ratio, ruin_ratio, warmth, survival_rate, forest_change_rate, coastal_pref)


# ---------------------------------------------------------------------------
# Prediction generation
# ---------------------------------------------------------------------------

def generate_prediction(grid, settlements, map_w, map_h,
                        obs_counts=None, sim_pred=None,
                        expansion_rate=None, dist_multipliers=None,
                        port_ratio=0.75, ruin_ratio=0.10,
                        prior_table=None, warmth="warm",
                        survival_rate=None, forest_change_rate=None,
                        coastal_preference=None):
    """Generate prediction by blending distance-aware priors + observations + simulator.

    Warm/cold-aware: uses SIM_WEIGHT_COLD=0 for cold rounds.
    """
    sim_weight = SIM_WEIGHT_WARM if warmth == "warm" else SIM_WEIGHT_COLD

    # Simulator safety net
    if sim_pred is not None and obs_counts is not None and sim_weight > 0:
        agree = total = 0
        for r in range(map_h):
            for c in range(map_w):
                n_obs = sum(obs_counts[r][c])
                if n_obs < 1:
                    continue
                obs_argmax = max(range(N_CLASSES), key=lambda k: obs_counts[r][c][k])
                sim_argmax = max(range(N_CLASSES), key=lambda k: sim_pred[r][c][k])
                total += 1
                if obs_argmax == sim_argmax:
                    agree += 1
        if total > 0 and agree / total < SIM_SAFETY_THRESHOLD:
            sim_pred = None
            sim_weight = 0.0

    dist_map = None
    if expansion_rate is not None:
        dist_map = compute_settlement_distances(grid, map_h, map_w)

    prediction = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
    for r in range(map_h):
        for c in range(map_w):
            if dist_map is not None:
                prior = get_distance_aware_prior(
                    grid, r, c, map_h, map_w, dist_map, expansion_rate,
                    dist_multipliers=dist_multipliers,
                    port_ratio=port_ratio, ruin_ratio=ruin_ratio,
                    prior_table=prior_table, survival_rate=survival_rate,
                    forest_change_rate=forest_change_rate,
                    coastal_preference=coastal_preference)
            else:
                prior = get_contextual_prior(grid, r, c, map_h, map_w, prior_table=prior_table)

            n_obs = sum(obs_counts[r][c]) if obs_counts else 0
            use_obs = n_obs >= MIN_OBS_TO_BLEND and OBS_WEIGHT > 0
            ow = OBS_WEIGHT * (n_obs ** OBS_EXPONENT) if use_obs else 0

            if ow > 0 or sim_weight > 0:
                total_w = ow + sim_weight + PRIOR_WEIGHT
                for k in range(N_CLASSES):
                    val = PRIOR_WEIGHT * prior[k]
                    if ow > 0:
                        val += ow * (obs_counts[r][c][k] / n_obs)
                    if sim_pred is not None:
                        val += sim_weight * sim_pred[r][c][k]
                    prediction[r][c][k] = val / total_w
            else:
                prediction[r][c] = prior

    return floor_and_normalize(prediction)


def pool_observations(seed_counts, map_w, map_h):
    """Pool observation counts across all seeds into a single grid.

    Since all seeds share the same hidden parameters, pooling gives 5x more
    data per cell — especially valuable on cold rounds where dynamic cells are rare.
    """
    pooled = [[[0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
    for s in seed_counts:
        counts = seed_counts[s]
        for r in range(map_h):
            for c in range(map_w):
                for k in range(N_CLASSES):
                    pooled[r][c][k] += counts[r][c][k]
    return pooled


# Equiv samples for Bayesian obs update
# Cold rounds: pooled obs (5x data) + higher equiv (trust prior more per obs)
# Warm rounds: per-seed obs + lower equiv (trust obs more)
EQUIV_COLD_POOLED = 50
EQUIV_WARM_PER_SEED = 20


def validate_mc_against_obs(mc_pred, obs_counts, map_h, map_w):
    """Check if MC predictions agree with observations. Returns agreement rate."""
    agree = total = 0
    for r in range(map_h):
        for c in range(map_w):
            n_obs = sum(obs_counts[r][c])
            if n_obs < 1:
                continue
            obs_argmax = max(range(N_CLASSES), key=lambda k: obs_counts[r][c][k])
            mc_argmax = max(range(N_CLASSES), key=lambda k: mc_pred[r][c][k])
            total += 1
            if obs_argmax == mc_argmax:
                agree += 1
    return agree / max(total, 1), total


def generate_prediction_abc(grid, mc_pred, map_w, map_h,
                             obs_counts=None, expansion_rate=None,
                             dist_multipliers=None, port_ratio=0.75,
                             ruin_ratio=0.10, prior_table=None,
                             warmth="warm", survival_rate=None,
                             forest_change_rate=None, coastal_preference=None):
    """Three-layer blending: distance-aware prior + ABC MC + Bayesian obs update."""
    dist_map = None
    if expansion_rate is not None:
        dist_map = compute_settlement_distances(grid, map_h, map_w)

    is_cold = warmth == "cold"

    equiv_samples = EQUIV_COLD_POOLED if is_cold else EQUIV_WARM_PER_SEED

    # Validate MC against observations — skip if it disagrees too much
    # If no observations exist for this seed, trust MC (it was fitted on other seeds)
    mc_w = 0.0
    if mc_pred is not None:
        if obs_counts is not None:
            agreement, n_compared = validate_mc_against_obs(mc_pred, obs_counts, map_h, map_w)
            if n_compared == 0 or agreement >= SIM_SAFETY_THRESHOLD:
                mc_w = ABC_MC_WEIGHT
            # else: mc_w stays 0, prior-only blend
        else:
            mc_w = ABC_MC_WEIGHT  # no obs to validate against, use MC
    prior_w = ABC_PRIOR_WEIGHT

    prediction = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]
    for r in range(map_h):
        for c in range(map_w):
            # Layer 1: distance-aware prior
            if dist_map is not None:
                prior = get_distance_aware_prior(
                    grid, r, c, map_h, map_w, dist_map, expansion_rate,
                    dist_multipliers=dist_multipliers,
                    port_ratio=port_ratio, ruin_ratio=ruin_ratio,
                    prior_table=prior_table, survival_rate=survival_rate,
                    forest_change_rate=forest_change_rate,
                    coastal_preference=coastal_preference)
            else:
                prior = get_contextual_prior(grid, r, c, map_h, map_w, prior_table=prior_table)

            # Layer 2: blend MC
            blended = [0.0] * N_CLASSES
            for k in range(N_CLASSES):
                blended[k] = prior_w * prior[k]
                if mc_pred is not None:
                    blended[k] += mc_w * mc_pred[r][c][k]
            total = sum(blended)
            if total > 0:
                blended = [v / total for v in blended]

            # Layer 3: Bayesian Dirichlet update with observations
            n_obs = sum(obs_counts[r][c]) if obs_counts else 0
            if n_obs > 0:
                alpha = [blended[k] * equiv_samples for k in range(N_CLASSES)]
                posterior = [alpha[k] + obs_counts[r][c][k] for k in range(N_CLASSES)]
                total = sum(posterior)
                prediction[r][c] = [p / total for p in posterior]
            else:
                prediction[r][c] = blended

    return floor_and_normalize(prediction)


# ---------------------------------------------------------------------------
# Live game logging
# ---------------------------------------------------------------------------

_LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
_ROUNDS_DIR = os.path.join(_LOGS_DIR, "rounds")
_INDEX_PATH = os.path.join(_LOGS_DIR, "index.json")


def _ensure_round_log(round_id, map_width=MAP_W, map_height=MAP_H):
    os.makedirs(_ROUNDS_DIR, exist_ok=True)
    path = os.path.join(_ROUNDS_DIR, f"{round_id}.json")
    if os.path.exists(path):
        with open(path) as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    from datetime import datetime, timezone
    data = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "map_width": map_width, "map_height": map_height,
        "queries": [], "submissions": [], "actions": [],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    # Update index
    try:
        with open(_INDEX_PATH) as f:
            index = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        index = {"rounds": []}
    if not any(r["id"] == round_id for r in index["rounds"]):
        from datetime import datetime, timezone
        index["rounds"].append({"id": round_id, "started_at": datetime.now(timezone.utc).isoformat()})
        with open(_INDEX_PATH, "w") as f:
            json.dump(index, f, indent=2)
    return data


def _save_round_log(round_id, data):
    path = os.path.join(_ROUNDS_DIR, f"{round_id}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def log_action(round_id, action, details=None):
    from datetime import datetime, timezone
    data = _ensure_round_log(round_id)
    data["actions"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action, "details": details or {},
    })
    _save_round_log(round_id, data)


def log_query(round_id, seed_index, viewport, grid, budget_remaining):
    from datetime import datetime, timezone
    data = _ensure_round_log(round_id)
    data["queries"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed_index": seed_index, "viewport": viewport,
        "grid": grid, "budget_remaining": budget_remaining,
    })
    _save_round_log(round_id, data)


def log_submission(round_id, seed_index, result):
    from datetime import datetime, timezone
    data = _ensure_round_log(round_id)
    data["submissions"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed_index": seed_index, "result": result,
    })
    _save_round_log(round_id, data)


# ---------------------------------------------------------------------------
# Live game observation (calls real API)
# ---------------------------------------------------------------------------

RATE_LIMIT_DELAY = 0.25


def observe_seed_live(round_id, seed_index, viewports, map_w, map_h):
    """Run simulate queries against the real API for one seed."""
    import time as _time
    from shared.utils import simulate

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

        log_query(round_id, seed_index,
                  {"x": vx, "y": vy, "w": VIEWPORT, "h": VIEWPORT},
                  grid, budget)

        for r, row in enumerate(grid):
            for c, val in enumerate(row):
                map_r = vy + r
                map_c = vx + c
                if 0 <= map_r < map_h and 0 <= map_c < map_w:
                    cls = TERRAIN_TO_CLASS.get(val, 0)
                    counts[map_r][map_c][cls] += 1

        print(f"    budget remaining: {budget}")
        _time.sleep(RATE_LIMIT_DELAY)

    return counts


# ---------------------------------------------------------------------------
# Live game main
# ---------------------------------------------------------------------------

def main():
    import time as _time
    from shared.utils import get_active_round, get_round as fetch_round, get_budget, submit

    # 1. Find active round
    print("Fetching active round...")
    active = get_active_round()
    if not active:
        print("No active round found. Exiting.")
        return

    round_id = active["id"]
    print(f"Active round: {round_id}")
    log_action(round_id, "fetch_active_round", {"round": active})

    # 2. Get round details
    round_data = fetch_round(round_id)
    map_w, map_h = extract_map_dimensions(round_data)
    _ensure_round_log(round_id, map_w, map_h)
    log_action(round_id, "fetch_round_details", {"raw_response": round_data})
    print(f"Map: {map_w}x{map_h}")

    # Parse per-seed grids
    initial_states = round_data.get("initial_states") or []
    seed_grids = {}
    for i, state in enumerate(initial_states):
        grid = state.get("grid") or state.get("terrain") or []
        if grid:
            seed_grids[i] = grid

    for si in sorted(seed_grids.keys()):
        g = seed_grids[si]
        n_settle = sum(1 for r in g for c in r if c in (1, 2))
        n_forest = sum(1 for r in g for c in r if c == 4)
        print(f"  Seed {si}: {n_settle} settlements/ports, {n_forest} forests")

    # 3. Check budget
    budget_info = get_budget()
    log_action(round_id, "check_budget", {"raw_response": budget_info})
    used = budget_info.get("queries_used", 0)
    max_q = budget_info.get("queries_max", 50)
    total_budget = int(max_q) - int(used)
    print(f"Budget: {total_budget} remaining ({used} used / {max_q} max)")

    if total_budget <= 0:
        print("No budget remaining. Exiting.")
        return

    # 4. Run observations using depth-over-breadth strategy
    def live_observe(seed_idx, viewports):
        print(f"\n--- Seed {seed_idx} ({len(viewports)} queries) ---")
        log_action(round_id, "start_seed_observation", {
            "seed_index": seed_idx, "num_queries": len(viewports),
        })
        return observe_seed_live(round_id, seed_idx, viewports, map_w, map_h)

    (seed_counts, avg_expansion, dist_multipliers, prior_table,
     port_ratio, ruin_ratio, warmth, survival_rate, forest_change_rate, coastal_pref) = \
        run_observation_phases(
            seed_grids, total_budget, map_w, map_h,
            observe_fn=live_observe,
        )

    log_action(round_id, "expansion_rate_estimate", {
        "pooled_rate": round(avg_expansion, 4),
        "warmth": warmth,
        "dist_multipliers": {str(k): round(v, 3) for k, v in dist_multipliers.items()},
        "port_ratio": round(port_ratio, 3),
        "ruin_ratio": round(ruin_ratio, 3),
        "survival_rate": round(survival_rate, 3) if survival_rate is not None else None,
        "forest_change_rate": round(forest_change_rate, 3) if forest_change_rate is not None else None,
        "coastal_preference": round(coastal_pref, 2) if coastal_pref is not None else None,
    })

    # 5. Pool observations for cold rounds
    is_cold = warmth == "cold"
    if is_cold:
        pooled_counts = pool_observations(seed_counts, map_w, map_h)
        print("Cold round: using pooled observations across all seeds")

    # 6. Generate predictions and submit for each seed
    for seed_idx in range(N_SEEDS):
        print(f"\nBuilding prediction for seed {seed_idx}...")

        grid, settlements = extract_grid_and_settlements(round_data, seed_idx)
        effective_obs = pooled_counts if is_cold else seed_counts[seed_idx]

        t0 = _time.time()

        # Use prior + Bayesian obs update (no MC in live — too slow)
        prediction = generate_prediction_abc(
            grid, None, map_w, map_h,
            obs_counts=effective_obs,
            expansion_rate=avg_expansion, dist_multipliers=dist_multipliers,
            port_ratio=port_ratio, ruin_ratio=ruin_ratio,
            prior_table=prior_table, warmth=warmth,
            survival_rate=survival_rate, forest_change_rate=forest_change_rate,
            coastal_preference=coastal_pref)

        elapsed = _time.time() - t0
        print(f"  Prediction built in {elapsed:.1f}s")

        log_action(round_id, "build_prediction", {
            "seed_index": seed_idx,
            "method": "v2_prior_obs_bayesian",
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
                "seed_index": seed_idx, "error": str(e),
            })
        _time.sleep(0.6)

    log_action(round_id, "run_complete", {"seeds_submitted": N_SEEDS})
    print("\nDone! All 5 seeds submitted.")


if __name__ == "__main__":
    main()
