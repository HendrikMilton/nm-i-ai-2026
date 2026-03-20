"""
Astar Island v4 — Distance-aware prior pipeline.

Key insight from Elias's experiments: pure distance-aware priors outperform
ABC+MC+simulator. Observations are used ONLY to calibrate expansion rate and
distance-decay multipliers, not directly in predictions.

Settlement probability at each cell = expansion_rate × distance_decay[dist]
where dist = Chebyshev distance to nearest initial settlement/port.

Usage:
    AINM_TOKEN=<token> python predict_v4.py
    AINM_TOKEN=<token> python predict_v4.py --from-cache observations_r8.json
    AINM_TOKEN=<token> python predict_v4.py --dry-run
    AINM_TOKEN=<token> python predict_v4.py --save-round-data round8.json
    python predict_v4.py --from-cache observations_r8.json --round-data round8.json --dry-run
"""
import argparse
import json
import os
import time
import numpy as np

from api_client import (
    get_round, get_active_round, get_budget,
    simulate_viewport, submit_prediction,
)
from dashboard_logger import log_action, log_query, log_submission, log_prediction


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

N_CLASSES = 6
N_SEEDS = 5
VIEWPORT = 15
RATE_LIMIT_DELAY = 0.22

TERRAIN_TO_CLASS = {
    0: 0, 10: 0, 11: 0,  # empty / ocean / plains → empty
    1: 1,   # settlement
    2: 2,   # port
    3: 3,   # ruin
    4: 4,   # forest
    5: 5,   # mountain
}

# Default distance decay multipliers calibrated from R1-R7 ground truth.
# Values are relative to base rate (d1-3 average = 1.0).
DIST_DECAY_DEFAULT = {
    0: 0.0,   # at a settlement — it moves to its own class
    1: 1.20,
    2: 1.00,
    3: 0.70,
    4: 0.50,
    5: 0.30,
    6: 0.20,
    7: 0.10,
}

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CONTEXTUAL_PRIORS_PATH = os.path.join(_THIS_DIR, "contextual_priors.json")
_contextual_priors = {}
if os.path.exists(_CONTEXTUAL_PRIORS_PATH):
    with open(_CONTEXTUAL_PRIORS_PATH) as _f:
        _cp = json.load(_f)
        # Use 'warm' table as default (most rounds are warm)
        _contextual_priors = _cp.get("warm", _cp.get("all", {}))


# ---------------------------------------------------------------------------
# Contextual prior lookup
# ---------------------------------------------------------------------------

_FALLBACK_PRIORS = {
    10: [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],              # ocean
    5:  [0.0, 0.0, 0.0, 0.0, 0.0, 1.0],               # mountain
    11: [0.8384, 0.1099, 0.009, 0.0102, 0.0325, 0.0], # plains
    4:  [0.0694, 0.1116, 0.0084, 0.0102, 0.8005, 0.0], # forest
    1:  [0.4794, 0.27,   0.0042, 0.0227, 0.2237, 0.0], # settlement
    2:  [0.4911, 0.0757, 0.1821, 0.0214, 0.2296, 0.0], # port
    0:  [0.8384, 0.1099, 0.009, 0.0102, 0.0325, 0.0],  # empty
    3:  [0.4794, 0.27,   0.0042, 0.0227, 0.2237, 0.0], # ruin
}


def get_contextual_prior(grid, r, c, H, W):
    """Get learned prior for cell (r,c) based on terrain and neighborhood."""
    terrain = grid[r][c]
    if terrain == 10:
        return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    if terrain == 5:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]

    n_forest = 0
    is_coastal = False
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < H and 0 <= nc < W:
                if grid[nr][nc] == 4:
                    n_forest += 1
                if grid[nr][nc] == 10:
                    is_coastal = True

    n_forest = min(n_forest, 4)

    # Try exact match, then relax features
    for key in [
        f"{terrain}_{n_forest}_{1 if is_coastal else 0}",
        f"{terrain}_{n_forest}_0",
        f"{terrain}_0_{1 if is_coastal else 0}",
    ]:
        if key in _contextual_priors:
            return list(_contextual_priors[key]["dist"])

    return list(_FALLBACK_PRIORS.get(terrain, [1/N_CLASSES] * N_CLASSES))


# ---------------------------------------------------------------------------
# Distance-aware prior
# ---------------------------------------------------------------------------

def compute_settlement_distances(grid, H, W):
    """BFS Chebyshev distance from each cell to nearest initial settlement/port."""
    dist = [[999] * W for _ in range(H)]
    queue = []
    for r in range(H):
        for c in range(W):
            if grid[r][c] in (1, 2):
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
                if 0 <= nr < H and 0 <= nc < W and dist[nr][nc] > dist[r][c] + 1:
                    dist[nr][nc] = dist[r][c] + 1
                    queue.append((nr, nc))
    return dist


def estimate_expansion_rate(obs_counts, grid, dist_map, H, W):
    """Estimate round expansion rate from observations near settlements (dist 1-3)."""
    settle_obs = total_obs = 0
    for r in range(H):
        for c in range(W):
            n = sum(obs_counts[r][c])
            if n == 0 or grid[r][c] in (10, 5, 1, 2):
                continue
            d = dist_map[r][c]
            if 1 <= d <= 3:
                total_obs += n
                settle_obs += obs_counts[r][c][1]
    if total_obs == 0:
        return 0.10, 0
    return settle_obs / total_obs, total_obs


def estimate_dist_decay(grid, obs_counts, dist_map, H, W):
    """Compute per-distance multipliers relative to d1-3 base rate from observations."""
    dist_stats = {}  # d -> [settle_count, total_count]
    for r in range(H):
        for c in range(W):
            n = sum(obs_counts[r][c])
            if n == 0 or grid[r][c] in (10, 5, 1, 2):
                continue
            d = dist_map[r][c]
            if 1 <= d <= 7:
                if d not in dist_stats:
                    dist_stats[d] = [0, 0]
                dist_stats[d][0] += obs_counts[r][c][1]
                dist_stats[d][1] += n

    d13_settle = sum(dist_stats.get(d, [0, 0])[0] for d in [1, 2, 3])
    d13_total  = sum(dist_stats.get(d, [0, 0])[1] for d in [1, 2, 3])
    base_rate = d13_settle / d13_total if d13_total > 0 else 0.10

    multipliers = {}
    for d in range(1, 8):
        if d in dist_stats and dist_stats[d][1] >= 10 and base_rate > 0.001:
            multipliers[d] = (dist_stats[d][0] / dist_stats[d][1]) / base_rate
        else:
            multipliers[d] = DIST_DECAY_DEFAULT.get(d, 0.0)

    return multipliers, base_rate


def estimate_port_ruin_ratios(seed_grids, seed_counts, H, W):
    """Estimate port/settle and ruin/settle ratios from observations."""
    port_obs = ruin_obs = settle_obs = 0
    for s, grid in seed_grids.items():
        counts = seed_counts.get(s)
        if counts is None:
            continue
        for r in range(H):
            for c in range(W):
                n = sum(counts[r][c])
                if n == 0 or grid[r][c] in (10, 5, 1, 2):
                    continue
                # coastal check
                is_coastal = any(
                    0 <= r+dr < H and 0 <= c+dc < W and grid[r+dr][c+dc] == 10
                    for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                    if not (dr == 0 and dc == 0)
                )
                settle_obs += counts[r][c][1]
                ruin_obs   += counts[r][c][3]
                if is_coastal:
                    port_obs += counts[r][c][2]

    port_ratio = port_obs / max(settle_obs, 1) if settle_obs > 10 else 0.35
    ruin_ratio = ruin_obs / max(settle_obs, 1) if settle_obs > 10 else 0.15
    return port_ratio, ruin_ratio


def get_distance_aware_prior(grid, r, c, H, W, dist_map, expansion_rate,
                              dist_multipliers=None, port_ratio=0.35, ruin_ratio=0.15):
    """Prior for cell (r,c) adjusted by distance to nearest settlement + expansion rate."""
    terrain = grid[r][c]
    if terrain == 10:
        return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    if terrain == 5:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]

    prior = get_contextual_prior(grid, r, c, H, W)

    # Existing settlements use their own contextual prior (no distance adjustment)
    if terrain in (1, 2):
        return prior

    dist = dist_map[r][c]
    mults = dist_multipliers or DIST_DECAY_DEFAULT
    if dist <= 7:
        decay = mults.get(dist, DIST_DECAY_DEFAULT.get(dist, 0.0))
    else:
        decay = max(0.02, 0.5 / max(dist, 1)) if dist <= 10 else 0.0

    target_settle = expansion_rate * decay

    # Coastal cells can develop ports
    is_coastal = any(
        0 <= r+dr < H and 0 <= c+dc < W and grid[r+dr][c+dc] == 10
        for dr in (-1, 0, 1) for dc in (-1, 0, 1)
        if not (dr == 0 and dc == 0)
    )
    target_port = target_settle * port_ratio if is_coastal else 0.0
    target_ruin = target_settle * ruin_ratio

    target_dynamic = target_settle + target_port + target_ruin
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


def build_prediction(grid, H, W, dist_map, expansion_rate,
                     dist_multipliers=None, port_ratio=0.35, ruin_ratio=0.15):
    """Build H×W×6 prediction array using distance-aware priors."""
    pred = np.zeros((H, W, N_CLASSES), dtype=np.float32)
    for r in range(H):
        for c in range(W):
            pred[r, c] = get_distance_aware_prior(
                grid, r, c, H, W, dist_map, expansion_rate,
                dist_multipliers=dist_multipliers,
                port_ratio=port_ratio, ruin_ratio=ruin_ratio,
            )
    # Floor + normalize
    pred = np.maximum(pred, 0.002)
    pred = pred / pred.sum(axis=2, keepdims=True)
    return pred


# ---------------------------------------------------------------------------
# Viewport planning
# ---------------------------------------------------------------------------

def find_dynamic_viewports(grid, H, W):
    """Greedy set cover: fewest 15×15 viewports to cover all dynamic cells."""
    dynamic = {(r, c) for r in range(H) for c in range(W) if grid[r][c] in (1, 2, 3)}
    if not dynamic:
        return []

    min_vx, min_vy = 1, 1
    max_vx = max(min_vx, W - VIEWPORT - 1)
    max_vy = max(min_vy, H - VIEWPORT - 1)

    viewports = []
    uncovered = set(dynamic)
    while uncovered:
        candidate_xs = set()
        candidate_ys = set()
        for r, c in uncovered:
            for vx in range(max(min_vx, c - VIEWPORT + 1), min(max_vx + 1, c + 1)):
                candidate_xs.add(vx)
            for vy in range(max(min_vy, r - VIEWPORT + 1), min(max_vy + 1, r + 1)):
                candidate_ys.add(vy)

        best_origin, best_covered = None, set()
        for vx in candidate_xs:
            for vy in candidate_ys:
                covered = {(r, c) for r, c in uncovered
                           if vy <= r < vy + VIEWPORT and vx <= c < vx + VIEWPORT}
                if len(covered) > len(best_covered):
                    best_covered, best_origin = covered, (vx, vy)

        if best_origin is None:
            break
        viewports.append(best_origin)
        uncovered -= best_covered

    return viewports  # list of (vx, vy) — query as vw=15, vh=15


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

def empty_counts(H, W):
    return [[[0] * N_CLASSES for _ in range(W)] for _ in range(H)]


def observe_seed(round_id, seed_index, viewports, H, W):
    """Query API for one seed, return H×W×6 counts."""
    counts = empty_counts(H, W)
    for vx, vy in viewports:
        try:
            result = simulate_viewport(round_id, seed_index, vx, vy, VIEWPORT, VIEWPORT)
            grid = result.get("grid") or []
            budget_used = result.get("queries_used")
            budget_max  = result.get("queries_max")
            budget_remaining = (budget_max - budget_used) if (budget_used is not None and budget_max is not None) else None

            log_query(round_id, seed_index,
                      {"x": vx, "y": vy, "w": VIEWPORT, "h": VIEWPORT},
                      grid, budget_remaining,
                      settlements=result.get("settlements"))

            for ri, row in enumerate(grid):
                for ci, val in enumerate(row):
                    mr, mc = vy + ri, vx + ci
                    if 0 <= mr < H and 0 <= mc < W:
                        cls = TERRAIN_TO_CLASS.get(val, 0)
                        counts[mr][mc][cls] += 1

            print(f"    VP ({vx:2d},{vy:2d}) budget={budget_remaining}")
            time.sleep(RATE_LIMIT_DELAY)
        except Exception as e:
            print(f"    VP ({vx},{vy}) FAILED: {e}")
            log_action(round_id, "query_error",
                       {"seed": seed_index, "vp": [vx, vy], "error": str(e)})
    return counts


def obs_cache_to_counts(cache_seeds, seed_index, H, W):
    """Convert [x,y,cls] cache format to H×W×6 counts array."""
    counts = empty_counts(H, W)
    seed_data = cache_seeds.get(str(seed_index), cache_seeds.get(seed_index, []))
    # Detect format: list of sweeps vs flat list
    if seed_data and isinstance(seed_data[0], list) and seed_data[0] and isinstance(seed_data[0][0], list):
        obs_items = [item for sweep in seed_data for item in sweep]
    else:
        obs_items = seed_data
    for item in obs_items:
        x, y, cls = item[0], item[1], item[2]
        if 0 <= y < H and 0 <= x < W and 0 <= cls < N_CLASSES:
            counts[y][x][cls] += 1
    return counts


# ---------------------------------------------------------------------------
# Surprise-based Phase 2 allocation
# ---------------------------------------------------------------------------

def compute_seed_surprise(grid, counts, H, W):
    """Mean absolute deviation between observations and contextual prior."""
    surprise = 0.0
    n = 0
    for r in range(H):
        for c in range(W):
            n_obs = sum(counts[r][c])
            if n_obs == 0:
                continue
            prior = get_contextual_prior(grid, r, c, H, W)
            for k in range(N_CLASSES):
                surprise += abs(counts[r][c][k] / n_obs - prior[k])
            n += 1
    return surprise / max(n, 1)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Astar Island v4 — distance-aware prior pipeline")
    parser.add_argument("--round-id",      help="Round UUID (auto-detects active)")
    parser.add_argument("--round-data",    help="Load round data (with initial_states) from JSON file")
    parser.add_argument("--save-round-data", help="Save round data to JSON file for future use")
    parser.add_argument("--from-cache",    help="Load observations from JSON file (skip querying)")
    parser.add_argument("--dry-run",       action="store_true", help="Skip submission")
    args = parser.parse_args()

    # --- Load round data ---
    if args.round_data:
        print(f"Loading round data from {args.round_data}...")
        with open(args.round_data) as f:
            round_data = json.load(f)
    elif args.round_id:
        round_data = get_round(args.round_id)
    else:
        active = get_active_round()
        if active is None:
            print("No active round. Pass --round-id or --round-data.")
            return
        round_data = get_round(active["id"])

    round_id  = round_data["id"]
    round_num = round_data.get("round_number", "?")
    map_w     = int(round_data.get("map_width", 40))
    map_h     = int(round_data.get("map_height", 40))
    n_seeds   = round_data.get("seeds_count", len(round_data.get("initial_states", [])))

    print(f"Round {round_num} ({round_id})")
    print(f"Map: {map_w}×{map_h}, {n_seeds} seeds")

    if args.save_round_data:
        with open(args.save_round_data, "w") as f:
            json.dump(round_data, f)
        print(f"Saved round data to {args.save_round_data}")

    log_action(round_id, "start_pipeline_v4", {
        "pipeline": "v4",
        "round_number": round_num,
        "from_cache": args.from_cache,
        "round_data_file": args.round_data,
    }, map_width=map_w, map_height=map_h)

    # Parse per-seed grids
    initial_states = round_data.get("initial_states", [])
    seed_grids = {i: state["grid"] for i, state in enumerate(initial_states) if "grid" in state}
    if not seed_grids:
        print("ERROR: No initial_states in round data. Run without --round-data to fetch from API.")
        return

    # --- Observations ---
    if args.from_cache:
        print(f"\nLoading observations from {args.from_cache}...")
        with open(args.from_cache) as f:
            cache = json.load(f)
        seed_counts = {
            s: obs_cache_to_counts(cache["seeds"], s, map_h, map_w)
            for s in range(n_seeds)
        }
        n_obs_total = sum(
            sum(seed_counts[s][r][c]
                for r in range(map_h) for c in range(map_w)
                for _ in [None])
            for s in range(n_seeds)
        )
        print(f"  Loaded observations for {n_seeds} seeds")
    else:
        print("\nPlanning viewports (set cover)...")
        seed_vps = {}
        for s in range(n_seeds):
            grid = seed_grids[s]
            seed_vps[s] = find_dynamic_viewports(grid, map_h, map_w)
            print(f"  Seed {s}: {len(seed_vps[s])} viewports")

        budget_info = get_budget()
        used = int(budget_info.get("queries_used", 0))
        max_q = int(budget_info.get("queries_max", 50))
        total_budget = max_q - used
        print(f"Budget: {total_budget} remaining ({used}/{max_q})")
        log_action(round_id, "check_budget",
                   {"queries_used": used, "queries_max": max_q, "remaining": total_budget},
                   map_width=map_w, map_height=map_h)

        phase1_total = sum(len(seed_vps[s]) for s in range(n_seeds))
        print(f"Phase 1 needs {phase1_total} queries, budget={total_budget}")

        # Phase 1: cover each seed once
        seed_counts = {}
        budget_spent = 0
        for s in range(n_seeds):
            vps = seed_vps[s]
            to_use = vps[:max(0, total_budget - budget_spent)]
            if not to_use:
                seed_counts[s] = empty_counts(map_h, map_w)
                continue
            print(f"\nSeed {s} Phase 1 ({len(to_use)} queries)...")
            seed_counts[s] = observe_seed(round_id, s, to_use, map_h, map_w)
            budget_spent += len(to_use)

        # Phase 2: remaining budget → highest-surprise seeds
        remaining = total_budget - budget_spent
        if remaining > 0:
            surprises = {
                s: compute_seed_surprise(seed_grids[s], seed_counts[s], map_h, map_w)
                for s in range(n_seeds)
            }
            priority = sorted(range(n_seeds), key=lambda s: surprises[s], reverse=True)
            print(f"\nPhase 2: {remaining} queries, priority={priority} "
                  f"(surprise={[round(surprises[s],3) for s in priority]})")

            while remaining > 0:
                allocated = False
                for s in priority:
                    vps = seed_vps[s]
                    n = min(len(vps), remaining)
                    if n == 0:
                        continue
                    print(f"  Seed {s} Phase 2 ({n} extra queries)...")
                    extra = observe_seed(round_id, s, vps[:n], map_h, map_w)
                    for r in range(map_h):
                        for c in range(map_w):
                            for k in range(N_CLASSES):
                                seed_counts[s][r][c][k] += extra[r][c][k]
                    remaining -= n
                    allocated = True
                    if remaining <= 0:
                        break
                if not allocated:
                    break

    # --- Estimate round parameters from observations ---
    print("\nEstimating expansion rate and distance decay...")

    # Aggregate across seeds for robustness
    agg_dist_stats = {}
    expansion_rates = []

    for s in range(n_seeds):
        grid = seed_grids[s]
        dist_map = compute_settlement_distances(grid, map_h, map_w)
        rate, n_samp = estimate_expansion_rate(seed_counts[s], grid, dist_map, map_h, map_w)
        if n_samp > 0:
            expansion_rates.append((rate, n_samp))

        for r in range(map_h):
            for c in range(map_w):
                n = sum(seed_counts[s][r][c])
                if n == 0 or grid[r][c] in (10, 5, 1, 2):
                    continue
                d = dist_map[r][c]
                if 1 <= d <= 7:
                    if d not in agg_dist_stats:
                        agg_dist_stats[d] = [0, 0]
                    agg_dist_stats[d][0] += seed_counts[s][r][c][1]
                    agg_dist_stats[d][1] += n

    if expansion_rates:
        total_samp = sum(n for _, n in expansion_rates)
        avg_expansion = sum(r * n for r, n in expansion_rates) / total_samp
    else:
        avg_expansion = 0.10

    d13_settle = sum(agg_dist_stats.get(d, [0, 0])[0] for d in [1, 2, 3])
    d13_total  = sum(agg_dist_stats.get(d, [0, 0])[1] for d in [1, 2, 3])
    base_rate = d13_settle / d13_total if d13_total > 0 else avg_expansion

    dist_multipliers = {}
    for d in range(1, 8):
        if d in agg_dist_stats and agg_dist_stats[d][1] >= 10 and base_rate > 0.001:
            dist_multipliers[d] = (agg_dist_stats[d][0] / agg_dist_stats[d][1]) / base_rate
        else:
            dist_multipliers[d] = DIST_DECAY_DEFAULT.get(d, 0.0)

    port_ratio, ruin_ratio = estimate_port_ruin_ratios(seed_grids, seed_counts, map_h, map_w)

    print(f"  Expansion rate: {avg_expansion:.4f} (from {sum(n for _,n in expansion_rates)} obs)")
    print(f"  Dist multipliers: " + " ".join(f"d{d}={dist_multipliers.get(d,0):.2f}" for d in range(1, 8)))
    print(f"  Port ratio: {port_ratio:.3f}, Ruin ratio: {ruin_ratio:.3f}")

    log_action(round_id, "expansion_estimate_v4", {
        "expansion_rate": round(avg_expansion, 4),
        "dist_multipliers": {str(k): round(v, 3) for k, v in dist_multipliers.items()},
        "port_ratio": round(port_ratio, 3),
        "ruin_ratio": round(ruin_ratio, 3),
    }, map_width=map_w, map_height=map_h)

    # --- Build and submit predictions ---
    class_names = ["Empty", "Settle", "Port", "Ruin", "Forest", "Mountain"]

    for seed_index in range(n_seeds):
        print(f"\n--- Seed {seed_index} ---")
        grid = seed_grids[seed_index]
        dist_map = compute_settlement_distances(grid, map_h, map_w)

        pred = build_prediction(
            grid, map_h, map_w, dist_map, avg_expansion,
            dist_multipliers=dist_multipliers,
            port_ratio=port_ratio, ruin_ratio=ruin_ratio,
        )

        argmax = pred.argmax(axis=2)
        parts = [f"{class_names[c]}={(argmax==c).sum()}" for c in range(6) if (argmax==c).sum() > 0]
        print(f"  Classes: {', '.join(parts)}")
        print(f"  Settle+Port prob range: "
              f"{(pred[:,:,1]+pred[:,:,2]).min():.3f} – {(pred[:,:,1]+pred[:,:,2]).max():.3f}")

        log_prediction(round_id, seed_index, pred, map_width=map_w, map_height=map_h)

        if not args.dry_run:
            try:
                result = submit_prediction(round_id, seed_index, pred)
                print(f"  Submitted: {result}")
                log_submission(round_id, seed_index, result, map_width=map_w, map_height=map_h)
            except Exception as e:
                print(f"  Submit ERROR: {e}")
                log_action(round_id, "submit_error",
                           {"seed_index": seed_index, "error": str(e)},
                           map_width=map_w, map_height=map_h)
            time.sleep(0.6)
        else:
            print("  [dry-run] Skipped.")

    log_action(round_id, "pipeline_v4_complete", {"dry_run": args.dry_run},
               map_width=map_w, map_height=map_h)
    print("\nDone!")


if __name__ == "__main__":
    main()
