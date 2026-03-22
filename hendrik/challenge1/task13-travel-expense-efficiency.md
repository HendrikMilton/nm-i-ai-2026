# Task 13 — Travel Expense: Efficiency Fix (2.4 → 4.0)

**Date:** 2026-03-22
**Impact:** Task 13 scores 2.4/4.0. All 6 checks pass (8/8 raw). Issue is purely efficiency.
**Status:** FIX CONFIRMED in sandbox

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

## Sandbox Verification

Tested in sandbox: `POST /travelExpense` with `costs` array containing 3 cost items.
- All 3 costs created in one call (201)
- `PUT /travelExpense/:deliver` succeeded (200)
- Travel expense delivered with all costs, correct amounts

## Fix

In `system-prompt.ts`, change the Travel expense workflow from:

```
1. GET /employee?firstName=X&lastName=Y
2. POST /travelExpense with {employee, title, date, travelDetails}
3. GET /travelExpense/costCategory and GET /travelExpense/paymentType — parallel
4. For each cost ONE AT A TIME: POST /travelExpense/cost
5. PUT /travelExpense/:deliver
```

To:

```
1. GET /employee?email=X (or firstName/lastName)
2. GET /travelExpense/costCategory and GET /travelExpense/paymentType — parallel
3. POST /travelExpense with inline costs:
   {employee:{id}, title, date, travelDetails:{...},
    costs:[
      {costCategory:{id}, paymentType:{id}, date, amountCurrencyIncVat, comments},
      {costCategory:{id}, paymentType:{id}, date, amountCurrencyIncVat, comments},
      ...
    ]}
4. PUT /travelExpense/:deliver with query param id=<travelExpenseId>
```

Key changes:
- Move costCategory/paymentType GETs BEFORE the travelExpense POST (need IDs for inline costs)
- Include all costs in the POST body
- Total: 2 writes instead of 5

## Score Impact

| Metric | Before | After |
|--------|--------|-------|
| Write calls | 5 | 2 |
| Errors | 0 | 0 |
| Efficiency bonus | ~1.2x | ~2.0x |
| Normalized score | 2.4 | up to 4.0 |
| Points gained | — | +1.6 |
