# Astar Island — Deep Research Funn

Nye funn fra tre research-gjennomganger. Dette er i tillegg til kodebase-analysen og anbefalingene dere allerede har fått.

Kildene er:
1. "Predicting distributions from a black-box stochastic simulator with 50 queries"
2. "Optimal probability estimation for entropy-weighted KL scoring"
3. "Predicting grid distributions in a Viking civilization simulator"

---

## 1. Probability floor: Erstatt flat 0.01 med KT-estimator

**Funn:** Krichevsky-Trofimov estimatoren (α=0.5) er **bevist minimax optimal for KL divergence** — den eksakte metrikken vi scores på.

```python
q(c) = (n_c + 0.5) / (N + 3.0)    # K=6 klasser
```

Sammenlignet med vår faste floor:

| Observasjoner (N) | KT adaptiv floor | Vår faste 0.01 |
|---|---|---|
| 0 (uobservert) | 0.167 | 0.01 |
| 5 | 0.063 | 0.01 |
| 10 | 0.038 | 0.01 |
| 30 | 0.015 | 0.01 |

Vår faste 0.01 er **for lav** for celler med få observasjoner — noe som gjelder nesten alle dynamiske celler. KT gir automatisk sterkere smoothing når data er sparsomt.

**Implementering:** Erstatt `floor_and_normalize()` med KT-estimator. For ekstra sikkerhet oppå:

```python
q_final = 0.97 * q_kt + 0.03 * np.full(6, 1/6)  # uniform mixture
q_final = np.clip(q_final, 0.005, 0.995)
q_final /= q_final.sum()
```

**Bruk float64 i hele submission-pipelinen** — float32 mangler presisjon i log-beregninger nær null.

**Effort:** 20 min. **Estimert gevinst:** +1-3 poeng.

---

## 2. Blending: Erstatt hardkodet prior_weight med Hausser-Strimmer shrinkage

**Funn:** Nåværende `prior_weight = 12.0 / (1.0 + obs_total / 1.5)` er manuelt tunet. Hausser-Strimmer (2009) gir **closed-form optimal shrinkage**:

```python
def optimal_shrinkage(counts, prior):
    K = len(counts)
    N = counts.sum()
    if N <= 1:
        return 50.0  # Prior dominerer

    p_mle = counts / N
    V = (1.0 - np.sum(p_mle**2)) / (N - 1)  # estimert varians i MLE
    D_sq = np.sum((p_mle - prior)**2)         # avstand MLE vs prior

    if D_sq < 1e-12:
        return 50.0  # Prior matcher data

    lam = np.clip(V / (V + D_sq), 0, 1)
    if lam >= 1.0:
        return 50.0
    return np.clip(lam * N / (1.0 - lam), 0.5, 50.0)
```

Hva dette gjør: Hvis observasjonene ligner prioren → høy vekt til prior. Hvis de avviker → lav vekt. Per-celle, adaptivt. Typisk optimal prior_weight for K=6 med moderat prior-kvalitet: **w ≈ 3-8 pseudocounts**.

**Effort:** 30 min. **Estimert gevinst:** +1-3 poeng.

---

## 3. Modell-kombinering: Linear pooling er RIKTIG

**Funn:** Abbas (2009) beviste matematisk:
- **KL(true ‖ pred)** minimeres av **lineær pooling**: `q = w*p1 + (1-w)*p2`
- **KL(pred ‖ true)** minimeres av **log-linear pooling**: `q ∝ p1^w * p2^(1-w)`

Vår scoring er KL(true ‖ pred). Lineær pooling er riktig. Log pooling er **zero-forcing** — hvis én modell gir 0 til en klasse, gjør kombinasjonen det også → KL eksploderer.

Vår nåværende blending er allerede lineær. **Bekreftelse at tilnærmingen er korrekt.** Men om noen foreslår geometrisk gjennomsnitt av simulator og priors: nei.

---

## 4. Importance-weighted ensemble: Koble Arians LHS med observasjoner

**Funn:** Den enkleste formen for Approximate Bayesian Computation som kobler de to pipelinene:

```python
# Arian har allerede steg 1-2
# 1. Kjør lokal simulator med M=500 LHS parameter-settings
# 2. For hver setting θ, kjør K=20-50 stokastiske runs
# 3. For viewport-celler: beregn per-celle klassefrekvenser per θ

# NYTT: Vekt parametere basert på match med API-observasjoner
for theta in parameter_settings:
    sim_freq = compute_frequencies(simulator_runs[theta], viewport_cells)
    obs_freq = compute_frequencies(api_observations, viewport_cells)
    discrepancy = sum_KL(obs_freq, sim_freq)  # per viewport-celle
    weights[theta] = exp(-lambda * discrepancy)

# Final prediksjon (alle 1600 celler):
for cell in all_cells:
    prediction[cell] = sum(weights[θ] * freq[cell][θ] for θ) / sum(weights)
```

λ (temperatur) styrer skarphet. Tune via cross-validation på overlapp-celler.

**Effekt:** Parametere som produserer virkelighets-lignende utfall → høy vekt. Parametere som avviker → null vekt. Lar dataen bestemme winter_severity i stedet for å gjette.

**Effort:** 1-2 timer. **Estimert gevinst:** +3-8 poeng.

---

## 5. Query-strategi: 3×3 tiling er bekreftet nær-optimal

**Funn:** Submodularity-bevis (Krause et al., 2008) bekrefter at uniform allokering over seeds er optimal. Greedy sensor placement gir ≥63% av optimalt informasjonsinnhold.

Viewport top-left corners på **{0, 13, 25} × {0, 13, 25}** gir:
- 9 viewports per seed × 5 seeds = 45 queries
- 2-3 cellers overlapp mellom viewports (gratis ekstra-observasjoner)
- 5 queries til overs for adaptive refinement

Overlapp-celler kan brukes til cross-validation av modellen.

**De 5 ekstra queries:** Greedy uncertainty-reduction — velg viewport med høyest sum av gjenværende usikkerhet. Prioriter høy-entropi transisjonssoner.

---

## 6. Score-til-KL tabell: Konkrete mål

| Mål-score | Krav: weighted KL | Hva det krever |
|---|---|---|
| 95 | < 0.017 | ~146 obs/celle (urealistisk med 50 queries) |
| 90 | < 0.035 | ~71 obs/celle |
| 80 | < 0.074 | Gode priors + noen observasjoner |
| 70 | < 0.119 | Prior-only på gode runder |
| 50 | < 0.231 | Prior-only på dårlige runder |

**Implikasjon:** Score 90+ krever bedre priors, ikke flere observasjoner. 50 queries kan aldri gi nok data alene. Prior-kvalitet er den bindende constrainten.

---

## 7. Scoring er robust mot individuelle katastrofer

Én celle med KL=10 (katastrofalt feil) endrer total weighted KL med ~10/1600 = 0.006 → score-endring ~1.9%.

**Konsekvens:** Systematisk nøyaktighet over alle celler er viktigere enn å perfeksjonere enkeltceller. Å ha feil prior-regime (warm vs cold) på ALLE dynamiske celler er katastrofalt. Å ha én feil celle er irrelevant.

---

## 8. Regime-spesifikke Dirichlet priors

**Funn:** I stedet for å bygge warm/cold priors manuelt, bruk Dirichlet-Multinomial conjugacy:

```python
# For hver regime (expansion/collapse), bygg prior fra ground truth
alpha_expansion = np.ones((40, 40, 6))  # uniform Dirichlet start
alpha_collapse = np.ones((40, 40, 6))

for round_data, regime in training_rounds:
    for y in range(40):
        for x in range(40):
            if regime == 'expansion':
                alpha_expansion[y, x, round_data[y, x]] += 1.0
            else:
                alpha_collapse[y, x, round_data[y, x]] += 1.0

# Prediksjon = Dirichlet posterior mean
pred_expansion = alpha_expansion / alpha_expansion.sum(axis=-1, keepdims=True)
pred_collapse = alpha_collapse / alpha_collapse.sum(axis=-1, keepdims=True)
```

Bayesian Model Averaging for soft valg mellom regimer:

```python
# Beregn log-likelihood av tidlige observasjoner under hvert regime
# Vekt prediksjoner proporsjonalt
p_final = w_exp * pred_expansion + w_col * pred_collapse
```

Fordel over threshold-tilnærming: gir soft blending når evidensen er tvetydig.

**Effort:** 1-2 timer. **Estimert gevinst:** +10-20 poeng på outlier-runder (R3-type).

---

## 9. Distance transform features

**Funn:** `scipy.ndimage.distance_transform_edt` gir avstand fra hver celle til nærmeste forekomst av hver terrengtype. Mye rikere spatial feature enn bare naboskog-count.

```python
from scipy.ndimage import distance_transform_edt

def distance_features(grid, n_classes=6):
    dists = np.zeros((40, 40, n_classes))
    for c in range(n_classes):
        mask = (grid != c)
        if not mask.all():
            dists[:,:,c] = distance_transform_edt(mask)
        else:
            dists[:,:,c] = 99.0
    return dists  # + log1p(dists) og 1/(1+dists) som alternativer
```

18 features per celle i ~0.1ms. Spesielt nyttig:
- **Avstand til settlement:** Predikerer sannsynlighet for ekspansjon
- **Avstand til ocean:** Predikerer port-dannelse
- **Avstand til forest:** Korrelerer med food-tilgang og overlevelse

Kan brukes til å bygge rikere priors enn (terrain, naboskog, kyst)-tabellen.

**Effort:** 30 min for features, 1-2 timer for å integrere i prior-modell. **Estimert gevinst:** +2-5 poeng.

---

## 10. Entropy-vekting og query-allokering

**Funn:** Optimal query-allokering følger √-entropi-regelen (Neyman allocation):

**Antall observasjoner per celle bør være proporsjonalt med √(entropy-vekt)**

Marginalverdien av observasjon nr. k på en celle med effective sample size A:

```
Δ_k = entropy_weight × (K-1) / (2 × A × (A+1))
```

Diminishing returns er kraftige:
- 2. observasjon er verdt 1/3 av 1. observasjon
- 3. observasjon er verdt 1/6 av 1. observasjon
- 2. observasjon på celle i er kun bedre enn 1. observasjon på celle j hvis **entropy_weight_i > 3 × entropy_weight_j**

**Konsekvens:** Med 50 queries bør ~40-50 unike celler få nøyaktig 1 observasjon. Kun celler med 3× median entropy-vekt bør få repeat-observasjoner.

---

## Prioritert handlingsliste (kun nye funn)

### Tier 1 — Størst impact, minst effort

| # | Handling | Gevinst | Effort |
|---|---------|---------|--------|
| 1 | KT-estimator (α=0.5) erstatter flat 0.01 | +1-3 | 20 min |
| 2 | Float64 i submission-pipeline | Edge-case sikkerhet | 5 min |
| 3 | 3×3 tiling ({0,13,25}²) for queries | Full kartdekning | 30 min |

### Tier 2 — Høy impact, moderat effort

| # | Handling | Gevinst | Effort |
|---|---------|---------|--------|
| 4 | Regime-spesifikke Dirichlet priors (expansion/collapse) | +10-20 på outliers | 1-2 timer |
| 5 | Importance-weighted ensemble (koble LHS + observasjoner) | +3-8 | 1-2 timer |
| 6 | Hausser-Strimmer shrinkage erstatter hardkodet prior_weight | +1-3 | 30 min |

### Tier 3 — Moderat impact, mer effort

| # | Handling | Gevinst | Effort |
|---|---------|---------|--------|
| 7 | Distance transform features i prior-modell | +2-5 | 1-2 timer |
| 8 | Cross-validation (leave-one-round-out) for hyperparameter-tuning | Bedre tuning | 1 time |
