PARAMS = { # 0.01 - 0.99 (1%-99%)
    "GROWTH": {
        "EXPANSION_RATE": 0.01,
        "EXPANSION_RANGE": 0.01,
        "PORT_DEVELOPMENT_CHANCE": 0.01,
        "LONGSHIP_BUILD_CHANCE": 0.01,
    },
    "CONFLICT": {
        "RAID_CHANCE": 0.01,
        "CONQUEST_CHANCE": 0.01,
        "LONGSHIP_RAID_RANGE": 0.01,
    },
    "TRADE": {
        "TRADE_RANGE": 0.01,
    },
    "WINTER": {
        "WINTER_HARSHNESS": 0.01,
        "COLLAPSE_CHANCE": 0.01,
    },
    "ENVIRONMENT": {
        "RUIN_TO_SETTLEMENT_RECLAIM_RATE": 0.01,
        "RUIN_TO_PORT_RECLAIM_RATE": 0.01,
        "FOREST_OVERTAKE_RATE": 0.01,
    },
}

COLD_VS_WARM_LIKELY = 0.5

MAP_W = 40
MAP_H = 40
VIEWPORT = 15

def tile_positions(map_size, vp_size):
    """Evenly space viewport origins to cover the interior with uniform overlap."""
    n_tiles = -(-map_size // vp_size)  # ceil division
    if n_tiles <= 1:
        return [0]
    step = (map_size - vp_size) / (n_tiles - 1)
    return sorted(set(int(i * step + 0.5) for i in range(n_tiles)))

def define_query_cells(map_w=MAP_W, map_h=MAP_H):
    """Build full-coverage tiling that skips the 1-cell ocean border."""
    interior_w = map_w - 2  # skip col 0 and col map_w-1
    interior_h = map_h - 2  # skip row 0 and row map_h-1
    xs = [x + 1 for x in tile_positions(interior_w, VIEWPORT)]
    ys = [y + 1 for y in tile_positions(interior_h, VIEWPORT)]
    return [(x, y) for y in ys for x in xs]


N_SEEDS = 5
N_CLASSES = 6

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
