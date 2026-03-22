# Experiment 3: Elias Simulator Blend

## Goal
Use Elias's existing offline ABC simulator to generate predictions, then blend with our GBM.
The simulator runs hundreds of Monte Carlo simulations and averages the outcomes — essentially
approximating the ground truth generation process.

## Approach
1. Wire up Elias's simulator at `../../elias/astar/offline/`
2. For a given round: run 100-500 sims, average outcomes → sim_pred (40×40×6)
3. Blend: `final = alpha * sim_pred + (1-alpha) * gbm_pred`
4. Tune alpha on historical rounds

## Elias's code
- `../../elias/astar/run.py` — main engine with ABC fitting
- `../../elias/astar/offline/abc.py` — ABC parameter fitting
- `../../elias/astar/offline/simulator.py` — the actual simulator
- `../../elias/astar/offline/run_local.py` — offline evaluation harness

## Key insight
The simulator captures the EXACT spatial dynamics (settlements cluster, expand, raid) that
our per-cell GBM misses. The GBM captures the statistical patterns across rounds.
Blending should give the best of both.

## Eval
- For each historical round with known config:
  - Run simulator with true config → sim_pred
  - Run our GBM → gbm_pred
  - Blend at different alphas
  - Score against GT
- Find optimal alpha

## Eval command
```bash
cd /home/hendrik/agentic-avengers-nm-ai/hendrik/challenge3/experiments/exp3_simulator_blend
python3 eval_blend.py
```

## Rules
- DO NOT modify Elias's code
- Edit ONLY files in this folder
- Report blend scores vs individual scores
- Target: 90+ (if simulator works well)
