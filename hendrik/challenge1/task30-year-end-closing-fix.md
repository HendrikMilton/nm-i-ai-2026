# Task 30 — Year-End Closing (Arsoppgjor): Two Root Causes Found

## Status: 0-1.8 points (0/6 or 4/6 checks). Tier 3 task (max 6.0). Top team: 6.0.

## Problem 1: Wrong Depreciation Account (causes 0/6)

System prompt line 210-211 says:
```
CRITICAL: ALWAYS credit the ASSET ACCOUNT DIRECTLY (e.g. 1250, 1230, 1210)
NEVER create or use accumulated depreciation accounts (1209, 1029, etc.)
```

**This is WRONG.** The task prompt explicitly says "Use account 1209 for accumulated depreciation."
The checker expects postings on 1209, not on the asset accounts.

### Evidence

| Run | Created 1209? | Depreciation credit | Score |
|-----|--------------|-------------------|-------|
| 19:25 | YES (went against instructions) | 1209 | 4/6 (1.8 pts) |
| 18:47 | YES (after retry) | 1209 | 0/6 (other issues) |
| 19:58 | NO (followed instructions) | Asset accounts | 0/6 |
| 20:24 | NO | Asset accounts | 0/6 |
| 20:54 | NO | Asset accounts | 0/6 |
| 21:26 | NO | Asset accounts | 0/6 |

### Fix

Remove lines 210-211. Replace with:
```
ALWAYS use the accumulated depreciation account specified in the task prompt (usually 1209).
If 1209 does not exist, create it: POST /ledger/account {number:1209, name:"Akkumulerte avskrivninger", vatType:{id:0}}
Credit this account, NOT the asset account directly.
```

### Sandbox verified

Bilag 3-2025 in Bilagsoversikt:
- Debit: 6010 Avskriving pa transportmidler — 20 616,67
- Credit: 1209 Akkumulerte avskrivninger — -20 616,67
- Kontrollsum: 0,00

## Problem 2: Wrong Prepaid Reversal Amount (causes checks 4+5 to fail)

The agent reverses the TOTAL prepaid amount from the prompt text, but should reverse
only the REMAINING BALANCE on account 1700.

### Evidence from 4/6 run (19:25)

```
Account 1700 postings:
  +25 750,00  Forskuddsbetalt arskostnad (original prepaid)
  -2 145,83   Periodisering maaned 1
  -2 145,83   Periodisering maaned 2
  ... (11 monthly reversals)
  -2 145,83   Periodisering maaned 11
  ─────────
  Balance: 2 145,87  (remaining = December's portion)

Agent reversed: 25 750,00 (WRONG — full total from prompt)
Should reverse:  2 145,87 (remaining balance on 1700)
```

This also causes the TAX CALCULATION to be wrong (check 5):
- Agent tax: 22% of (profit - 25750 prepaid) = 387 502,57
- Correct tax: 22% of (profit - 2145.87 prepaid) = 392 695,48
- Difference: 5 192,91

### Fix

Change the prepaid reversal instruction to:
```
5. POST prepaid reversal voucher:
   Query GET /ledger/posting on account 1700 for the year.
   SUM all postings to get the REMAINING BALANCE on 1700.
   Reverse this remaining balance (NOT the total from the prompt).
   The prompt states the original total, but monthly reversals have already
   been posted for months 1-11. Only reverse what REMAINS.
   Debit the correct expense account (6300 for rent), credit 1700.
```

### Sandbox verified

Created test data: 25750 prepaid + 11 monthly reversals = 2145.87 remaining.
Bilag 16-2025 in Bilagsoversikt:
- Debit: 6300 Leie lokale — 2 145,87
- Credit: 1700 Forskuddsbetalt leiekostnad — -2 145,87
- 1700 balance after reversal: 0,00 ✓

## Combined Impact

| Check | What | Current | After fix |
|-------|------|---------|-----------|
| 1 | Depreciation asset 1 | FAIL (wrong account) | PASS (use 1209) |
| 2 | Depreciation asset 2 | FAIL (wrong account) | PASS (use 1209) |
| 3 | Depreciation asset 3 | FAIL (wrong account) | PASS (use 1209) |
| 4 | Prepaid reversal | FAIL (wrong amount) | PASS (remaining balance) |
| 5 | Tax provision | FAIL (cascading error) | PASS (correct prepaid → correct tax) |
| 6 | Structural (dates, separate vouchers) | PASS | PASS |

## Additional Notes

- Depreciation rounding: amount/years rounded to 2 decimal places (verified: 4/6 run checks 1-3 passed with this rounding)
- Account 1209 creation: POST /ledger/account with {number, name, vatType:{id:0}} — do NOT include type field (causes 422)
- Account 8700 creation: same — {number, name, vatType:{id:0}} without type field
- All vouchers dated 2025-12-31 (year-end)
- Each depreciation as separate bilag (prompt requirement)
- Tax formula: taxableProfit = -(existingP&L + totalDepreciation + remainingPrepaid)

## Expected Score

| Metric | Value |
|--------|-------|
| Current best | 1.8 (4/6 checks, one lucky run) |
| After fix | 4.0-6.0 (6/6 checks, Tier 3) |
| Top team | 6.0 |
