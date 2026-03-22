# Experiment 3: Combined Approach Results

## Final Architecture: V3 GBM + Distance Priors + Bayesian Obs

### R22 Validation Results (trained R1-R21)

| Method | R22 Score | Delta vs Baseline |
|--------|-----------|-------------------|
| V1 GBM (35 features, old) | ~80.0 | - |
| **V3 GBM + distance priors + est expansion** | **80.69** | baseline |
| V3 + Bayesian Dirichlet obs (equiv=30) | **81.21** | **+0.52** |
| V3 + MC sim (default params) | 79.37 | -1.32 |
| V3 + MC sim + Bayesian obs | worse | - |
| Actual live R22 | 80.64 | - |

### What Worked

1. **Distance prior features (+1.3 avg on LOO)** — 6 extra features from Arian's expansion-rate-aware prior table. Biggest single improvement.

2. **n_settlements expansion rate estimation (+2.0 on R21)** — `exp_rate = 0.759 * (n_sett/n_land) - 0.004` with R²=0.995. Uses settlement_stats from query API.

3. **Bayesian Dirichlet observation update (+0.52 on R22)** — Treats model prediction as Dirichlet prior (equiv_samples=30), observations as evidence. Principled update vs naive alpha blending.

### What Did NOT Work

1. **Simulator blend (default params)** — Scores 30 avg. Default params don't match round dynamics. ABC-fitted params would help but we can't run ABC fitting at inference time within the query budget.

2. **Spatial smoothing** — +0.07 at best (sigma=0.3). Too blunt.

3. **Optuna hyperparameter tuning** — +0.16 after 7 trials. Current params are near-optimal.

4. **Naive observation blending** — alpha=0.05 gives +0.48 but fragile. Bayesian Dirichlet is better and more principled.

5. **MC simulator + Bayesian obs** — Adding MC sims hurts because default params are wrong. MC=0.1 gives -1.3.

### Experiments Completed

| Experiment | Result | Status |
|------------|--------|--------|
| 3a: Simulator-GBM blend | Sim=30 avg, blend useless | DISCARD |
| 3b: Spatial smoothing | +0.07 at best | DISCARD |
| 3c: Optuna tuning | +0.16, params near-optimal | DISCARD |
| 3d: Distance prior features | +1.3 avg LOO | **KEEP** |
| 3e: n_settlements expansion rate | +2.0 on R21 holdout | **KEEP** |
| 3f: Bayesian Dirichlet obs | +0.52 on R22 | **KEEP** |
| 3g: MC sim + Bayesian | -1.3 (default params) | DISCARD |

### Deployed Model (V3)

- **Architecture:** LightGBM × 6 classes, 41 features (35 base + 6 distance prior)
- **Checkpoints:** `checkpoints_v3/lgbm_v3_class_{0-5}.joblib`
- **Inference:** initial_grid + settlement_stats → estimate expansion rate → compute prior features → GBM predict → (optional) Bayesian obs update → static overrides → floor + normalize
- **Training time:** ~40s on GPU (L4)
- **Inference time:** ~170ms per seed

### Gap Analysis

| Score | What |
|-------|------|
| 80.6 | Our R22 live |
| 81.2 | V3 + Bayesian obs (best we can do) |
| 81.6 | Oracle params (perfect hidden params) |
| 87.6 | Elias ABC backtest on similar cold round (R8) |
| 93.8 | GT ceiling |

The 81.2 → 87.6 gap (6.4 points) is the ABC simulator with fitted params. This requires running ABC fitting (~5 min) during the query phase, which means:
1. Use first ~10 queries for observations
2. Run ABC fitting on those observations
3. Run weighted MC with fitted params
4. Bayesian blend MC + prior + remaining observations

This is Elias's full pipeline and would be the next big improvement.

### Score History

| Round | Score | Rank | Type |
|-------|-------|------|------|
| R5 | 25.0 | 120 | warm |
| R6 | 61.4 | 78 | warm |
| R7 | 12.3 | 182 | warm |
| R8 | 77.3 | 73 | cold |
| R9 | 86.7 | 57 | warm |
| R11 | 81.2 | 53 | warm |
| R12 | 56.9 | 46 | warm |
| R13 | 85.7 | 70 | warm |
| R14 | 78.4 | 56 | warm |
| R17 | 85.6 | 90 | warm |
| R21 | 84.8 | 109 | cool |
| R22 | 80.6 | 96 | cold |
