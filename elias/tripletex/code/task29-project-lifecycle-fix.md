# Task 29 — Complete Project Lifecycle — Fix Report

**Date:** 2026-03-21
**Current score:** 1.64 (raw 6/11, 4/7 checks passed)
**Potential score:** ~4.50
**Impact:** +2.86 points
**Tier:** 3 (x3 multiplier)

---

## Task Description

"Execute the complete project lifecycle for 'System Upgrade Windmill' (Windmill Ltd):
1. Budget 336750 NOK
2. Log time: Grace Walker 46h, Edward Smith 90h
3. Register supplier cost 60750 NOK from Greenfield Ltd
4. Create customer invoice for the project"

## Scoring Breakdown

| Check | Result | Likely meaning |
|-------|--------|---------------|
| Check 1 | PASSED | Project/customer setup |
| Check 2 | PASSED | Timesheet entry (Edward 90h) |
| Check 3 | **FAILED** | Supplier cost linked to project |
| Check 4 | PASSED | Invoice created |
| Check 5 | **FAILED** | Timesheet entry (Grace 46h) or supplier amount |
| Check 6 | PASSED | Order/invoice structure |
| Check 7 | **FAILED** | Unknown — possibly description or amount |

---

## Root Cause 1: Missing project:{id} on supplier cost (CRITICAL)

### What the agent did

```json
POST /ledger/voucher postings: [
  {account:{id:4300}, supplier:{id}, amountGross:60750, ...}  // NO project:{id}!
  {account:{id:2400}, supplier:{id}, amountGross:-60750, ...}
]
```

### What the system prompt says (line 100-102)

```
Register supplier cost via POST /ledger/voucher with postings that INCLUDE project:{id}
on the debit posting
```

The agent ignored this instruction. The supplier cost exists but is NOT linked to the project.

### UI Verification

Created two test vouchers on sandbox — one with `project:{id}`, one without:

- **WITH project (27-2026):** Dimensjon column shows "1 Testprosjekt" + supplier name — project is linked
- **WITHOUT project (26-2026):** Dimensjon column shows only supplier name — no project reference

The scorer checks whether supplier costs are associated with the project via the `project` field on postings.

### Fix

The system prompt already has the correct instruction. The agent just doesn't follow it. Make it more explicit:

```
4. Register supplier cost — CRITICAL: the debit posting MUST include project:{id}
   Without project:{id}, the cost is not linked to the project and the check FAILS.
```

---

## Root Cause 2: Timesheet entries sent in PARALLEL (causes 409)

### What happened

Step 4: Agent sent both timesheet entries simultaneously:
- POST /timesheet/entry (Grace, 46h) → **409 Duplicate entry**
- POST /timesheet/entry (Edward, 90h) → 201 Created

The system prompt (line 99) says: "Log timesheet entries ONE AT A TIME sequentially (parallel causes 409)"

Grace's entry was eventually created in Step 8, but it took 4 extra diagnostic GET calls to recover, adding to the API call count and efficiency penalty.

### Fix

Make sequential requirement stronger:

```
3. Log timesheet entries ONE AT A TIME — NEVER in parallel.
   Send the first POST, wait for 201, then send the next.
   Parallel causes 409 "Duplicate entry" error.
```

---

## Possible Root Cause 3: Supplier cost amount interpretation

Task says "supplier cost of 60750 NOK." The agent used this as `amountGross` (incl VAT):
- amountGross = 60,750 (incl VAT)
- amount = 48,600 (net, after 25% VAT deducted)

But in Norwegian accounting, "kostnad" (cost) typically means the cost to the company = net amount (excl VAT), because input VAT is deductible.

If the scorer expects 60,750 as the NET cost:
- amountGross should be 60,750 × 1.25 = 75,937.50
- amount would be 60,750

This ambiguity could explain one of the failed checks. Cannot verify without another submission.

---

## API Call Analysis

**Total: 23 calls, 2 errors**

| Step | Calls | Purpose | Needed? |
|------|-------|---------|---------|
| 1 | 7 GET | Customer, supplier, 2 employees, project, activity, bank account | YES (all parallel) |
| 2 | 4 GET | Full employee details + accounts 4300, 2400 | YES |
| 3 | 2 PUT | Update employees (dateOfBirth, userType) | YES |
| 4 | 3 POST | 2 timesheet entries + supplier voucher (sent in parallel!) | PARTIAL — timesheets should be sequential |
| 5 | 1 GET | Check Grace's timesheet (after 409) | WASTED |
| 6 | 1 GET | Retry check Grace's timesheet | WASTED |
| 7 | 1 GET | Another check | WASTED |
| 8 | 1 POST | Retry Grace's timesheet (succeeds) | NEEDED (recovery) |
| 9 | 1 POST | Create order | YES |
| 10 | 1 POST | Create order line | YES |
| 11 | 1 POST | Create invoice | YES |

**Ideal flow: 17 calls, 0 errors** (remove 4 diagnostic GETs from 409 recovery, send timesheets sequentially)

---

## Other Issues Noted

### Employee userType stays null
Agent PUT with `userType:"STANDARD"` but response shows `userType:null`. Tripletex doesn't allow changing userType via the employee token. However, timesheet entries still succeeded for both employees, so this isn't blocking.

### Order line description
Agent used: `"System Upgrade Windmill - Project Invoice"`
System prompt says: `description:"Project invoice"`
Could be a minor check failure.

---

## System Prompt Changes Needed

### 1. Emphasize project:{id} on supplier cost

Current (line 100):
```
Register supplier cost via POST /ledger/voucher with postings that INCLUDE project:{id} on the debit posting
```

Change to:
```
4. CRITICAL: Register supplier cost via POST /ledger/voucher.
   The debit posting MUST include project:{id} — without it the cost is not linked to the project.
   {date, description, postings: [
     {date, description, account:{id:expense_4300}, supplier:{id}, project:{id}, amountGross:..., amountGrossCurrency:..., vatType:{id:1}, invoiceNumber:"SUP-001", row:1},
     {date, description, account:{id:2400}, supplier:{id}, amountGross:<negative>, amountGrossCurrency:<negative>, row:2}
   ]}
```

### 2. Reinforce sequential timesheet entries

Current (line 99):
```
Log timesheet entries ONE AT A TIME sequentially (parallel causes 409)
```

Change to:
```
3. Log timesheet entries ONE AT A TIME — send first entry, wait for 201, then send next.
   NEVER send timesheet entries in parallel — it causes 409 "Duplicate entry" errors.
```

### 3. Use exact order line description

```
POST /order/orderline with {order:{id}, description:"Project invoice", count:1, ...}
```
