# Simulator Fixes — High Impact

Known divergences between `astar/offline/simulator.py` and the real Astar Island game mechanics, ordered by expected scoring impact.

---

## 1. Distance Function — Euclidean vs Chebyshev

**Location:** `simulator.py:129-130`

```python
def _dist(self, x1, y1, x2, y2):
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
```

The simulator uses Euclidean distance, but the game is grid-based and almost certainly uses Chebyshev (`max(|dx|, |dy|)`). The prediction code in `run.py` already uses Chebyshev for expansion estimation, making the two inconsistent.

**Why it matters:** Every range check in the simulator is affected — raid range, longship range, trade range, expansion radius, settlement reclaim radius, and population dispersal on collapse. Euclidean at range 4 reaches ~50 cells; Chebyshev at range 4 reaches 80 cells. This systematically underestimates interaction ranges, producing fewer raids, less trade, and slower expansion than the real game.

**Fix:**
```python
def _dist(self, x1, y1, x2, y2):
    return max(abs(x1 - x2), abs(y1 - y2))
```

---

## 2. Expansion Cannot Clear Forests

**Location:** `simulator.py:160-163`

```python
def _is_buildable(self, x, y):
    t = self.grid[y][x]
    return t in (PLAINS, EMPTY, RUIN)
```

Forest cells are excluded from expansion targets. But game rules say forests "provide food to adjacent settlements," and forests are often the most attractive expansion targets (adjacent food bonus). Ground truth data shows settlements appearing on cells that were initially forest.

**Why it matters:** On warm rounds, forests are common near settlements (food producers). Blocking expansion onto them forces the simulator to expand further away on plains, producing a different spatial pattern. This distorts the distance-decay curve that drives predictions.

**Fix:**
```python
def _is_buildable(self, x, y):
    t = self.grid[y][x]
    return t in (PLAINS, EMPTY, RUIN, FOREST)
```

Optionally gate forest clearing behind a fitted parameter (`forest_clear_chance: 0.3–0.7`) so it's harder than building on open land.

---

## 3. Winter Severity Range Too Narrow

**Location:** `DEFAULT_PARAMS` and ABC parameter ranges

The default `winter_severity_mean=0.4` with `std=0.2` produces severity draws mostly in the 0.0–0.8 range. On cold rounds like R3 (expansion rate 0.003), the real game produces outcomes where nearly all settlements collapse. The simulator cannot reproduce this.

**Why it matters:** R3 ground truth has max settlement probability ~0.05, but the simulator predicts ~0.27 — a 9x overestimate. This is the single largest scoring gap in backtests (21 points below oracle on R3). Cold rounds are where the simulator hurts most, and the winter model is the root cause.

**Fix:** Widen the ABC-fittable range:
- `winter_severity_mean`: allow up to 1.5 (currently capped at 0.75)
- `winter_food_loss_base`: make this an ABC parameter instead of hardcoding 0.3 — cold rounds likely have 0.6+
- `collapse_chance_base`: make this an ABC parameter instead of hardcoding 0.3 — cold rounds likely 0.6+

---

## 4. Hardcoded Parameters Not Fitted by ABC

**Location:** `abc.py` parameter space (8 fitted) vs `simulator.py` DEFAULT_PARAMS (~25 total)

ABC only fits 8 high-level parameters that map to simulator params through linear transforms. 12+ critical parameters are hardcoded and never calibrated against observations:

| Hardcoded Param | Default | Role |
|---|---|---|
| `winter_food_loss_base` | 0.3 | Drives collapse rate — the #1 signal for cold/warm |
| `base_food_production` | 0.3 | Survival baseline — too high means nothing dies |
| `collapse_chance_base` | 0.3 | How likely starvation leads to death |
| `population_growth_rate` | 0.1 | Controls how fast settlements reach expansion threshold |
| `desperate_raid_multiplier` | 2.5 | Cold rounds: starving settlements raid more, causing cascading collapses |
| `raid_damage` | 0.3 | Whether raids weaken defenders enough to collapse in winter |
| `raid_loot_fraction` | 0.4 | Resource drain on raid targets |
| `population_food_threshold` | 0.5 | Growth gating — determines steady-state population |
| `collapse_food_threshold` | 0.1 | Starvation death trigger |
| `expansion_radius` | 3 | How far new settlements spawn from parent |

**Why it matters:** The growth-vs-death balance is what determines whether a round is warm or cold. That balance depends on `base_food_production` vs `winter_food_loss_base` vs `collapse_chance_base` — all hardcoded. ABC can shift `winter_severity_mean` but can't independently control food production or collapse thresholds, so it can't reproduce the full range of game behaviors.

**Fix:** Add at minimum these 4 to the ABC parameter space:
- `winter_food_loss_base` (range 0.1–0.8)
- `base_food_production` (range 0.1–0.6)
- `collapse_chance_base` (range 0.1–0.7)
- `population_growth_rate` (range 0.03–0.25)

These 4 control the growth-vs-death balance. Fitting them allows the simulator to naturally produce both warm and cold regimes without relying on the coarse linear mapping from `expansion_rate`.

---

## 5. ABC Parameter Mapping Is Linear

**Location:** `abc.py` — parameter mapping from ABC space to simulator space

ABC parameters map to simulator params via simple linear transforms:
```python
expansion_chance = expansion_rate * 0.15
expansion_threshold = max(0.5, 2.0 - expansion_rate)
collapse_chance_base = winter_severity * 0.5
```

These mappings have no empirical basis and assume independence between parameters.

**Why it matters:** Real game mechanics have non-linear interactions. A settlement that's been raided (low food from conflict) is far more likely to die in winter (food + defense below thresholds). But the linear mapping treats `conflict_prob` and `winter_severity` as independent knobs. This means ABC can find the right *marginal* behavior for each parameter but never the right *joint* behavior, explaining why fitted MC predictions consistently hurt scores even when individual parameter estimates look reasonable.

**Fix:** Either:
1. **Direct mapping:** Map ABC params 1:1 to simulator params (skip the translation layer). Expand the ABC space to 12-15 params and fit them directly.
2. **Interaction terms:** Add compound mappings like `collapse_chance = base * (1 + conflict_severity * winter_severity)` to capture that harsh winters + frequent raids compound into mass collapse.
3. **Remove the mapping entirely:** Let ABC search the simulator parameter space directly. More expensive but eliminates an entire layer of assumptions.

Option 1 is the most practical — it removes the arbitrary mapping without exploding the search space.

---

## 6. Ruin Reclaim Only Checks Dead Settlements

**Location:** `simulator.py:352`

```python
ruins = [(s.x, s.y) for s in self.settlements if not s.alive]
```

This only finds ruins that were once tracked as settlements in `self.settlements`. Ruins that exist on the initial map, or ruins created by environmental processes (forest overtaking abandoned sites), are never in this list and can never be reclaimed by nearby settlements.

**Why it matters:** On warm rounds with high reclaim rates, missing reclaimable ruins means the simulator underestimates settlement density in areas where ruins exist from the start. This produces systematically lower settlement probabilities in those areas.

**Fix:** Scan the grid directly:
```python
ruins = []
for r in range(self.height):
    for c in range(self.width):
        if self.grid[r][c] == RUIN:
            ruins.append((c, r))
```
