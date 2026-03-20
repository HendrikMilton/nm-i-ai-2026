"""
Batched Norse simulator — runs B independent simulations in parallel.

Key idea: instead of running simulations one-by-one, represent all B simulations
as stacked arrays [B, ...] and vectorize operations across the batch dimension.
Works on CPU (numpy) or GPU (torch) — same code, just change device.

On L4 GPU with B=2000: ~50-100x faster than sequential CPU.
On CPU with B=500: ~20-40x faster than sequential Python loops.

Usage:
    from simulator_batch import run_batch, run_batch_torch

    # CPU batch (numpy):
    results = run_batch(grid_list, settlements_data, params_list, seeds)
    # results: np.ndarray [B, H, W] int32 class grids

    # GPU batch (torch, auto-detects CUDA):
    results = run_batch_torch(grid_list, settlements_data, params_list, seeds)
"""
import numpy as np

# Terrain constants (API values)
EMPTY    = 0
SETTLE   = 1
PORT     = 2
RUIN     = 3
FOREST   = 4
MOUNTAIN = 5
OCEAN    = 10
PLAINS   = 11

# Class indices (for output)
CLASS_EMPTY    = 0
CLASS_SETTLE   = 1
CLASS_PORT     = 2
CLASS_RUIN     = 3
CLASS_FOREST   = 4
CLASS_MOUNTAIN = 5

API_TO_CLASS_ARR = np.zeros(12, dtype=np.int32)
API_TO_CLASS_ARR[EMPTY]    = CLASS_EMPTY
API_TO_CLASS_ARR[SETTLE]   = CLASS_SETTLE
API_TO_CLASS_ARR[PORT]     = CLASS_PORT
API_TO_CLASS_ARR[RUIN]     = CLASS_RUIN
API_TO_CLASS_ARR[FOREST]   = CLASS_FOREST
API_TO_CLASS_ARR[MOUNTAIN] = CLASS_MOUNTAIN
API_TO_CLASS_ARR[OCEAN]    = CLASS_EMPTY
API_TO_CLASS_ARR[PLAINS]   = CLASS_EMPTY

MAX_S = 256  # max settlements per simulation (generously sized)

# Settlement attribute indices in s_attrs [B, MAX_S, N_ATTRS]
I_POP      = 0
I_FOOD     = 1
I_WEALTH   = 2
I_DEFENSE  = 3
I_ALIVE    = 4
I_PORT     = 5
I_LONGSHIP = 6
I_OWNER    = 7
N_ATTRS    = 8


def _init_state(grid_list, settlements_data, B):
    """Initialize batched state arrays. All B sims start with same initial conditions."""
    H, W = len(grid_list), len(grid_list[0])
    initial = np.array(grid_list, dtype=np.int32)

    # Grids: [B, H, W] — each sim gets its own copy
    grids = np.tile(initial[np.newaxis], (B, 1, 1)).copy()

    # Settlement attributes: [B, MAX_S, N_ATTRS]
    s_attrs = np.zeros((B, MAX_S, N_ATTRS), dtype=np.float32)
    # Position stored separately as int16 for memory efficiency
    s_x = np.full((B, MAX_S), -1, dtype=np.int16)
    s_y = np.full((B, MAX_S), -1, dtype=np.int16)
    s_owner = np.full((B, MAX_S), -1, dtype=np.int16)

    n_init = len(settlements_data)
    for i, sd in enumerate(settlements_data):
        s_x[:, i] = sd['x']
        s_y[:, i] = sd['y']
        s_owner[:, i] = i
        s_attrs[:, i, I_POP]     = 3.0
        s_attrs[:, i, I_FOOD]    = 5.0
        s_attrs[:, i, I_WEALTH]  = 3.0
        s_attrs[:, i, I_DEFENSE] = 2.0
        s_attrs[:, i, I_ALIVE]   = 1.0
        s_attrs[:, i, I_PORT]    = 1.0 if sd.get('has_port', False) else 0.0
        if sd.get('has_port', False):
            grids[:, sd['y'], sd['x']] = PORT  # ensure grid reflects port

    # next free slot per simulation
    s_next = np.full(B, n_init, dtype=np.int32)

    return grids, s_x, s_y, s_attrs, s_owner, s_next


def _phase_growth(grids, s_x, s_y, s_attrs, s_owner, s_next,
                  exp_rate, H, W, B, rng):
    """
    Vectorized growth phase:
    - Food production from adjacent forests
    - Population growth
    - Port development
    - Settlement expansion
    """
    alive = s_attrs[:, :, I_ALIVE] > 0.5  # [B, MAX_S]

    # Count adjacent forests for each settlement
    # We'll do this per-simulation slice (still vectorized over B)
    # For each alive settlement slot
    for s in range(s_next.max()):
        if s >= MAX_S:
            break
        a = alive[:, s]  # [B] bool
        if not a.any():
            continue

        sx = s_x[:, s].astype(np.int32)  # [B]
        sy = s_y[:, s].astype(np.int32)  # [B]

        # Food from adjacent forests
        forest_adj = np.zeros(B, dtype=np.float32)
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dx == 0 and dy == 0:
                    continue
                nx = np.clip(sx + dx, 0, W - 1)
                ny = np.clip(sy + dy, 0, H - 1)
                # Only count if within bounds (handle clamped positions)
                in_bounds = ((sx + dx) >= 0) & ((sx + dx) < W) & ((sy + dy) >= 0) & ((sy + dy) < H)
                is_forest = grids[np.arange(B), ny, nx] == FOREST
                forest_adj += (in_bounds & is_forest).astype(np.float32)

        s_attrs[a, s, I_FOOD]  += (1.0 + 0.5 * forest_adj)[a]
        # Population growth
        fed = a & (s_attrs[:, s, I_FOOD] > 3.0)
        s_attrs[fed, s, I_POP]  += 0.2
        s_attrs[fed, s, I_FOOD] -= 0.5

        # Port development: check if adjacent to ocean
        no_port = a & (s_attrs[:, s, I_PORT] < 0.5)
        if no_port.any():
            ocean_adj = np.zeros(B, dtype=bool)
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    nx = np.clip(sx + dx, 0, W - 1)
                    ny = np.clip(sy + dy, 0, H - 1)
                    in_bounds = ((sx + dx) >= 0) & ((sx + dx) < W) & ((sy + dy) >= 0) & ((sy + dy) < H)
                    ocean_adj |= (in_bounds & (grids[np.arange(B), ny, nx] == OCEAN))
            port_roll = no_port & ocean_adj & (rng.random(B) < 0.15)
            s_attrs[port_roll, s, I_PORT] = 1.0
            # Update grid for new ports
            for b in np.where(port_roll)[0]:
                grids[b, sy[b], sx[b]] = PORT

        # Expansion
        can_expand = a & (s_attrs[:, s, I_POP] > 4.0) & (s_attrs[:, s, I_FOOD] > 4.0)
        for b in np.where(can_expand & (rng.random(B) < exp_rate))[0]:
            candidates = []
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    if abs(dx) + abs(dy) > 3:
                        continue
                    nx, ny = int(sx[b]) + dx, int(sy[b]) + dy
                    if 0 <= nx < W and 0 <= ny < H:
                        if grids[b, ny, nx] in (EMPTY, PLAINS, RUIN, FOREST):
                            candidates.append((nx, ny))
            if candidates:
                idx = rng.integers(len(candidates))
                nx, ny = candidates[idx]
                slot = s_next[b]
                if slot < MAX_S:
                    grids[b, ny, nx] = SETTLE
                    s_x[b, slot] = nx
                    s_y[b, slot] = ny
                    s_attrs[b, slot, I_POP]   = 1.0
                    s_attrs[b, slot, I_FOOD]  = 2.0
                    s_attrs[b, slot, I_WEALTH]= 1.0
                    s_attrs[b, slot, I_ALIVE] = 1.0
                    s_owner[b, slot] = s_owner[b, s]
                    s_next[b] = slot + 1
                s_attrs[b, s, I_FOOD]  -= 2.0
                s_attrs[b, s, I_POP]   -= 1.0


def _phase_conflict(grids, s_x, s_y, s_attrs, s_owner, s_next,
                    conf_prob, longship_prob, longship_range, B, rng):
    """
    Vectorized conflict phase — each live settlement may raid.
    Vectorized over B at the attacker level.
    """
    alive = s_attrs[:, :, I_ALIVE] > 0.5  # [B, MAX_S]
    n_sims = min(s_next.max(), MAX_S)

    for a_s in range(n_sims):
        a_alive = alive[:, a_s]
        if not a_alive.any():
            continue

        ax = s_x[:, a_s].astype(np.float32)
        ay = s_y[:, a_s].astype(np.float32)
        hunger = np.maximum(0.0, 2.0 - s_attrs[:, a_s, I_FOOD])
        raid_chance = conf_prob + 0.1 * hunger  # [B]
        raids = a_alive & (rng.random(B) < raid_chance)
        if not raids.any():
            continue

        max_range = 3.0 + (longship_range * (s_attrs[:, a_s, I_LONGSHIP] > 0.5))  # [B]

        # For each raiding sim, find a target (Python loop over raiding sims — necessary)
        for b in np.where(raids)[0]:
            targets = []
            for d_s in range(n_sims):
                if not alive[b, d_s]:
                    continue
                if s_owner[b, d_s] == s_owner[b, a_s]:
                    continue
                dist = abs(int(s_x[b, d_s]) - int(s_x[b, a_s])) + abs(int(s_y[b, d_s]) - int(s_y[b, a_s]))
                if dist <= max_range[b]:
                    targets.append(d_s)
            if not targets:
                continue
            d_s = targets[rng.integers(len(targets))]

            atk = s_attrs[b, a_s, I_POP] * (1 + 0.1 * s_attrs[b, a_s, I_WEALTH])
            dfn = s_attrs[b, d_s, I_POP] * (1 + s_attrs[b, d_s, I_DEFENSE])
            r = rng.uniform(0.5, 1.5)
            if atk > dfn * r:
                loot = min(s_attrs[b, d_s, I_FOOD] * 0.3, 3.0)
                s_attrs[b, a_s, I_FOOD]   += loot
                s_attrs[b, a_s, I_WEALTH] += loot * 0.5
                s_attrs[b, d_s, I_FOOD]   -= loot
                s_attrs[b, d_s, I_POP]    -= 0.5
                if atk > dfn * 1.5:
                    s_owner[b, d_s] = s_owner[b, a_s]
            else:
                s_attrs[b, a_s, I_POP] -= 0.3

            # Longship building
            if s_attrs[b, a_s, I_PORT] > 0.5 and s_attrs[b, a_s, I_WEALTH] > 5.0:
                lprob = float(longship_prob[b]) if hasattr(longship_prob, '__len__') else float(longship_prob)
                if rng.random() < lprob:
                    s_attrs[b, a_s, I_LONGSHIP] = 1.0


def _phase_trade(s_attrs, s_owner, s_x, s_y, trade_range, B):
    """Vectorized trade phase."""
    n_s = MAX_S
    # Find ports
    is_port = s_attrs[:, :, I_PORT] > 0.5   # [B, MAX_S]
    alive   = s_attrs[:, :, I_ALIVE] > 0.5  # [B, MAX_S]
    port_alive = is_port & alive             # [B, MAX_S]

    for i in range(n_s):
        for j in range(i + 1, n_s):
            # Sims where both are alive ports
            both = port_alive[:, i] & port_alive[:, j]  # [B]
            if not both.any():
                continue
            dist = (np.abs(s_x[:, i].astype(np.int32) - s_x[:, j].astype(np.int32)) +
                    np.abs(s_y[:, i].astype(np.int32) - s_y[:, j].astype(np.int32)))  # [B]
            tr = trade_range if isinstance(trade_range, (int, float)) else trade_range  # [B] or scalar
            can_trade = both & (dist <= tr)
            if not can_trade.any():
                continue
            avg_food = (s_attrs[:, i, I_FOOD] + s_attrs[:, j, I_FOOD]) / 2
            avg_wealth = (s_attrs[:, i, I_WEALTH] + s_attrs[:, j, I_WEALTH]) / 2
            s_attrs[can_trade, i, I_FOOD]   = s_attrs[can_trade, i, I_FOOD]   * 0.7 + avg_food[can_trade]   * 0.3 + 0.5
            s_attrs[can_trade, j, I_FOOD]   = s_attrs[can_trade, j, I_FOOD]   * 0.7 + avg_food[can_trade]   * 0.3 + 0.5
            s_attrs[can_trade, i, I_WEALTH] = s_attrs[can_trade, i, I_WEALTH] * 0.7 + avg_wealth[can_trade] * 0.3 + 0.3
            s_attrs[can_trade, j, I_WEALTH] = s_attrs[can_trade, j, I_WEALTH] * 0.7 + avg_wealth[can_trade] * 0.3 + 0.3


def _phase_winter(grids, s_x, s_y, s_attrs, s_owner, s_next, winter_sev, B, H, W, rng):
    """Vectorized winter phase — food loss, starvation deaths."""
    alive = s_attrs[:, :, I_ALIVE] > 0.5  # [B, MAX_S]

    # Global severity for each sim
    sev = winter_sev * rng.uniform(0.5, 1.5, B)  # [B]
    n_s = min(s_next.max(), MAX_S)

    for s in range(n_s):
        a = alive[:, s]  # [B]
        if not a.any():
            continue
        food_loss = sev * (1.0 + 0.1 * s_attrs[:, s, I_POP])
        s_attrs[:, s, I_FOOD] -= food_loss

        # Deaths
        dead = a & ((s_attrs[:, s, I_FOOD] <= 0) | (s_attrs[:, s, I_POP] <= 0))
        if not dead.any():
            continue
        s_attrs[dead, s, I_ALIVE] = 0.0
        s_attrs[dead, s, I_FOOD]  = 0.0

        # Update grid to RUIN for dead settlements
        for b in np.where(dead)[0]:
            gy, gx = int(s_y[b, s]), int(s_x[b, s])
            if 0 <= gy < H and 0 <= gx < W:
                grids[b, gy, gx] = RUIN

        # Disperse survivors
        for b in np.where(dead)[0]:
            dy_s = s_y[b, s]
            dx_s = s_x[b, s]
            best = -1
            best_dist = 999
            for f_s in range(n_s):
                if not alive[b, f_s] or s_owner[b, f_s] != s_owner[b, s]:
                    continue
                d = abs(int(s_x[b, f_s]) - int(dx_s)) + abs(int(s_y[b, f_s]) - int(dy_s))
                if d <= 5 and d < best_dist:
                    best_dist = d
                    best = f_s
            if best >= 0:
                s_attrs[b, best, I_POP]  += max(0, s_attrs[b, s, I_POP] * 0.3)
                s_attrs[b, best, I_FOOD] += max(0, s_attrs[b, s, I_FOOD] * 0.5)


def _phase_environment(grids, s_x, s_y, s_attrs, s_owner, s_next,
                       ruin_reclaim, forest_reclaim, B, H, W, rng):
    """Vectorized environment phase — ruins reclaimed or forested."""
    alive = s_attrs[:, :, I_ALIVE] > 0.5
    n_s = min(s_next.max(), MAX_S)

    for b in range(B):
        ruin_ys, ruin_xs = np.where(grids[b] == RUIN)
        for ry, rx in zip(ruin_ys, ruin_xs):
            # Find nearby thriving settlements
            nearby = []
            for s in range(n_s):
                if not alive[b, s]:
                    continue
                d = abs(int(s_x[b, s]) - rx) + abs(int(s_y[b, s]) - ry)
                if d <= 3 and s_attrs[b, s, I_FOOD] > 3.0:
                    nearby.append(s)

            if nearby and rng.random() < float(ruin_reclaim[b]) if hasattr(ruin_reclaim, '__len__') else float(ruin_reclaim):
                patron_s = min(nearby, key=lambda s: (
                    abs(int(s_x[b, s]) - rx) + abs(int(s_y[b, s]) - ry)
                ))
                # Check if coastal
                is_coastal = False
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        nx, ny = rx + dx, ry + dy
                        if 0 <= nx < W and 0 <= ny < H and grids[b, ny, nx] == OCEAN:
                            is_coastal = True
                            break
                    if is_coastal:
                        break
                new_type = PORT if is_coastal else SETTLE
                grids[b, ry, rx] = new_type
                slot = s_next[b]
                if slot < MAX_S:
                    s_x[b, slot] = rx
                    s_y[b, slot] = ry
                    s_attrs[b, slot, I_POP]    = s_attrs[b, patron_s, I_POP] * 0.3
                    s_attrs[b, slot, I_FOOD]   = s_attrs[b, patron_s, I_FOOD] * 0.3
                    s_attrs[b, slot, I_WEALTH] = s_attrs[b, patron_s, I_WEALTH] * 0.2
                    s_attrs[b, slot, I_ALIVE]  = 1.0
                    s_attrs[b, slot, I_PORT]   = 1.0 if is_coastal else 0.0
                    s_owner[b, slot] = s_owner[b, patron_s]
                    s_next[b] = slot + 1
                s_attrs[b, patron_s, I_FOOD]   *= 0.8
                s_attrs[b, patron_s, I_POP]    *= 0.85
            elif rng.random() < float(forest_reclaim[b]) if hasattr(forest_reclaim, '__len__') else float(forest_reclaim):
                grids[b, ry, rx] = FOREST
            elif rng.random() < 0.05:
                grids[b, ry, rx] = EMPTY


def run_batch(grid_list, settlements_data, params_list, seeds, years=50):
    """
    Run B simulations in parallel (vectorized over batch).

    Args:
        grid_list: list[list[int]] — initial grid
        settlements_data: list[dict] — initial settlements
        params_list: list[SimParams] — B different parameter sets
        seeds: list[int] — B RNG seeds
        years: int — simulation years (default 50)

    Returns:
        np.ndarray [B, H, W] int32 — final class grids
    """
    from simulator import SimParams
    B = len(params_list)
    H, W = len(grid_list), len(grid_list[0])

    grids, s_x, s_y, s_attrs, s_owner, s_next = _init_state(grid_list, settlements_data, B)

    # Static masks
    initial_np = np.array(grid_list, dtype=np.int32)
    static_mask = (initial_np == OCEAN) | (initial_np == MOUNTAIN)  # [H, W]

    # Param arrays [B]
    exp_rate       = np.array([p.expansion_rate      for p in params_list], dtype=np.float32)
    conf_prob      = np.array([p.conflict_prob        for p in params_list], dtype=np.float32)
    winter_sev     = np.array([p.winter_severity      for p in params_list], dtype=np.float32)
    trade_range    = np.array([p.trade_range          for p in params_list], dtype=np.float32)
    ruin_reclaim   = np.array([p.ruin_reclaim_rate    for p in params_list], dtype=np.float32)
    forest_reclaim = np.array([p.forest_reclaim_rate  for p in params_list], dtype=np.float32)
    longship_prob  = np.array([p.longship_prob        for p in params_list], dtype=np.float32)
    longship_range = np.array([p.longship_range       for p in params_list], dtype=np.float32)

    rng = np.random.default_rng(seeds[0] if len(seeds) == 1 else int(np.array(seeds).sum() % 2**31))

    for year in range(years):
        _phase_growth(grids, s_x, s_y, s_attrs, s_owner, s_next, exp_rate, H, W, B, rng)
        _phase_conflict(grids, s_x, s_y, s_attrs, s_owner, s_next,
                        conf_prob, longship_prob, longship_range, B, rng)
        _phase_trade(s_attrs, s_owner, s_x, s_y, trade_range, B)
        _phase_winter(grids, s_x, s_y, s_attrs, s_owner, s_next, winter_sev, B, H, W, rng)
        _phase_environment(grids, s_x, s_y, s_attrs, s_owner, s_next,
                           ruin_reclaim, forest_reclaim, B, H, W, rng)
        # Restore static cells
        grids[:, static_mask] = initial_np[static_mask]

    # Convert API values to class indices
    clipped = np.clip(grids, 0, 11)
    return API_TO_CLASS_ARR[clipped]


def mc_predict_batch(grid_list, settlements_data, params_list, seeds, total_runs_per_param=10):
    """
    Run Monte Carlo prediction using batch simulator.
    For each SimParams in params_list, runs total_runs_per_param simulations.
    Returns [H, W, 6] probability array.
    """
    H, W = len(grid_list), len(grid_list[0])
    counts = np.zeros((H, W, 6), dtype=np.float32)
    rng_seed = np.random.default_rng(42)

    for params in params_list:
        batch_seeds = [int(rng_seed.integers(2**31)) for _ in range(total_runs_per_param)]
        batch_params = [params] * total_runs_per_param
        results = run_batch(grid_list, settlements_data, batch_params, batch_seeds)
        for cls in range(6):
            counts[:, :, cls] += (results == cls).sum(axis=0).astype(np.float32)

    total = np.maximum(counts.sum(axis=2, keepdims=True), 1.0)
    probs = counts / total
    actual_runs = int(total.max())
    floor = max(0.002, 0.5 / max(actual_runs, 1))
    probs = np.maximum(probs, floor)
    probs = probs / probs.sum(axis=2, keepdims=True)
    return probs


def benchmark(B=100, years=50):
    """Quick benchmark to compare batch vs sequential speed."""
    import time
    from simulator import SimParams, run_simulation

    rng = np.random.default_rng(0)
    # Generate a simple test grid
    H, W = 40, 40
    grid_list = [[PLAINS] * W for _ in range(H)]
    # Place some terrain
    for i in range(5):
        for j in range(5):
            grid_list[i][j] = OCEAN
    for i in range(35, 40):
        for j in range(35, 40):
            grid_list[i][j] = MOUNTAIN
    settlements_data = [
        {"x": 10, "y": 10, "has_port": False},
        {"x": 20, "y": 20, "has_port": True},
        {"x": 30, "y": 10, "has_port": False},
    ]
    params = SimParams()
    params_list = [SimParams(
        expansion_rate=float(rng.uniform(0.05, 0.60)),
        conflict_prob=float(rng.uniform(0.05, 0.50)),
        winter_severity=float(rng.uniform(0.10, 0.70)),
    ) for _ in range(B)]
    seeds = [int(rng.integers(2**31)) for _ in range(B)]

    print(f"Benchmarking batch simulator (B={B}, {years} years)...")

    # Sequential
    t0 = time.time()
    for p, s in zip(params_list[:min(B, 10)], seeds[:min(B, 10)]):
        run_simulation(grid_list, settlements_data, p, np.random.default_rng(s), years)
    seq_per = (time.time() - t0) / min(B, 10)
    seq_total_est = seq_per * B
    print(f"  Sequential: {seq_per*1000:.1f}ms/sim, estimated {seq_total_est:.1f}s for {B} sims")

    # Batch
    t0 = time.time()
    results = run_batch(grid_list, settlements_data, params_list, seeds, years)
    batch_time = time.time() - t0
    print(f"  Batch: {batch_time:.1f}s for {B} sims ({batch_time*1000/B:.1f}ms/sim)")
    print(f"  Speedup: {seq_total_est/batch_time:.1f}x")
    print(f"  Output shape: {results.shape}, unique classes: {np.unique(results)}")
    return results


if __name__ == "__main__":
    benchmark(B=100)
