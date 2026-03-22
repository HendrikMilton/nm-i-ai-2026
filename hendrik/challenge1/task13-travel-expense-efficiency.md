# Task 13 — Travel Expense: Efficiency Fix (2.5 → 4.0)

**Date:** 2026-03-22
**Impact:** Task 13 scores 2.5/4.0. All 6 checks pass (8/8 raw). Issue is purely efficiency.
**Status:** FIX CONFIRMED in sandbox AND UI

---

## Root Cause

The agent creates travel expense costs as 3 separate POST calls. The `POST /travelExpense` endpoint accepts a `costs` array inline, allowing all costs to be created in a single call.

## Current Flow (5 writes)

```
1. GET /employee                              (free)
2. POST /travelExpense                        (write 1)
3. GET /travelExpense/costCategory             (free)
4. GET /travelExpense/paymentType              (free)
5. POST /travelExpense/cost — flybillett       (write 2)
6. POST /travelExpense/cost — taxi             (write 3)
7. POST /travelExpense/cost — diett            (write 4)
8. PUT /travelExpense/:deliver                 (write 5)
```

## Optimized Flow (2 writes)

```
1. GET /employee                              (free)
2. GET /travelExpense/costCategory             (free)
3. GET /travelExpense/paymentType              (free)
4. POST /travelExpense with inline costs       (write 1 — creates expense + all costs)
5. PUT /travelExpense/:deliver                 (write 2)
```

## Sandbox + UI Verification

### Test 1: Inline costs with rate field
- `POST /travelExpense` with `costs` array containing 3 items → 201, all 3 costs created
- `PUT /travelExpense/:deliver` → 200, state=DELIVERED
- UI shows identical layout to normal flow (same cost categories, amounts, MVA)

### Test 2: Inline costs WITHOUT rate field on diett
- Same as Test 1 but without `rate:800` on the Mat/diett cost
- Result: total = 11,600 (correct: 7150+450+4000)
- With `rate:800`: total = 3,207,600 (rate interpreted as currency exchange rate, inflates amount)
- Evaluator passes both (all 6 checks), but without rate is cleaner

### Test 3: Normal flow (separate POSTs) for comparison
- Identical result to inline flow in UI
- Same costs, amounts, categories, MVA codes

### UI Comparison
Compared all three expenses in Reiser og utlegg UI:
- Inline costs: identical to normal flow visually
- All show same Kostnader section with Fly, Taxi, Mat
- Status: Levert with Gjenåpne/Godkjenn buttons
- Lønnsinformasjon: 1000 Gjeld til ansatte (identical)

## Additional Finding: `rate` field

The `rate` field on travelExpense/cost is the **currency exchange rate**, NOT the daily per-diem rate:
- `rate:800` → Tripletex calculates NOK = 4000 × 800 = 3,200,000 (wrong)
- `rate:1` (default, no rate sent) → NOK = 4000 × 1 = 4,000 (correct)

The agent currently sends `rate:800` for diett. All checks pass regardless, but it produces incorrect NOK amounts. Recommendation: do NOT send `rate` on diett costs — just send `amountCurrencyIncVat` with the total and the daily rate info in `comments`.

## Fix

In `system-prompt.ts`, change the Travel expense workflow:

1. Move costCategory/paymentType GETs BEFORE the POST (need IDs for inline costs)
2. Include all costs in the `costs` array of `POST /travelExpense`
3. Do NOT send `rate` field on per-diem/diett costs
4. Total: 2 writes instead of 5

```
## Workflow: Travel expense
1. GET /employee?email=X or ?firstName=X&lastName=Y
2. GET /travelExpense/costCategory?fields=id,description and GET /travelExpense/paymentType?fields=id,description — parallel
3. POST /travelExpense with INLINE costs:
   {employee:{id}, title, date, travelDetails:{isForeignTravel:false, isDayTrip:false,
    isCompensationFromRates:true, departureDate, returnDate, departureFrom, destination,
    departureTime:"08:00", returnTime:"18:00", purpose:<title>},
    costs:[
      {costCategory:{id:<fly>}, paymentType:{id}, date:<departureDate>, amountCurrencyIncVat:<amount>, comments:"Flybillett"},
      {costCategory:{id:<taxi>}, paymentType:{id}, date:<returnDate>, amountCurrencyIncVat:<amount>, comments:"Taxi"},
      {costCategory:{id:<mat>}, paymentType:{id}, date:<returnDate>, amountCurrencyIncVat:<total_diett>, comments:"Diett <N> dager x <rate> NOK"}
    ]}
   CRITICAL: Do NOT send "rate" field on costs — it's the currency exchange rate, not daily rate.
4. PUT /travelExpense/:deliver with query param id=<travelExpenseId>
Total: 2 write calls.
```

## Score Impact

| Metric | Before | After |
|--------|--------|-------|
| Write calls | 5 | 2 |
| Errors | 0 | 0 |
| Efficiency bonus | ~1.25x | ~2.0x |
| Normalized score | 2.5 | up to 4.0 |
| Points gained | — | +1.5 |
