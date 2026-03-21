# Task 24 — Fix Ledger Errors (Correction Vouchers)

**Date:** 2026-03-21
**Current score:** 2.25 (3/4 checks) | **Competitor best:** unknown
**Tier:** 3 (estimated, max 6.0)
**Runs analyzed:** 3 (15:37 score 2.25, 15:50 expired token, 16:16 score 0.0)

---

## Task Description (parameterized)

Find 4 errors in the general ledger for January-February 2026 and correct them with correction vouchers. The 4 error types are always:

1. **Wrong account** — posting on account X instead of Y, amount Z kr
2. **Duplicate voucher** — duplicate posting on account X, amount Z kr
3. **Missing VAT line** — account X, amount excl. Z kr, missing VAT on 2710
4. **Wrong amount** — account X, Z1 kr posted instead of Z2 kr

Accounts, amounts, and values are different each run.

---

## Root Cause Analysis

### Run 1 (15:37, score 2.25, 3/4 checks)
- All 4 corrections used **vatType:0** regardless of original vatType
- Wrong-account correction moved 6200 NET instead of 4960 NET (because original had vatType:1)
- MVA correction added full 1937.50 to 2710 instead of the difference 387.50
- 2400 posting hit 422 (missing supplier), then retried with supplier — 1 wasted write

### Run 2 (16:16, score 0/4)
- Used **vatType:1** on wrong-account correction (OK for that account)
- Used **vatType:1** on duplicate reversal — some accounts are **locked to vatType:0** causing 422
- Inconsistent vatType handling across corrections broke everything

### Core bugs
1. Agent doesn't read the original voucher's vatType before correcting
2. Agent doesn't calculate the DIFFERENCE for MVA — posts the full amount
3. Agent doesn't look up the supplier from the original voucher BEFORE posting to 2400
4. Agent doesn't know about `PUT /:reverse` for duplicate handling

---

## Correct Approach (Verified on Sandbox + UI)

### Error 1: Wrong Account
**Use the SAME vatType as the original posting.**

```
POST /ledger/voucher
  Row 1: wrong_account, amountGross=-<amount>, vatType:{id:<original_vatType>}
  Row 2: correct_account, amountGross=+<amount>, vatType:{id:<original_vatType>}
```

Tripletex auto-splits net/VAT. With vatType:1 and amountGross=6200:
- Wrong account: -4960 net (correct reversal)
- Correct account: +4960 net
- 2710: -1240 and +1240 (cancel out, net zero VAT change)

**Sandbox test:** Voucher #33 confirmed in UI.

### Error 2: Duplicate Voucher
**Use `PUT /ledger/voucher/{id}/:reverse?date=YYYY-MM-DD`**

- 1 write call (not 2 like manual reversal)
- Auto-generates reversed postings with correct amounts and vatTypes
- Sets `reverseVoucher` field linking to original
- Description auto-generated: "Reversering av bilag X-YYYY"

The agent must first find the duplicate voucher ID by scanning postings.

**Sandbox test:** Voucher #36 confirmed in UI — perfect mirror of #35.

### Error 3: Missing VAT Line
**Post a 3-line correction voucher with the DIFFERENCES.**

The original voucher treated amount_excl as gross (incl VAT). The correction must adjust:
- Expense account: +difference_net
- 2710 (MVA): +difference_VAT
- 2400 (supplier debt): -(difference_net + difference_VAT)

Formula:
```
correct_net = amount_excl (from prompt)
correct_VAT = amount_excl * 0.25
correct_gross = amount_excl * 1.25

current_net = original posting "amount" field
current_VAT = original 2710 posting "amount" field

adjustment_expense = correct_net - current_net
adjustment_VAT = correct_VAT - current_VAT
adjustment_supplier = -(adjustment_expense + adjustment_VAT)
```

Example (from our logs):
- Prompt says: excl. 7750 kr
- Original: net=6200, VAT=1550 (treated 7750 as gross)
- Correct: net=7750, VAT=1937.50
- Correction: expense +1550, 2710 +387.50, 2400 -1937.50

**CRITICAL:** The 2400 posting MUST include `supplier:{id}` from the original voucher. Look it up FIRST.

**Sandbox test:** Voucher #32 confirmed in UI — 3 lines, kontrollsum 0.00.

### Error 4: Wrong Amount
**Use the SAME vatType as the original posting, post the gross DIFFERENCE.**

```
POST /ledger/voucher
  Row 1: expense_account, amountGross=-(wrong - correct), vatType:{id:<original_vatType>}
  Row 2: contra_account, amountGross=+(wrong - correct), vatType:{id:0}
```

If original has VAT (vatType:1), Tripletex auto-splits the net/VAT proportionally:
- amountGross=-3700 with vatType:1 -> net=-2960, VAT=-740

If original has no VAT (vatType:0), it's a simple net adjustment.

**Sandbox tests:** Voucher #37 (with VAT) and #38 (without VAT) both confirmed in UI.

---

## Why vatType Matching is Critical

| Approach | Result |
|----------|--------|
| vatType:0 on VAT posting | Moves GROSS as NET — wrong account balance |
| vatType:1 on non-VAT posting | 422 error if account is locked to vatType:0 |
| vatType matching original | Correct net/VAT split, auto-handled by Tripletex |

**Rule: ALWAYS read the original posting's vatType and use the same one.**

---

## Recommended System Prompt Workflow

```
## Workflow: Fix ledger errors (correction vouchers)
1. GET /ledger/posting?dateFrom=YYYY-01-01&dateTo=YYYY-02-28&count=1000
   &fields=id,date,description,account(id,number,name),amount,amountGross,
   vatType(id,name,percentage),voucher(id,number,description),supplier(id)
   Read ALL postings. Match errors from the prompt by account number and amount.

2. For EACH error, note from the original posting:
   - vatType id (MUST match in correction)
   - supplier id (needed for 2400 postings)
   - amount (net) vs amountGross
   - voucher id (needed for /:reverse)

3. ERROR TYPE: Wrong account
   POST /ledger/voucher with 2 postings:
   - wrong_account: amountGross=-<amount>, vatType:{id:<ORIGINAL>}
   - correct_account: amountGross=+<amount>, vatType:{id:<ORIGINAL>}

4. ERROR TYPE: Duplicate voucher
   PUT /ledger/voucher/{voucher_id}/:reverse?date=<correction_date>
   (1 write call, auto-handles everything)

5. ERROR TYPE: Missing VAT line
   Read original postings to get current net and current VAT on 2710.
   Calculate: correct_net = amount_excl, correct_VAT = amount_excl * 0.25
   POST /ledger/voucher with 3 postings:
   - expense_account: amountGross=+(correct_net - current_net), vatType:{id:0}
   - 2710: amountGross=+(correct_VAT - current_VAT), vatType:{id:0}
   - 2400: amountGross=-(sum of above), vatType:{id:0}, supplier:{id:<from_original>}

6. ERROR TYPE: Wrong amount
   diff = wrong_amount - correct_amount (from prompt)
   POST /ledger/voucher with 2 postings:
   - expense_account: amountGross=-diff, vatType:{id:<ORIGINAL>}
   - contra_account: amountGross=+diff, vatType:{id:0}, supplier:{id} if 2400

CRITICAL RULES:
- ALWAYS read original vatType before posting corrections
- ALWAYS include supplier:{id} on 2400 postings (look up from original)
- Use /:reverse for duplicates (1 write vs 2)
- For MVA corrections, calculate the DIFFERENCE, not the full VAT amount
- Post all corrections in parallel after gathering all data
```

---

## Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Checks passing | 3/4 | 4/4 |
| Write errors (422) | 1 | 0 |
| Write calls | 5 | 4 (using /:reverse saves 1) |
| Score | 2.25 | 4.0-4.5+ |

Potential gain: **+2.0 to +2.25 points**.
