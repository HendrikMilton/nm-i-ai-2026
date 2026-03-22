# Experiment 3: Simulator Blend + Follow-up Experiments

## Results Summary

### Exp 3a: Simulator-GBM Blend (Default Params)
- **Result: DISCARD**
- Simulator with default params: **30.4 avg** (terrible)
- GBM baseline: **83.6 avg**
- Best blend alpha=0.00 (pure GBM wins)
- **Conclusion:** Default simulator params don't match round dynamics. Would need ABC-fitted params per round.

### Exp 3b: Post-hoc Spatial Smoothing
- **Result: DISCARD**
- Best sigma=0.3: **83.71** vs raw 83.64 (+0.07)
- Anything above sigma=0.5 destroys predictions
- **Conclusion:** GBM predictions are already well-calibrated per-cell. Blind smoothing can't fix spatial coherence.

### Exp 3c: Optuna Hyperparameter Tuning
- **Result: DISCARD**
- 7/20 trials completed on 3-fold fast CV
- Best trial: **76.05** vs baseline 75.89 (+0.16)
- **Conclusion:** Current LGB params (depth=7, lr=0.03, 1000 trees) are near-optimal. No headroom.

### Exp 3d: Distance Prior Features + Blend (IN PROGRESS)
- Using Arian's expansion-rate-aware distance priors
- Tests: prior as features for GBM, prior-GBM blend, prior+augmented GBM blend
- **Status:** Running LOO CV, ~25 min remaining
- Early signal (R1): GBM=84.1, GBM+prior_feat=84.3

## Key Takeaways
1. GBM hyperparams are already well-tuned — no gains from Optuna
2. Simulator needs ABC-fitted params to be useful — default params score 30
3. Spatial smoothing is too blunt — needs learned spatial corrections (CNNs)
4. Distance priors are the most promising direction — prior alone scores ~70 LOO which suggests useful signal for the GBM to learn from
