# Phase 2 Query Allocation (5 remaining queries)

After Phase 1, all 45 queries are spent (9 viewports × 5 seeds), covering every non-ocean cell once. The remaining 5 queries should go where they add the most value, not just repeat the same viewports on the most "surprising" seed.

## Current behavior

Phase 2 re-queries the same tiling viewports on seeds ranked by surprise score. This gives a second stochastic sample on the most surprising seed's cells. Diminishing returns — 2nd observation is worth ~1/3 of the 1st.

## Better strategies

### 1. Expansion rate confidence targeting (highest leverage)

The expansion rate estimate drives the prior for all 5 seeds × 1600 cells. If the estimate is uncertain, improving it has the biggest downstream impact.

- After Phase 1, compute expansion rate variance across seeds
- If variance is high (seeds disagree), build viewports centered on settlement boundary cells (distance 1-3) across multiple seeds
- These observations directly improve the expansion rate estimate, which improves every prediction

### 2. Cross-seed disagreement

Hidden params are shared across all 5 seeds. If one seed shows expansion at distance 2 but others don't, one got an unlikely stochastic outcome.

- Compare per-seed expansion rates after Phase 1
- Re-query the outlier seed's boundary cells to determine if the observation was noise or signal
- Helps separate stochastic variance from actual expansion behavior

### 3. High-entropy boundary cells

Not all cells benefit equally from a second observation. Cells far from settlements are almost always empty (one obs is enough). Cells at distance 1-3 are where outcomes vary most.

- After Phase 1, identify cells where the observation disagreed most with the prior (e.g. settlement observed where empty was expected, or vice versa)
- Build viewports that maximize coverage of those high-surprise boundary cells
- A targeted 15×15 viewport over a cluster of boundary cells is far more valuable than a full-map re-scan

## Proposed approach

1. After Phase 1, compute expansion rate confidence (variance across seeds)
2. If confidence is low → target distance 1-3 cells across multiple seeds to nail down expansion rate
3. If confidence is high → target the most surprising seed's boundary cells for better per-cell estimates
