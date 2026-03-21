# Round Analysis — Live Game Performance (Rounds 9-13)

## Our Submitted Scores

| Round | Score | Rank | Total Teams | Weight | Seeds Submitted | Queries Used |
|------:|------:|-----:|------------:|-------:|----------------:|-------------:|
| R9    | 86.7  | 57   | 221         | 1.55   | 5               | 50/50        |
| R10   | 76.1  | 84   | 238         | 1.63   | 5               | 50/50        |
| R11   | 81.2  | 53   | 171         | 1.71   | 5               | 50/50        |
| R12   | 56.9  | 46   | 146         | 1.80   | 5               | 50/50        |
| R13   | 85.7  | 70   | 186         | 1.89   | 5               | 50/50        |

**Leaderboard position:** Rank 70 / 330 teams. Top teams score ~177. Our weighted score: 161.6.

## Per-Seed Score Variance

| Round | Seed 0 | Seed 1 | Seed 2 | Seed 3 | Seed 4 | Spread |
|------:|-------:|-------:|-------:|-------:|-------:|-------:|
| R9    | 86.5   | 85.4   | 85.7   | 88.0   | 87.9   | 2.6    |
| R10   | 75.2   | 75.9   | 73.4   | 78.1   | 77.9   | 4.7    |
| R11   | 82.7   | 83.0   | **75.8** | 82.2   | 82.4   | **7.1**  |
| R12   | 57.8   | 60.6   | **49.7** | 58.4   | 57.9   | **10.9** |
| R13   | 87.9   | 84.6   | 84.5   | 86.0   | 85.6   | 3.4    |

Seed 2 is consistently the worst performer in R11 and R12, dragging the round average down significantly.

---

## CRITICAL FINDING: Seeds Have Different Initial Maps

**Each seed has a completely different procedurally generated map.** ~700 cells differ between seeds (44% of the 40x40 grid). This includes:
- Different forest/plains layouts (forest<->plains: ~475 swaps)
- Different settlement counts and positions
- Different ocean/mountain borders
- Different numbers of initial settlements

**Settlement counts per seed (examples):**

| Round | Seed 0 | Seed 1 | Seed 2 | Seed 3 | Seed 4 |
|------:|-------:|-------:|-------:|-------:|-------:|
| R9    | 33     | 50     | 58     | 40     | 38     |
| R10   | 39     | 52     | 41     | 56     | 50     |
| R11   | 33     | 32     | **56** | 35     | 34     |
| R12   | 44     | varies | varies | varies | varies |

Seed 2 in R11 has 56 initial settlements vs 33 for seed 0 -- a fundamentally different map requiring different predictions.

**Implication: Observation pooling across seeds is INVALID for per-cell predictions.** The current cold-round pooling code (`pool_observations()`) combines observations from cells with different initial terrain across seeds. This adds noise rather than signal.

---

## Observation Strategy Used in Production

All rounds used identical strategy:
- **Phase 1:** 3x3 tiled viewports at positions (1,1), (1,13), (1,24), (13,1), (13,13), (13,24), (24,1), (24,13), (24,24)
- **9 queries per seed x 5 seeds = 45 queries**
- **Phase 2:** 5 remaining queries targeted at one seed (varied per round)
- **Total coverage:** ~90% of map, each cell observed 1 time per seed
- **All 50 queries always exhausted**

One seed receives 14 queries (extra Phase 2 observation); the other four get 9 each.

### Execution Performance
- Round 9: 68 seconds total
- Round 10: 37 seconds (caching optimizations)
- Rounds 11-12: Multiple re-planning iterations with cached queries
- No query failures or errors (except R10 seed 4 submitted too late -- 409 error)

---

## Ground Truth Analysis

### Map Characteristics

| Round | Dynamic Cells | Avg Entropy | Settle>5% | Port>5% | Ruin>5% | Forest Changing | Max Settle Prob |
|------:|--------------:|------------:|----------:|--------:|--------:|----------------:|----------------:|
| R9    | 1319          | 0.656       | 1096      | 111     | 3       | 336             | 0.345           |
| R10   | 540           | 0.291       | 77        | 0       | 0       | 110             | 0.120           |
| R11   | 1336          | 0.776       | 1219      | 123     | 11      | 368             | 0.595           |
| R12   | 649           | 0.645       | 517       | 48      | 14      | 176             | 0.875           |
| R13   | 1384          | 0.586       | 1078      | 48      | 1       | 347             | 0.350           |

### Round Classification

| Round | Type | Characteristics |
|------:|------|-----------------|
| R9    | Warm | High dynamics, moderate expansion, many settlement cells |
| R10   | Cold | Few dynamic cells, very low settlement probability, mostly forest changes |
| R11   | Warm | Highest entropy, most dynamic, strong expansion, many ports |
| R12   | Mixed | Moderate dynamics but HIGH settlement probability (max 0.875), many ports, ruins appear |
| R13   | Warm | Similar to R9, moderate expansion |

### Dynamic Cells by Initial Terrain (R9 example)

| Initial Terrain | Dynamic Cells | Total Entropy | Avg Entropy |
|-----------------|-------------:|-------------:|------------:|
| Plains          | 966          | 591          | 0.612       |
| Forest          | 320          | 237          | 0.740       |
| Settlement      | 32           | 36           | 1.134       |
| Port            | 1            | 1            | 1.082       |

**Key insight:** Initial settlements have the HIGHEST per-cell entropy (1.13) -- they're the most unpredictable cells. Forests that change also have high entropy (0.74). Plains are the bulk of dynamic cells but with lower individual entropy.

---

## What Works

1. **Full map coverage** -- the 3x3 tiling ensures no blind spots
2. **All seeds submitted** -- no zero-score seeds
3. **Fast execution** -- completes in <2 minutes, well within the prediction window
4. **Contextual priors** -- when loaded correctly, these are the strongest signal
5. **Budget fully utilized** -- no wasted queries

## What Needs Improvement

### 1. Observation Pooling Is Broken (CRITICAL)
Seeds have different maps. Pooling cell-level observations across seeds mixes data from different terrain. This must be disabled or replaced with parameter-level pooling (e.g., aggregate expansion rate estimates across seeds, not raw cell counts).

### 2. Per-Seed Prediction Quality Varies Too Much
Spread of 7-11 points between best and worst seed (R11, R12). The worst seed drags the average down. Seeds with more initial settlements (like R11 seed 2 with 56) may need different handling than seeds with fewer (seed 0 with 33).

### 3. Only 1 Observation Per Cell Per Seed
With 9 queries covering ~1444 cells, each cell gets observed exactly once (or twice in overlaps). One stochastic sample is almost useless for estimating probabilities. The Bayesian update with equiv_samples=20 barely moves from the prior.

### 4. Phase 2 Is Underutilized
Only 5 queries allocated to Phase 2 (10% of budget). These should be the most valuable queries since they can be targeted at high-entropy areas.

### 5. Cold Round R10/R12 Strategy
R10 has only 77 cells with settlement probability >5% and max settlement prob of 0.12. The system needs to identify that very few cells will be dynamic and focus on predicting which settlements survive rather than trying to predict new expansion.

### 6. R12 Is a Special Case
R12 has the highest max settlement probability (0.875) despite being classified as having fewer dynamic cells. This suggests a round where existing settlements strongly survive but don't expand much. The current warm/cold binary classification misses this pattern.

### 7. No Re-observation of Same Cells
The system never queries the same viewport twice on the same seed. Multiple observations of the same high-entropy cells would give much better probability estimates than single observations of all cells.
