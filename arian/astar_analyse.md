# Astar Island — Komplett Analyserapport

**Dato:** Fredag 20. mars 2026, ~14:00  
**Analysert av:** Gabriel (strategisk lag)  
**Scope:** Full kodebase-analyse + strategiske anbefalinger  
**Status:** Rank ~110 — estimert potensial: topp 10-20

---

## 1. Arkitekturoversikt

### Repostruktur

```
repo/
├── elias/astar/                        # Hoved-pipeline
│   ├── run.py                          # Online: query API → observe → predict → submit
│   ├── utils.py                        # API-klient, floor_and_normalize()
│   ├── contextual_priors.json          # Lært prior-tabell fra R1-R5 ground truth
│   ├── STRATEGY.md                     # Strategidokument med historikk
│   ├── IMPROVEMENTS.md                 # Forbedringsliste med backtest-data
│   ├── offline/
│   │   ├── simulator.py                # Lokal 5-fase simulator
│   │   ├── run_local.py                # Offline Monte Carlo → submit UTEN queries
│   │   ├── score.py                    # Lokal KL divergence scoring
│   │   └── sweep.py                    # Parameter-sweep over completed rounds
│   └── logs/offline/                   # 50+ backtest-resultater (JSON)
│
├── arian/                              # Alternativ pipeline
│   ├── predict.py                      # Predict + submit (bruker INGEN queries)
│   ├── api_client.py                   # API-klient
│   ├── simulator.py                    # NumPy-basert sim med LHS parameter-sampling
│   └── evaluate.py                     # Lokal evaluering
```

### Tre separate pipelines

| Pipeline | Eier | Queries | Metode | Backtest-score |
|----------|------|---------|--------|----------------|
| Elias Online (run.py v4) | Elias | 50/runde | Priors + API-observasjoner + sim-blending | 69-88 (aldri submittert) |
| Elias Offline (run_local.py) | Elias | 0 | Priors + lokal Monte Carlo sim | 69-88 |
| Arian Offline (predict.py) | Arian | 0 | LHS parameter-sampling + Monte Carlo | Ikke benchmarked mot ground truth |

---

## 2. Rot-årsak: Hvorfor vi ligger på rank 110

### Det store bildet

**Backtest viser 69-88 poeng. Faktiske submissions: 0.26 og 25.0.**

Gapet skyldes ikke manglende modell — det skyldes at buggy versjoner ble submittet, og den gode versjonen (v4) har aldri blitt brukt online.

### R3: Score 0.26 — v1 (katastrofal overconfidence)

**Rot-årsak:** v1 brukte ren empirisk frekvens fra ÉN stokastisk observasjon, uten priors.

Kode (git commit `a2cdb4b`):
```python
# counts_to_prediction() i v1
if total > 0:
    prediction[r][c] = [n / total for n in counts[r][c]]
else:
    prediction[r][c] = [1.0 / N_CLASSES] * N_CLASSES
```

Med 9 viewports × 5 seeds = 45 queries fikk hver celle NØYAKTIG 1 observasjon:
- Celle observert som Settlement → prediction = `[0, 1, 0, 0, 0, 0]` (100% confidence)
- Ground truth kan være `[0.4, 0.3, 0.05, 0.05, 0.2, 0]`
- KL divergence eksploderer for klasser der ground truth > 0 men prediction = 0
- `floor_and_normalize()` redder fra uendelig, men KL er fortsatt ekstrem

Celler UTEN observasjoner fikk uniform 1/6 — ingen terrengbaserte priors.

**Konsekvens:** Hvert dynamisk punkt var ekstremt overconfident. Scoring-formelen `100 × exp(-3 × weighted_kl)` kollapser eksponentielt.

### R5: Score 25.0 — v2 (cross-seed averaging)

**Rot-årsak:** v2 blandet observasjoner fra forskjellige kart.

Fra STRATEGY.md: *"cross-seed averaging destroyed seeds 2-4 in R5"*

Hver seed har et ANNET kart (andre settlement-posisjoner, annen terrengfordeling). Å snitte observasjoner mellom seeds:
- Seed 0 har settlement på (5,10), seed 3 har skog der
- Averaging gir ~50% settlement, 50% skog → feil for BEGGE seeds
- Seeds 2-4 ble ødelagt. Snittscoren kollapset.

### v4 fikser alt — men har aldri blitt submittet

v4 (nåværende `run.py` og `offline/run_local.py`) har:
- Contextual priors som baseline (73-88 poeng alene)
- Per-seed grids (aldri bland seeds)
- Adaptiv blending (prior dominerer med få obs)
- Greedy set cover for viewports
- Surprise-basert phase 2 budget-allokering

---

## 3. Contextual Priors — Ryggraden i modellen

### Hva er det?

`contextual_priors.json` er en lookup-tabell med 42 entries. Nøkkel: `(initial_terrain, n_forest_neighbors, is_coastal)`. Verdi: sannsynlighetsfordeling over 6 klasser.

Eksempler:
```
Settlement (inland, 1 forest):   P(settle)=0.274, P(empty)=0.478, P(ruin)=0.163
Settlement (coastal, 2 forest):  P(settle)=0.121, P(port)=0.063, P(empty)=0.510
```

Lært fra ground truth via `/analysis/{round_id}/{seed_index}` for R1-R5.

### Styrker
- Fanger terrengets lokale kontekst (naboskog, kystlinje)
- Gir sterk baseline uten noen queries (69-88 poeng)
- `floor_and_normalize()` med 0.01 minimum forhindrer KL-katastrofer

### Svakheter

**Kritisk: Priors er STATISK gjennomsnitt over alle runder.**

Det er ÉN tabell som brukes uansett rundens karakteristikk. Men ground truth varierer dramatisk:

| Runde | Celler m/ P(settle)>0.10 | Maks P(settle) | Scored cells | Karakter |
|-------|--------------------------|----------------|--------------|----------|
| R1    | 4666 av 6590             | 0.66           | 6590         | VARM: massiv ekspansjon |
| R3    | 0 av 2098                | 0.05           | 2098         | ISKALD: alt dør |
| R4    | 2960 av 6706             | 0.39           | 6706         | MILD: moderat |
| R5    | 3333 av 6299             | 0.61           | 6299         | VARM: god overlevelse |

I R3 er P(settlement) ≈ 0.03 for ALLE settlement-celler. Prioren på 0.274 er **9× for høy**. Det er hovedårsaken til at R3 scorer bare 52.8 — prioren matcher ikke virkeligheten.

**Manglende terrengtyper:** Terrain 3 (Ruin) og terrain 0 (Empty) mangler i priors — faller tilbake til grove globale `TERRAIN_PRIORS`.

**Null-verdier:** Alle 42 entries har P(mountain)=0.0 og alle inland entries har P(port)=0.0. Korrekt logisk (dynamiske celler blir ikke mountains, inland blir ikke ports), men avhenger av at `floor_and_normalize()` kjøres konsekvent.

### Anbefaling

1. Lag to sett priors: "warm" (basert på R1/R4/R5) og "cold" (basert på R3)
2. Generer priors for terrain 3 og 0 fra ground truth data
3. Klassifiser runden tidlig (se seksjon 5) og velg riktig prior-sett

---

## 4. Simulator-analyse

### Sammenligning: Elias vs Arian

| Aspekt | Elias (`offline/simulator.py`) | Arian (`simulator.py`) |
|--------|-------------------------------|----------------------|
| Språk | Pure Python, `random.Random` | NumPy, `np.random.Generator` |
| Parameter-håndtering | **Faste DEFAULT_PARAMS (25 params)** | **LHS over 8 nøkkelparams** |
| Monte Carlo | 200 runs, 1 param-sett | 500 runs, 10 param-sett |
| Static cell enforcement | Nei (kan overskrives) | Ja, `static_mask` etter hvert år |
| Port-utvikling | Via wealth threshold | Via adjacency til ocean |
| Expansion | Radius-basert, `rng.choice` | Radius 2, matbasert terskel |
| Trade | Euclidean distance | Manhattan distance |
| Collapse | Food + defense + stochastic | Food ≤ 0 or population ≤ 0 |
| Speed | Langsom (pure Python) | Raskere (NumPy delvis vektorisert) |

### Nøkkelfunn: Simulatoren SKADER scoren

Backtest-data er entydig:

| Runde | Prior-only | sw0.5_pw4 (blended) | sw1_pw4 (sim dominerer) | Delta (blended vs prior) |
|-------|-----------|---------------------|------------------------|--------------------------|
| R1    | 73.5      | 76.3                | 76.3                   | **+2.8** |
| R2    | 75.4      | 78.1                | 77.7                   | **+2.7** |
| R3    | 52.8      | 45.0                | 39.1                   | **-7.8** |
| R4    | 87.6      | 85.1                | 81.3                   | **-2.5** |
| R5    | 69.1      | 70.5                | 69.4                   | **+1.4** |

Per-seed breakdown bekrefter at det er systematisk, ikke tilfeldige outliers:
```
R1: +2.9  +2.8  +2.6  +3.0  +3.0  (konsistent positiv)
R3: -7.4  -8.9  -7.7  -7.9  -6.7  (konsistent negativ)
R4: -3.1  -2.3  -1.9  -2.0  -2.8  (konsistent negativ)
```

**Rot-årsak:** Elias' simulator bruker faste params. Når hidden params avviker (spesielt `winter_severity`), produserer simulatoren *confidently wrong* predictions. Scoring-formelen straffer overconfidence eksponentielt.

### Arians LHS er bedre tilnærming

Arian sampler over 8 dimensjoner med Latin Hypercube:
```
expansion_rate      [0.05 .. 0.60]
conflict_prob       [0.05 .. 0.50]
winter_severity     [0.10 .. 0.70]    ← dekker hele spekteret
trade_range         [4 .. 12]
ruin_reclaim_rate   [0.10 .. 0.60]
forest_reclaim_rate [0.02 .. 0.25]
longship_prob       [0.05 .. 0.40]
longship_range      [5 .. 15]
```

Med 10 LHS-samples gir ~2/10 samples `winter_severity > 0.55` (R3-type). Elias' faste `winter_severity_mean = 0.4` treffer aldri dette. Arians tilnærming gir bredere distribusjon = mer robust.

### Anbefaling

1. **Kortsiktig:** `sim_weight=0` (prior-only) som default. Sikrere enn sim med faste params.
2. **Mellomsiktig:** Integrer Arians LHS-sampling i Elias' pipeline.
3. **Langsiktig:** Kalibrér sim-params fra observerte settlement stats (food, population).

---

## 5. Query-strategi

### Nåværende implementasjon (run.py v4)

**Viewport-planning:** Greedy set cover (`find_dynamic_viewports()`) plasserer minimum antall 15×15 viewports for å dekke alle dynamiske celler (initial terrain ∈ {Settlement, Port, Ruin}).

**Budget-allokering:**
- Phase 1: 1 pass gjennom alle 5 seeds sine dynamic viewports. Typisk 15-30 queries.
- Phase 2: Resterende queries til seeds med høyest "surprise" (L1-avstand mellom observert frekvens og prior).

**Blending-formel:** `prior_weight = 12.0 / (1.0 + obs_total / 1.5)`

| Observasjoner | prior_weight | Obs-andel av blend |
|---------------|-------------|-------------------|
| 1             | 7.2         | 12% |
| 2             | 5.1         | 28% |
| 3             | 4.0         | 43% |
| 5             | 3.0         | 63% |

### Hva er optimal query-allokering?

**Matematikk:** 40×40 kart, 15×15 viewports. 3 viewports dekker én akse (0-14, 13-27, 25-39). 3×3 = 9 viewports for full kartdekning per seed. 5 seeds × 9 = **45 queries for full dekning, 5 til overs.**

**Funn fra backtest:** Observasjoner gir bare +1-3 poeng over priors på gode runder. Marginalen er liten fordi blending-formelen er konservativ (1 obs = bare 12% vekt).

**Spørsmålet: 1 obs/celle (full dekning) vs 3 obs/halvparten?**

Vi har ingen direkte A/B-test, men kan resonere:
- 1 obs + prior: nudger 12% — nok til å detektere om virkeligheten avviker
- 0 obs + prior: null korreksjon — avhenger helt av prior-kvalitet
- 3 obs + prior: 43% obs-andel, men bare halvparten av cellene dekket

**Anbefaling:** Full dekning (1 obs per celle per seed) er bedre. Grunnen: 4 unobserverte seeds får null gevinst, mens 1 obs per celle likevel detekterer avvik. Bruk resterende 5 queries på høy-entropi soner.

### Surprise-metric

Phase 2 bruker gjennomsnittlig L1-norm mellom observert frekvens og prior:
```python
surprise += abs(obs_frac - prior[k])
```
Konseptuelt riktig, men med 1 observasjon er `obs_frac` enten 0 eller 1 per klasse — noisy estimat.

---

## 6. Runde-klassifisering (Winter Severity)

### Problemet

Contextual priors er et statisk gjennomsnitt. På R3 ("nuclear winter") er P(settlement)=0.03, men prioren sier 0.274. Resultatet: 52.8 poeng i stedet for potensielt 70+.

### Evidens for at winter severity er den dominerende variabelen

| Runde | Karakter | Prior-only score | Scored cells |
|-------|----------|-----------------|--------------|
| R1    | VARM     | 73.5            | 6590 |
| R3    | ISKALD   | 52.8            | 2098 |
| R4    | MILD     | 87.6            | 6706 |
| R5    | VARM     | 69.1            | 6299 |

R3 har bare 2098 scored cells (vs 6000-6700 for andre runder). Alt kollapset — nesten ingen dynamisk aktivitet. Settlement-overlevelse korrelerer direkte med rundescore.

### Hva styrer winter severity i simulatorene?

**Elias:** Fast `winter_severity_mean = 0.4, std = 0.2`. Treffer aldri R3-type ekstremer.

**Arian:** LHS-samplet `winter_severity ∈ [0.10, 0.70]`. ~2/10 samples fanger R3-type. Mer robust.

### Kan vi inferere winter severity fra simulate-responsen?

**Ja.** Simulate-responsen inkluderer settlement stats:
```json
{
  "settlements": [
    {"population": 2.8, "food": 0.4, "wealth": 0.7, "defense": 0.6, "alive": true}
  ]
}
```

**Indikatorer:**
- `food > 2.0` og `>50% alive` → WARM runde
- `food < 0.5` og `<30% alive` → COLD runde

**Viktig:** Alle 5 seeds deler hidden parameters. Klassifisering fra seed 0 gjelder alle seeds.

### Er dette implementert?

**Nei.** Ingen steder i kodebasen analyseres settlement stats fra simulate-responser. `run.py` logger dem men bruker dem aldri. `arian/predict.py` bruker ingen API-queries overhodet.

### Forslag: Runde-klassifisering med 2 queries

1. Bruk 2 queries på seed 0, viewport over settlement-cluster
2. Les settlement stats (food, population, alive)
3. Klassifiser som WARM eller COLD
4. Velg mellom to sett priors
5. Bruk resterende 48 queries normalt

**Kostnad:** 2 queries (4% av budsjettet)
**Estimert gevinst:** +15-20 poeng på R3-type runder (prior-mismatch fra 9× feil til ~2× feil)
**Risiko:** Feilklassifisering gir feil priors, men nedside er begrenset (priors er allerede et gjennomsnitt)

---

## 7. Komplett scorehistorikk

### Faktiske submissions

| Runde | Score | Rank | Versjon | Rot-årsak |
|-------|-------|------|---------|-----------|
| R3    | 0.26  | 100/100 | v1 | 100% confidence fra 1 obs, ingen priors |
| R5    | 25.0  | 120/144 | v2 | Cross-seed averaging |

### Backtest-resultater (hva vi KUNNE fått)

| Runde | Prior-only | Best blend | Best config | Notes |
|-------|-----------|------------|-------------|-------|
| R1    | 73.5      | 76.3       | sw0.5_pw4   | Sim hjelper +2.8 |
| R2    | 75.4      | 78.1       | sw0.5_pw4   | Sim hjelper +2.7 |
| R3    | 52.8      | 52.8       | prior_only  | Sim SKADER (ned til 39.1) |
| R4    | 87.6      | 87.6       | prior_only  | Sim gir ~0 gevinst |
| R5    | 69.1      | 70.5       | sw0.5_pw4   | Sim hjelper +1.4 |

### Gjennomsnittlig backtest-score

- **Prior-only snitt:** 71.7
- **Best blend snitt:** 73.0
- **Sim-only dominert snitt:** 66.4 (SIM SKADER SNITTET)

---

## 8. Prioriterte anbefalinger

### Tier 1 — UMIDDELBART (neste runde)

| # | Handling | Forventet gevinst | Effort |
|---|---------|-------------------|--------|
| 1 | **Submit v4 med `sim_weight=0`** | +45-55 poeng over nåværende rank | 5 min |
| 2 | Sett opp `.env` med `AINM_TOKEN` | Forutsetning for #1 | 2 min |
| 3 | Verifiser at `floor_and_normalize()` kjøres på all output | Forhindrer KL-katastrofe | 5 min |

**Estimert score etter Tier 1: 69-88 poeng (topp 20-30)**

### Tier 2 — Før neste runde (1-2 timer)

| # | Handling | Forventet gevinst | Effort |
|---|---------|-------------------|--------|
| 4 | **Lag warm/cold priors fra ground truth** | +10-20 poeng på outlier-runder | 1 time |
| 5 | **Implementer runde-klassifisering (2 queries)** | Aktiverer #4 | 30 min |
| 6 | Generer priors for terrain 3 (Ruin) og 0 (Empty) | +1-2 poeng | 20 min |

**Estimert score etter Tier 2: 75-90+ poeng (topp 10-15)**

### Tier 3 — Signifikant forbedring (halvdag)

| # | Handling | Forventet gevinst | Effort |
|---|---------|-------------------|--------|
| 7 | Integrer Arians LHS-sampling i Elias' pipeline | +2-5 poeng robusthet | 2 timer |
| 8 | Kalibrér sim-params fra observerte settlement stats | +3-8 poeng | 3 timer |
| 9 | Øk `n_sims` til 500-1000 | +1-2 poeng (kun med gode params) | 30 min |
| 10 | Analyser R3 ground truth for spesifikke prior-feil | Forbedrer cold-priors | 1 time |

**Estimert score etter Tier 3: 80-93+ poeng (topp 5-10)**

---

## 9. Oppsummering

**Hvorfor vi er rank 110:** Vi har aldri submittet koden som faktisk fungerer. v1 og v2 hadde fundamentale bugs. v4 er klar og backtest-verifisert til 69-88 poeng.

**Største uutnyttede gevinst:** Runde-klassifisering. Statiske priors treffer 87.6 på snille runder men bare 52.8 på outliers. To sett priors (warm/cold) + 2 queries for klassifisering kan løfte outlier-runder med +15-20 poeng.

**Viktigste innsikter:**
1. Contextual priors er ryggraden — ikke simulatoren
2. Simulatoren med faste params har negativ forventet verdi
3. Arians LHS-sampling er fundamentalt bedre enn faste params
4. Settlement stats fra API-responser er en ubrukt gullgruve
5. Observasjoner gir bare +1-3 poeng over priors — forbedring av priors er viktigere enn query-optimalisering
