# Deep Analysis: Fundamental Issues Preventing 88+ Scores

Current backtest scores (rounds 9-12):

| Round | Score |
|-------|-------|
| R9    | 86.9  |
| R10   | 81.3  |
| R11   | 82.3  |
| R12   | 52.7  |
| **Avg** | **75.8** |

---

## CRITICAL BUG: Contextual Priors Are Missing

**The #1 issue.** The code at `run.py:77` loads priors from `_PRIORS_DIR`, which resolves to `/astar/`. But **no `contextual_priors*.json` files exist there**. They only exist in `outdated/astar_old/`.

This means `_CONTEXTUAL_PRIORS`, `_CONTEXTUAL_PRIORS_WARM`, and `_CONTEXTUAL_PRIORS_COLD` are all **empty dicts `{}`**. Every prior lookup falls through to the crude `TERRAIN_PRIORS` table, which is a flat per-terrain-type distribution that ignores:
- Number of adjacent forests (food bonus = settlement attractiveness)
- Whether the cell is coastal (port probability)
- Warm/cold round characteristics

For example, a coastal plains cell with 3 forest neighbors should have ~8% settlement + ~6.5% port probability (from the warm table). Instead it gets the flat plains prior of ~11% settlement, 0.9% port. This mismatch compounds across hundreds of dynamic cells.

**Fix:** Copy the priors to the active directory, or fix the path in `run.py:77`.

---

## Issue 2: Observation Budget Wasted on Full-Seed Coverage

Current strategy: **9 queries x 5 seeds = 45 queries** for Phase 1 (uniform tiling of each seed). Only **5 queries** remain for Phase 2.

But all 5 seeds share **identical hidden parameters**. Observations pool perfectly across seeds (the code already does this for cold rounds). Observing all 5 seeds with full coverage is wasteful -- each cell gets observed ~1 time per seed, which is nearly zero signal for the Bayesian update.

**Better strategy:** Observe **2-3 seeds** with full tiling (18-27 queries), leaving **23-32 queries** for Phase 2 to **re-observe high-entropy areas multiple times**. With 5-8 observations per dynamic cell instead of 1-2, the Bayesian update actually has signal to work with.

The math: With `equiv_samples=20`, 1 observation moves the posterior by ~5%. With 8 observations, it moves by ~30%. That's the difference between "prior with noise" and "useful data."

---

## Issue 3: Equiv Samples Too High for Warm Rounds

`EQUIV_WARM_PER_SEED = 20` means "treat the prior as equivalent to 20 observations." Since most cells get only 1-2 observations, the prior dominates 90-95% of the prediction. The observations barely matter.

On warm rounds where expansion rate is well-estimated and the prior is reasonable, this is fine. But when the prior is wrong (different hidden params than past rounds), observations can't override it.

**Fix:** Lower to 8-12 for warm rounds, especially if observation depth increases from fixing Issue 2.

---

## Issue 4: Distance-Aware Prior Doesn't Model Cascading Expansion

The current prior uses BFS distance from **initial** settlements only. But in the real game, settlements expand to distance 3, then those expand further. After 50 years, settlements can cascade to distance 9+ from the original.

The distance decay curve (`DIST_DECAY_WARM`) drops to 0.15 at distance 7 and 0 beyond. But ground truth shows settlements appearing at distance 10+ on warm rounds. The prior assigns near-zero probability to these cells, causing high KL divergence.

**Fix:** Model 2-hop expansion -- compute distance from initial settlements AND from cells likely to have expanded settlements (distance 1-3).

---

## Issue 5: Cold Rounds Need Fundamentally Different Treatment

R12 scores 52.7 -- dragging the average down by 8+ points. Cold rounds have very few dynamic cells, but the ones that are dynamic have high entropy. The current system:
- Pools observations (good)
- Uses cold priors (but these are missing -- see Issue 1)
- Uses higher equiv_samples (makes observations even less impactful)

The real problem: on cold rounds, most settlements die. The few that survive are determined by **micro-positioning** (adjacent forests = food, coastal = trade, distance from enemies = safety). The flat terrain prior can't capture this.

---

## Scoring Model Reference

```
score = 100 * exp(-3 * weighted_kl)
weighted_kl = sum(entropy(cell) * KL(gt[cell], pred[cell])) / sum(entropy(cell))
```

- Only cells with entropy > 0.01 contribute (static terrain is ignored)
- Higher-entropy cells (more uncertain outcomes) are weighted more heavily
- KL divergence is asymmetric: assigning 0 probability where GT > 0 is catastrophic
- To score 88: weighted_kl must be ~0.043
- To score 91: weighted_kl must be ~0.031

---

## Priority Order for Maximum Impact

| Priority | Fix | Expected Impact |
|----------|-----|-----------------|
| **1** | Copy contextual priors to active directory | +2-4 points avg |
| **2** | Reduce Phase 1 to 2-3 seeds, use budget for repeated observations | +1-3 points avg |
| **3** | Lower equiv_samples for warm rounds | +0.5-1 point |
| **4** | Model cascading expansion in distance prior | +0.5-1 point on warm |
| **5** | Better cold-round prior (survival likelihood based on food/position) | +2-5 points on cold rounds |
