# Query Strategy Improvements

## Current Strategy (v3)

- Fixed 15x15 grid tiling → filter to viewports containing dynamic cells
- Hard cutoff: cells with < 3 observations → pure prior, observations discarded
- Budget split evenly across observed seeds; unobserved seeds get 0 queries
- No adaptive reallocation mid-run

---

## Improvement 1: Optimal Viewport Placement (Set Cover)

### Problem
`build_tiling()` generates a fixed grid: positions 0, 15, 25 for a 40-wide map. If all settlements cluster in a 20x20 area, the grid produces 4-6 viewports when 2 well-placed ones could cover everything. Fewer viewports per seed = more repeats or more seeds observed.

### What to change

Replace `find_dynamic_viewports()` (lines 243-260) with a greedy set-cover approach:

```python
def find_optimal_viewports(initial_grid, map_w, map_h):
    """Place fewest 15x15 viewports to cover all dynamic cells."""
    # 1. Collect all dynamic cell positions
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
        # 2. Try all valid viewport origins, pick the one covering the most uncovered cells
        best_origin = None
        best_covered = set()

        # Candidate origins: any position where the viewport could cover an uncovered cell
        # Viewport at (vx, vy) covers rows [vy, vy+15) and cols [vx, vx+15)
        candidate_xs = set()
        candidate_ys = set()
        for r, c in uncovered:
            # Viewport origin ranges that would include this cell
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
```

### Impact
On a typical map with ~30 dynamic cells clustered in 2-3 regions, this could reduce viewports from 6-9 down to 3-5. With 50 queries / 5 viewports = 10 queries/seed, you can observe all 5 seeds at 2 repeats each, vs the current strategy of observing 1-2 seeds at 3+ repeats.

---

## Improvement 2: Soft Blending Curve (Remove Hard Cutoff)

### Problem
`counts_to_prediction_v3()` (lines 310-332) has a binary cutoff at `MIN_OBS_TO_BLEND = 3`: cells with 1-2 observations get **zero value** from those queries. This wastes budget and forces the "concentrate all queries on few seeds" strategy.

### What to change

Replace the hard cutoff with a continuous prior weight that decreases as observations increase:

```python
def counts_to_prediction_v4(counts, initial_grid, map_w, map_h):
    """Blend observations with priors using adaptive weighting.

    prior_weight scales inversely with observation count:
      0 obs → pure prior
      1 obs → prior_weight=8.0  (prior dominates, obs nudges)
      2 obs → prior_weight=5.0
      3 obs → prior_weight=3.0
      5 obs → prior_weight=2.0
      10 obs → prior_weight=1.5
    """
    prediction = [[[0.0] * N_CLASSES for _ in range(map_w)] for _ in range(map_h)]

    for r in range(map_h):
        for c in range(map_w):
            prior = get_contextual_prior(initial_grid, r, c, map_h, map_w)
            obs_total = sum(counts[r][c])

            if obs_total == 0:
                prediction[r][c] = prior
            else:
                # Decaying prior weight: high when few obs, low when many
                # pw = base / (1 + obs/scale)  →  pw(1)=8, pw(3)=3, pw(10)=1.5
                prior_weight = 12.0 / (1.0 + obs_total / 1.5)
                blended = [0.0] * N_CLASSES
                for k in range(N_CLASSES):
                    blended[k] = (counts[r][c][k] + prior_weight * prior[k]) / (obs_total + prior_weight)
                prediction[r][c] = blended

    return prediction
```

### Impact
Every query now adds value. Even 1 observation per cell nudges the prediction slightly toward reality. Combined with optimal viewport placement, this enables the "observe all 5 seeds" strategy: 50 queries / 5 seeds / 4 viewports = 2-3 observations per cell per seed, all contributing signal.

### Key tradeoff
The `12.0 / (1 + obs/1.5)` formula should be validated via offline backtesting. The curve needs to:
- Be conservative at 1 obs (prior weight ~8 → obs is only 11% of the blend)
- Match current behavior around 3 obs (prior weight ~3 → 50/50)
- Let observations dominate at 5+ obs (prior weight ~2 → obs is 71%)

---

## Improvement 3: Observe All Seeds, Concentrate on Hardest

### Problem
Current strategy picks `observed_seeds = min(5, budget // (n_dynamic * 3))`. With 9 dynamic viewports, that's `50 // 27 = 1` seed observed. 4 seeds get zero queries.

### What to change

With improvements 1+2 (fewer viewports + soft blending), switch to: every seed gets at least 1 pass through its viewports, then remaining budget goes to the seeds with highest uncertainty.

Replace the budget allocation block (lines 412-432):

```python
if max_dynamic == 0:
    seed_viewports = {s: [] for s in range(N_SEEDS)}
else:
    # Phase 1: every seed gets 1 pass through its viewports
    seed_viewports = {}
    budget_used = 0
    for s in range(N_SEEDS):
        dvps = seed_dynamic_vps[s]
        seed_viewports[s] = list(dvps)  # 1 pass each
        budget_used += len(dvps)

    # Phase 2: remaining budget → extra passes on seeds with most dynamic cells
    remaining = total_budget - budget_used
    if remaining > 0:
        # Rank seeds by number of dynamic viewports (more dynamic = more uncertain)
        seed_priority = sorted(range(N_SEEDS),
                               key=lambda s: len(seed_dynamic_vps[s]),
                               reverse=True)

        # Round-robin extra passes to priority seeds
        while remaining > 0:
            for s in seed_priority:
                dvps = seed_dynamic_vps[s]
                if not dvps:
                    continue
                # Add one more pass through this seed's viewports
                can_add = min(len(dvps), remaining)
                seed_viewports[s].extend(dvps[:can_add])
                remaining -= can_add
                if remaining <= 0:
                    break
```

### Impact
Instead of 1 seed at 5 repeats + 4 seeds at 0, you get something like: all 5 seeds at 1-2 repeats, with the hardest seed getting 3. Combined with the soft blending curve, every seed now gets useful observations.

---

## Improvement 4: Adaptive Mid-Run Reallocation

### Problem
Budget plan is fixed before any queries run. If a seed's observations closely match the prior, those extra repeats are wasted — the prior was already good enough.

### What to change

Split execution into 2 phases in `main()`:

```python
# Phase 1: 1 pass per seed (observe everything once)
for seed_idx in range(N_SEEDS):
    dvps = seed_dynamic_vps[seed_idx]
    seed_counts[seed_idx] = observe_seed(round_id, seed_idx, dvps, map_w, map_h)
    budget_spent += len(dvps)

# Phase 2: compute per-seed "surprise" and allocate remaining budget
remaining = total_budget - budget_spent
if remaining > 0:
    seed_surprise = {}
    for s in range(N_SEEDS):
        # Compare observed distribution to prior for each dynamic cell
        grid = seed_grids.get(s, initial_grid)
        surprise = 0.0
        n_cells = 0
        for r in range(map_h):
            for c in range(map_w):
                obs_total = sum(seed_counts[s][r][c])
                if obs_total == 0:
                    continue
                prior = get_contextual_prior(grid, r, c, map_h, map_w)
                # Simple surprise metric: how far is observation from prior?
                for k in range(N_CLASSES):
                    obs_frac = seed_counts[s][r][c][k] / obs_total
                    surprise += abs(obs_frac - prior[k])
                n_cells += 1
        seed_surprise[s] = surprise / max(n_cells, 1)

    # Seeds where observations diverge most from priors need more data
    priority = sorted(range(N_SEEDS), key=lambda s: seed_surprise.get(s, 0), reverse=True)

    while remaining > 0:
        for s in priority:
            dvps = seed_dynamic_vps[s]
            if not dvps:
                continue
            can_add = min(len(dvps), remaining)
            extra_counts = observe_seed(round_id, s, dvps[:can_add], map_w, map_h)
            merge_counts(seed_counts[s], extra_counts, map_w, map_h)
            remaining -= can_add
            if remaining <= 0:
                break
```

### Impact
Seeds where the prior is already accurate get fewer wasted repeat queries. Seeds where the prior is wrong (the ones that actually hurt your score) get the extra observations they need. This is especially valuable for R3-type rounds where the prior is weak.

---

## Summary: Combined Effect

| Change | Queries saved/gained | Score impact |
|--------|---------------------|--------------|
| Optimal viewport placement | 2-4 fewer viewports per seed | Enables observing all seeds |
| Soft blending curve | Every query adds value (no waste) | +1-3 pts per seed with 1-2 obs |
| Observe all seeds | 4 seeds go from 0→1-2 obs | +2-5 pts on unobserved seeds |
| Adaptive reallocation | Redirect wasted repeats | +1-3 pts on hard seeds |

**Combined expected gain: +5-10 points average across rounds**, with the biggest improvement on rounds where 2-4 seeds were previously pure-prior.

## Implementation Order

1. **Soft blending curve** — smallest code change, immediately makes every query worthwhile, easy to backtest
2. **Optimal viewport placement** — replaces `find_dynamic_viewports`, frees up budget
3. **Observe-all-seeds allocation** — new budget logic, depends on 1+2 being in place
4. **Adaptive reallocation** — most complex, refactors `main()` execution flow, do last
