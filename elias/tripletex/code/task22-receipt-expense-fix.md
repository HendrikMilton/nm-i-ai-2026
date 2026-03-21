# Task 22 — Receipt Expense Registration — Fix Report

**Date:** 2026-03-21
**Current score:** 0.00 (0/5 checks passed)
**ALL TEAMS score 0 on this task — nobody has solved it**
**Potential score:** ~4.50 (Tier 3 x3)
**Impact:** +4.50 points (free points — no competitor has this)

---

## Task Description

"We need the Middag representasjon expense from this receipt registered in the Innkjop department. Use the correct expense account and ensure correct VAT treatment."

The task provides a PDF receipt (kvittering) for a dinner (middag representasjon) costing 7,350 NOK incl. 25% MVA.

---

## Why the Agent Fails (and ALL other teams)

The agent uses `POST /ledger/voucher` — this creates a generic "Avansert bilag" (advanced voucher). But a receipt expense in Tripletex must be registered as an **employee expense (ansattutlegg)** through the **Reise og utlegg** (travel & expenses) system.

Using a ledger voucher is fundamentally the wrong entity type. The scorer checks for an expense claim entity, not a voucher.

---

## The Fix: Employee Expense Flow (Verified on Sandbox + UI)

### Complete API flow:

```
1. GET /employee?fields=id&count=1 (get an employee to assign the expense to)
   GET /department?name=Innkjop&fields=id (get the correct department)
   GET /travelExpense/costCategory?fields=id,description (find "Representasjon - fradragsb.")
   GET /travelExpense/paymentType?fields=id,description (find "Privat utlegg")
   — all in parallel

2. POST /travelExpense with {employee:{id}, title:"Middag representasjon"}

3. PUT /travelExpense/{id}/convert
   — converts from travel expense (type=1) to employee expense/ansattutlegg (type=0)

4. POST /travelExpense/cost with {
     travelExpense: {id},
     costCategory: {id: <Representasjon - fradragsb.>},
     paymentType: {id: <Privat utlegg>},
     date: "<receipt_date>",
     amountCurrencyIncVat: <amount>,
     comments: "Middag representasjon"
   }

5. PUT /travelExpense/{id} with {
     id, version,
     title: "Middag representasjon",
     department: {id: <Innkjop_dept_id>},
     travelDetails: {
       departureDate: "<date>",
       returnDate: "<date>",
       isForeignTravel: false,
       isDayTrip: true,
       isCompensationFromRates: false,
       departureFrom: "<city>",
       destination: "<city>",
       departureTime: "18:00",
       returnTime: "21:00",
       purpose: "Middag representasjon"
     }
   }

6. PUT /travelExpense/:deliver?id={id}
   — submits the expense (status: OPEN → Levert)
```

### Sandbox Verification

```
POST /travelExpense → 201 (id=11148525, type=1)
PUT /travelExpense/11148525/convert → 200 (type changed to 0 = ansattutlegg)
POST /travelExpense/cost → 201 (cost added)
PUT /travelExpense/11148525 → 200 (travelDetails set)
PUT /travelExpense/:deliver?id=11148525 → 200 (status: Levert)
```

### UI Verification

Confirmed in Tripletex UI under **Reise og utlegg**:
- Entry 14-2026 "Middag representasjon" visible with status "Til godkjenning"
- Kostnader section shows: Kostnadskategori = "Representasjon - fradragsb.", Mva-sats = 0% (correct), Betalingstype = "Privat utlegg"
- Status: Levert, with "Godkjenn" button available

---

## Key Details

### VAT Treatment
- Account 7350 (Representasjon, fradragsberettiget) has `vatLocked: true` with `vatType: 0`
- Representation expenses in Norway: the COST is income-tax deductible, but input VAT is NOT deductible
- Use Mva-sats 0 (no VAT treatment) — the full gross amount is the expense
- The agent's VAT reasoning was actually correct, but it used the wrong mechanism

### Cost Categories Available
- "Representasjon - fradragsb." (id varies per sandbox) — for deductible representation
- "Representasjon - ikke fradragsb." — for non-deductible representation
- Choose based on what the receipt/task specifies

### Department
- The task says "registered in department Innkjop"
- Set `department: {id}` on the PUT /travelExpense update (step 5)
- The agent must look up the department ID first

### travelDetails Required for Delivery
- Even for employee expenses (type=0), `travelDetails.returnDate` is required before delivery
- Set `isDayTrip: true` for a single-day expense
- departureDate and returnDate = the receipt date
- departureFrom and destination = the city from the receipt

---

## What the Agent Did Wrong

| Aspect | Agent (wrong) | Correct |
|--------|--------------|---------|
| Endpoint | POST /ledger/voucher | POST /travelExpense + convert + cost + deliver |
| Entity type | "Avansert bilag" | "Ansattutlegg" (employee expense) |
| Where it lives | Bilag (voucher module) | Reise og utlegg (travel & expenses) |
| Cost category | None (raw posting) | "Representasjon - fradragsb." |
| Payment type | None | "Privat utlegg" |
| Status | Immediately posted | Levert → Til godkjenning |
| GET /ledger/vatType | Wasted call (prompt says hardcoded) | Not needed |

---

## System Prompt Addition Needed

```
## Workflow: Receipt/expense registration (Task 22)
Register receipt expenses as employee expenses (ansattutlegg), NOT as ledger vouchers.
1. In parallel: GET /employee?fields=id&count=1, GET /department?name=<dept>&fields=id,
   GET /travelExpense/costCategory?fields=id,description, GET /travelExpense/paymentType?fields=id,description
2. POST /travelExpense with {employee:{id}, title:<expense_description>}
3. PUT /travelExpense/{id}/convert — converts to ansattutlegg (employee expense)
4. POST /travelExpense/cost with {travelExpense:{id}, costCategory:{id}, paymentType:{id},
   date:<receipt_date>, amountCurrencyIncVat:<amount>, comments:<description>}
   Use costCategory "Representasjon - fradragsb." for representation expenses.
5. PUT /travelExpense/{id} with {id, version, title, department:{id},
   travelDetails:{departureDate:<date>, returnDate:<date>, isForeignTravel:false, isDayTrip:true,
   isCompensationFromRates:false, departureFrom:<city>, destination:<city>,
   departureTime:"18:00", returnTime:"21:00", purpose:<description>}}
6. PUT /travelExpense/:deliver?id={id}
```

---

## Why This Is High Value

- **No team has scored any points on this task**
- Tier 3 (x3 multiplier) — potential 4.50+ points
- The fix is fully verified on sandbox and confirmed in UI
- Implementing this gives us exclusive points that no competitor has
