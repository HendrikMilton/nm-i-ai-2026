# Astar v2 — Improvement Ideas

Sorted by estimated impact on score. Based on R10 backtest analysis (cold round, score 73.1, prior baseline 73.5 — pipeline actually hurts by -0.4).

---

## 1. Cold-round blending is actively harmful (HIGH)

The pipeline scores *worse* than the prior-only baseline on R10. The observation blending (`OBS_WEIGHT=0.5`) and ABC MC blending (`ABC_MC_WEIGHT=0.15`) inject noise on cold rounds where the prior already captures dynamics well.

**Fix:** When `warmth == "cold"`, either:
- Skip ABC entirely and use prior-only predictions
- Drastically reduce `ABC_MC_WEIGHT` (e.g. 0.02) and `OBS_WEIGHT` (e.g. 0.1) for cold rounds
- Increase `MC_EQUIV_SAMPLES` for cold rounds so the Dirichlet prior dominates over sparse observations

This alone could recover the -0.4 gap and push cold-round scores above the baseline.

---

## 2. Simulator mechanics diverge from the real game (HIGH)

The simulator is a best-guess reimplementation. Several mechanics likely differ from the real black-box:

- **Distance function:** Simulator uses Euclidean (`math.sqrt`) but the game likely uses Chebyshev (grid-based), which changes raid ranges, trade, and expansion reach significantly
- **Expansion on forests:** `_is_buildable` only allows PLAINS/EMPTY/RUIN. But the game rules say forests provide food to adjacent settlements — settlements might be able to clear forests to expand (the sim doesn't model this)
- **Trade logic:** Sim has ports trade with 50% chance if different factions (`self.rng.random() < 0.5`), but rules say "not at war". Faction relationship tracking is missing
- **Ruin reclaim:** The sim checks ruins from the `settlements` list (dead settlements), but ruins created by forest overtake wouldn't be in this list — they'd be missed
- **Port auto-creation on expansion:** New settlements founded on coastal cells get ports with 30% chance, but the real game might use different logic tied to wealth/tech

**Fix:** Run backtests on all completed rounds, identify which seeds/cells have the worst KL divergence, and compare sim outputs vs ground truth at those cells to find systematic biases. Correct one mechanic at a time and measure.

---

## 3. ABC parameter mapping is too coarse (MEDIUM-HIGH)

The 8 ABC parameters map to ~20 simulator params through simple linear relationships (e.g., `expansion_chance = er * 0.15`). This misses:
- **Non-linear interactions:** e.g., high conflict + high winter should compound collapse rates, but they're independent
- **Missing parameters:** `desperate_raid_multiplier`, `raid_damage`, `raid_loot_fraction`, `winter_food_loss_base`, `population_growth_rate` are hardcoded, not fitted
- **Crude mappings:** `expansion_threshold = max(0.5, 2.0 - er)` is an arbitrary formula with no empirical basis

**Fix:**
- Add 3-4 more ABC parameters for the most impactful fixed params (especially `winter_food_loss_base`, `raid_damage`, `population_growth_rate`)
- Fit the mappings empirically by running ground-truth comparisons across all completed rounds
- Consider using a lookup table or piecewise linear mapping instead of ad-hoc formulas

---

## 4. Query budget allocation is suboptimal (MEDIUM)

Phase 1 uses 9 queries per seed × 5 seeds = 45, leaving only 5 for Phase 2. With only 50 queries for a 40×40 map:
- Each seed gets a single 3×3 tiling of 15×15 viewports, but all 5 seeds share the same map layout — observing all 5 is redundant for learning terrain
- The stochasticity means you need *multiple* observations of the *same* area to estimate probabilities, but each area is only observed once

**Fix:**
- Observe fewer seeds in Phase 1 (e.g., 3 seeds × 9 = 27) and use remaining 23 queries for repeat observations of the same areas across different seeds
- Since all seeds share the same initial map, use 1-2 seeds for full-map coverage and the rest for targeted repeat observations of dynamic areas (near settlements)
- Weight query allocation toward boundary cells (dist 1-3 from settlements) where outcomes are most uncertain

---

## 5. Stage 1 ABC uses argmax match rate — poor signal (MEDIUM)

Stage 1 scores candidates by what fraction of observed cells have matching argmax class between sim and observations. This is a very coarse metric:
- On cold rounds, 95%+ cells are class 0 (empty) so *any* parameter set gets ~0.95 match rate (R10 showed 0.948 vs 0.946 — basically no discrimination)
- It ignores probability calibration entirely

**Fix:**
- Use a probability-aware metric even in Stage 1 (e.g., simplified KL or Brier score)
- Or score only on dynamic cells (those observed as non-class-0 at least once) to increase signal
- Filter candidates more aggressively in Stage 1 to reduce Stage 2 compute

---

## 6. Increase MC simulation count for better probability estimates (MEDIUM)

`MC_TOTAL_RUNS = 500` may be insufficient for estimating low-probability events (ports, ruins). For a cell with true probability 0.02 of being a port, 500 runs gives ~10 observations with high variance.

**Fix:**
- Increase to 1000-2000 runs for the final prediction (or at least for the top-weighted parameter set)
- Use importance sampling: run more simulations with the highest-weighted ABC parameters
- Consider adaptive stopping: run more sims only for cells with high entropy after initial runs

---

## 7. Per-round distance decay calibration (LOW-MEDIUM)

The hardcoded `DIST_DECAY_WARM` and `DIST_DECAY_COLD` tables are averages across prior rounds. The R10 observation showed extreme concentration at d=1 (`d1=2.50, d2=0.41, d3=0.03`) — very different from defaults.

**Fix:**
- Already partially implemented via `estimate_dist_decay()`, but the observation-derived multipliers aren't sufficiently trusted vs the defaults
- When observation sample count is high (>50 cells at a given distance), trust the observation-derived values more heavily
- Blend defaults and observed values with a sample-size-dependent weight

---

## 8. Forest-to-settlement transitions not modeled in priors (LOW-MEDIUM)

The contextual priors treat forests as mostly static, but forests adjacent to settlements can be cleared for expansion (if the game supports this). The R10 ground truth likely shows some forest cells becoming settlements.

**Fix:**
- Add forest-neighbor-count as a feature in distance-aware priors specifically for forest cells
- Increase settlement probability for forest cells at dist=1 from existing settlements

---

## 9. Scoring floor values may not match server (LOW)

`CLASS_FLOORS = [0.005, 0.005, 0.001, 0.002, 0.005, 0.001]` — these are hand-tuned. If the server uses `q_floor = 0.01` universally (as suggested in the game rules tip), the local scoring may not perfectly match server scoring.

**Fix:**
- Test with uniform floors of 0.01 and compare local vs server scores on completed rounds
- Align floors with whatever the server uses

---

## 10. No ensemble across warm/cold strategies (LOW)

The pipeline makes a binary warm/cold decision at `expansion_rate < 0.05`. Rounds near the threshold get fully one treatment or the other.

**Fix:**
- Soft-blend warm and cold predictions weighted by distance from threshold
- E.g., at expansion_rate=0.04, use 80% cold + 20% warm predictions
