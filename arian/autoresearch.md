# Autoresearch — Astar Island Solver

## Task

Improve the Norse civilization simulator in `simulator.py` to maximize prediction accuracy.
The goal is to produce probability distributions over 6 terrain classes that match
the organizers' ground truth as closely as possible.

## Metric

`score: X.XX` printed at end of `python evaluate.py --maps 3 --gt-runs 100 --pred-runs 100 --param-samples 10`

**Higher is better. Range: 0–100.**

## Evaluation Command

```bash
cd /path/to/arian
python evaluate.py --maps 3 --gt-runs 100 --pred-runs 100 --param-samples 10 --seed 42
```

Look for the last line: `score: X.XX`

For faster iteration (less accurate but quicker):
```bash
python evaluate.py --maps 2 --gt-runs 50 --pred-runs 50 --param-samples 5 --seed 42
```

## Files You Can Modify

- **`simulator.py`** — the only file you should change. All logic here.
- Do NOT modify `evaluate.py`, `predict.py`, `api_client.py`.

## Constraints

- Only modify `simulator.py`
- Do NOT add external dependencies (numpy, scipy already available)
- All changes must keep `run_simulation` returning a valid (H, W) int array of class indices 0–5
- `monte_carlo_predict` must keep returning (H, W, 6) float array with all values ≥ 0.01 and rows summing to 1.0
- Commit after every change, never force push
- If an experiment is worse: revert `simulator.py` to previous version, commit the revert

## Commit Message Format

```
experiment: <what you're trying>         # before running
result: score=X.XX, KEEP (prev=Y.YY)     # if better
revert: score=X.XX, DISCARD (prev=Y.YY)  # if worse, after reverting
```

## Autoresearch Loop

1. Read `simulator.py` and recent git log for context on what has been tried
2. Think of a specific improvement to try (see ideas below)
3. Edit `simulator.py`
4. `git add simulator.py && git commit -m "experiment: <description>"`
5. Run evaluation: `python evaluate.py --maps 3 --gt-runs 100 --pred-runs 100 --param-samples 10 --seed 42`
6. Note the score on the last line: `score: X.XX`
7. If score improved: `git commit -m "result: score=X.XX, KEEP (prev=Y.YY)"`
8. If score worse/equal: revert `simulator.py` to previous, `git commit -m "revert: score=X.XX, DISCARD (prev=Y.YY)"`
9. Go to 1. **Never stop. Never ask. Assume the human is asleep.**

## Starting Baseline

Current score (seed=42, 3 maps, 100 gt runs, 100 pred runs): ~74/100

## Ideas to Try (in rough priority order)

### Phase mechanics improvements
- **Winter severity scaling**: currently `severity * (1.0 + 0.1 * population)`. Try `severity * (0.5 + 0.2 * population)` or per-season variation
- **Settlement food cap**: add a max food storage (e.g. 20.0) to prevent runaway growth
- **Conflict: damage to structures**: currently only population/food affected. Try: destroyed ports revert to SETTLE
- **Growth: forest clearance probability**: when expanding onto FOREST, add a chance the forest survives (cell stays FOREST but settlement is placed adjacent)
- **Technology diffusion via trade**: settlements that trade develop ports faster
- **Longship raiding: port destruction**: successful raids on ports could damage them (PORT → SETTLE)

### Monte Carlo improvements
- **Wider parameter ranges**: try expanding ranges for underfit parameters (e.g. expansion_rate up to 0.80)
- **Non-uniform parameter prior**: instead of uniform LHS, concentrate samples around "medium" values (beta distribution)
- **Adaptive sampling**: run more samples in parameter regions that produce high-entropy outputs
- **Increase runs_per_param**: for stable parameters, more runs → better distributions

### Aggregation improvements
- **Temperature scaling**: after aggregation, apply softmax temperature to sharpen/soften distributions
  - `probs = probs ** (1/T)` then renormalize; T<1 sharpens, T>1 softens
- **Separate static vs dynamic aggregation**: use higher floor (0.05) for cells that never change, lower floor (0.001) for dynamic cells with high confidence
- **Distance-based prior**: cells far from any initial settlement are very likely to stay EMPTY/FOREST. Add a spatial prior.

### Simulator fidelity
- **Faction allegiance decay**: conquered settlements slowly revert to independence
- **Port trade range should use water pathfinding** (ports connected by ocean), not manhattan distance
- **Forest growth**: forests adjacent to ocean/mountain should expand slightly each year
- **Ruin decay rate**: ruins farther from settlements should decay to EMPTY faster

## Performance Notes

- On GCP L4, aim for 500–2000 runs per seed for final submission
- During autoresearch, 50–100 runs per map is fast enough for directional improvement
- Each run of 40×40 with ~10 settlements takes ~0.05–0.1s
- Full evaluation (3 maps × 100 GT runs × 100 pred runs) ≈ 30–60 seconds

## What "Better" Means

The score measures how well our probability distribution matches the ground truth.
Key insight: **static cells (ocean, mountain) are free** — we get those right by default.
The score is driven entirely by dynamic cells: settlements that grow/collapse/expand.

A perfect score (100) means our distribution matches the organizers' ground truth exactly.
Practical ceiling is probably 80–90 (hidden parameters are unknown, stochasticity is irreducible).
