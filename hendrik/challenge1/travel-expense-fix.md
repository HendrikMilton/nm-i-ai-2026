# Travel Expense — Root Cause Analysis & Proposed Fix

**Date:** 2026-03-21
**Impact:** 2.5 pts per task (currently 5.5/8, potential 8/8)
**Status:** ROOT CAUSE FOUND — cannot fully verify on our sandbox (expired rate categories)

---

## Problem

Travel expense tasks score 5.5/8 — Check 3 and Check 6 consistently fail.

- **Check 3:** Per diem (diett/dagpenger) registered incorrectly
- **Check 6:** Travel expense not delivered/submitted

## Root Cause — Check 3: Per diem uses wrong API

The agent registers per diem as a regular cost:
```
POST /travelExpense/cost  with costCategory "Mat"  ← WRONG
```

The UI shows per diem is a **separate section** ("Kostgodtgjørelse") with its own fields (rate category, meal deductions for breakfast/lunch/dinner, overnight accommodation type). The correct API is:
```
POST /travelExpense/perDiemCompensation  ← CORRECT
```

### UI evidence

The "Ny reiseregning" form has 4 distinct sections:

| UI Section | API Endpoint | What goes here |
|---|---|---|
| **Kostgodtgjørelse** | `POST /travelExpense/perDiemCompensation` | Per diem / meals (diett) |
| **Nattillegg** | `POST /travelExpense/accommodationAllowance` | Night allowance |
| **Kjøregodtgjørelse** | `POST /travelExpense/mileageAllowance` | Driving/mileage |
| **Kostnader** | `POST /travelExpense/cost` | Actual receipts (flight, taxi, hotel) |

Flight and taxi correctly go under "Kostnader". But per diem belongs under "Kostgodtgjørelse" — a fundamentally different entity.

## Root Cause — Check 6: Missing deliver step

The agent leaves the travel expense in **OPEN** state. The response even includes the deliver action:
```json
"actions": [{"rel": "DELIVER", "type": "PUT", "href": ".../expense/:deliver", "id": 11145894}]
```

The fix is to call:
```
PUT /travelExpense/{id}/:deliver
```

## Proposed Correct Flow

```
1. GET /employee?firstName=X&lastName=Y
2. POST /travelExpense with body:
   {
     "employee": {"id": <emp_id>},
     "title": "Trip title",
     "date": "2026-03-21",
     "travelDetails": {
       "departureDate": "2026-03-21",
       "returnDate": "2026-03-24",
       "purpose": "Client visit",
       "destination": "Trondheim"
     }
   }
3. GET /travelExpense/perDiemCompensation/rateCategory  (or GET /travelExpense/rateCategory?type=PER_DIEM)
   → find a valid rate category for the travel dates
4. GET /travelExpense/costCategory  +  GET /travelExpense/paymentType
5. POST /travelExpense/perDiemCompensation with body:
   {
     "travelExpense": {"id": <te_id>},
     "rateCategory": {"id": <valid_rate_cat_id>},
     "count": <num_days>,
     "rate": <daily_rate>,
     "amount": <total>,
     "location": "<destination>",
     "overnightAccommodation": "NONE"
   }
6. POST /travelExpense/cost  (for each actual expense: flight, taxi, hotel)
   {
     "travelExpense": {"id": <te_id>},
     "costCategory": {"id": <fly/taxi/etc>},
     "paymentType": {"id": <privat_utlegg_id>},
     "date": "2026-03-21",
     "amountCurrencyIncVat": <amount>,
     "comments": "Flight ticket"
   }
7. PUT /travelExpense/{id}/:deliver   ← NEW — submits the report
```

## Why Lucy Walker scored 8/8 but Inês/Paul scored 5.5/8

All three used identical approach (cost with "Mat" category, no deliver). The difference is that **competition sandboxes have different check sets per task variant**. Lucy's task likely had simpler checks that didn't validate per diem method specifically.

## Sandbox Limitation

Our sandbox has ALL rate categories expired (toDate: "2008-05-01"). This means `POST /travelExpense/perDiemCompensation` fails with "Reiseregningens dato samsvarer ikke med valgt satskategori" on our sandbox.

Competition sandboxes will have valid rate categories. The agent should:
1. `GET /travelExpense/rateCategory?type=PER_DIEM&fields=id,name,fromDate,toDate`
2. Find a category where the travel date falls within fromDate–toDate range
3. Use that category ID

## Summary of Changes Needed in system-prompt.ts

1. Create travel expense WITH `travelDetails` (departureDate, returnDate, purpose, destination)
2. Use `POST /travelExpense/perDiemCompensation` for per diem — NOT `POST /travelExpense/cost` with "Mat"
3. Look up valid rateCategory at runtime
4. Add `PUT /travelExpense/{id}/:deliver` as final step
5. Keep `POST /travelExpense/cost` for actual expenses (flight, taxi, hotel) — this part is correct
