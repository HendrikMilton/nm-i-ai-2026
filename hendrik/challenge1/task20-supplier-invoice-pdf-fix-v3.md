# Task 20 — Supplier Invoice from PDF: sendToLedger Missing

## Status: 2.1 points (4/6 checks). Tier 3 (max 6.0). Top team: 6.0.

## Root Cause: Same as Task 11 — sendToLedger not called

The agent creates the supplierInvoice correctly (checks 1-4 pass) but
does NOT call `PUT /ledger/voucher/{id}/:sendToLedger` afterwards.
Without this step, the voucher is unbooked (number=0) and ledger postings
are invisible to queries → checks 5-6 fail.

The system prompt ALREADY has sendToLedger as step 4 (line 55-57) but
the agent skips it in ALL Task 20 runs. This is an agent compliance issue.

## Evidence

| Run | Approach | sendToLedger? | Score |
|-----|----------|--------------|-------|
| 18:23 | POST /ledger/voucher (old) | N/A | 1/6 (0.6) |
| 18:33 | POST /ledger/voucher (old) | N/A | 1/6 (0.6) |
| 19:19 | POST /ledger/voucher (old) | N/A | 1/6 (0.6) |
| 20:47 | POST /supplierInvoice (correct!) | NO | 4/6 (2.1) |
| 20:52 | POST /supplierInvoice (correct!) | NO | 4/6 (2.1) |

Early runs used wrong endpoint (ledger/voucher). Later runs use correct
endpoint (supplierInvoice) but skip sendToLedger.

## 6 Checks

| Check | What | Status |
|-------|------|--------|
| 1 | Supplier invoice exists | PASS |
| 2 | Correct supplier linked | PASS |
| 3 | Correct invoice number/date | PASS |
| 4 | Correct amount | PASS |
| 5 | Posting on expense account (needs booked voucher) | FAIL |
| 6 | Posting on 2400 leverandorgjeld (needs booked voucher) | FAIL |

## Fix

The agent must call sendToLedger IMMEDIATELY after POST /supplierInvoice:

```
3a. POST /supplierInvoice → save voucher.id from response
3b. PUT /ledger/voucher/{voucherId}/:sendToLedger with empty body {}
    CRITICAL: This MUST happen immediately after 3a.
    WITHOUT THIS STEP, checks 5+6 WILL FAIL (0 points for postings).
```

## Sandbox Verification

Full end-to-end test with Havbris AS, account 6340, 27437 kr:

```
Step 1: GET accounts 6340, 2400               → 200 ✓
Step 2: POST /supplierInvoice                  → 201 (voucher id=609215832) ✓
Step 3: Check postings BEFORE sendToLedger     → NOT VISIBLE ✗
Step 4: PUT /ledger/voucher/:sendToLedger      → 200 (booked, number=67) ✓
Step 5: Check postings AFTER sendToLedger      → VISIBLE ✓
  6340 Lys, varme:            21 949,60 (net) / 27 437 (gross), vatType 1 (25%)
  2400 Leverandorgjeld:      -27 437,00, supplier=Havbris AS
  2710 Inngaende MVA:          5 487,40 (auto-generated)
  Kontrollsum:                     0,00
```

## UI Verification

Bilag 67-2026 in Bilagsoversikt:
- Title: "Leverandorfaktura (enkel foring)" ✓
- 6340 Lys, varme — MVA 1 — 21 949,60 ✓
- 2400 Leverandorgjeld, Havbris AS — -27 437,00 ✓
- 2710 Inngaende merverdiavgift — 5 487,40 ✓
- Kontrollsum: 0,00 ✓

## Agent Compliance Issue

The system prompt already has sendToLedger (line 55-57) but the agent
consistently skips it. Recommendation: restructure the workflow to make
sendToLedger a sub-step of the POST /supplierInvoice step, not a
separate numbered step that can be skipped:

```
3. POST /supplierInvoice with {...}
   THEN IMMEDIATELY: PUT /ledger/voucher/{voucher.id}/:sendToLedger {}
   These two calls are ONE UNIT — never skip the second.
```

## Expected Score

| Metric | Value |
|--------|-------|
| Current | 2.1 (4/6 checks) |
| After fix | 4.0-6.0 (6/6 checks, Tier 3) |
| Top team | 6.0 |
