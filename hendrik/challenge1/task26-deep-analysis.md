# Task 26 — Deep Analysis & Efficiency Fix

**Date:** 2026-03-22
**Analysts:** Gabriel + Claude
**Current score:** 4.0/6.0 (6/6 checks pass, efficiency 1.33)
**Task:** Monthly closing — post accrual reversal, depreciation, salary accrual

---

## Current state

Task 26 already passes ALL 6 checks consistently. The problem is **efficiency only** — too many API calls reduce the efficiency multiplier from 2.0 (max) to 1.33.

| Attempt | Score | Norm | Steps | API Calls | Errors |
|---------|-------|------|-------|-----------|--------|
| 19-37 | 10/10 | 4.0 | 9 | 14 | 0 |
| 20-42 | 10/10 | 4.0 | 7 | 13 | 0 |
| 20-56 | 10/10 | 4.0 | 7 | 17 | 0 |
| 09-11 | 10/10 | 4.0 | 7 | 15 | 0 |

All get exactly 4.0 regardless of call count (13-17). Tier 3 efficiency: 4.0/3 = 1.33.

## Root cause: too many GET calls

The agent makes 10-14 individual `GET /ledger/account?number=XXXX` calls to look up account IDs. Each account is queried separately.

Typical call breakdown:
- 10-14 × GET /ledger/account (individual lookups)
- 0-2 × GET /ledger/posting (salary amount lookup)
- 3 × POST /ledger/voucher (accrual, depreciation, salary)
- **Total: 13-17 calls**

## Fix: batch account lookup

Replace all individual account lookups with ONE call:
```
GET /ledger/account?fields=id,number&count=1000
```

Returns all accounts (533 in sandbox) in one response. Agent finds needed IDs from the JSON.

### Optimized flow:
1. GET /ledger/account?fields=id,number&count=1000 (ALL accounts, 1 call)
2. GET /ledger/posting (salary amount, only if not specified in prompt, 0-1 call)
3. POST /ledger/voucher × 3 (accrual, depreciation, salary — in parallel)
- **Total: 4-5 calls**

## Sandbox verification

Tested the full 4-call flow in sandbox:
- 1 GET returned all 533 accounts
- 3 POST vouchers created successfully
- Verified in Tripletex UI (Bilag #87, #88, #89):
  - #87 Periodisering: 6300 +4,800 / 1710 -4,800 ✓
  - #88 Avskrivning: 5000 +3,000 / 1200 -3,000 ✓
  - #89 Lønnsavsetning: 5000 +45,000 / 2900 -45,000 ✓
  - All kontrollsum: 0.00 ✓

## Efficiency comparison (other Tier 3 tasks)

| Task | Best Score | Efficiency | API Calls |
|------|-----------|------------|-----------|
| 27 | 6.00 | 2.00 | 10 |
| 25 | 4.80 | 1.60 | 9 |
| 26 | 4.00 | 1.33 | 13-17 |

Fewer calls = higher efficiency. Reducing Task 26 from 13-17 to 4-5 calls should push score toward 5-6 points.

## System prompt change

Replace step 1:
```
1. GET all accounts mentioned in the task in parallel. Use the accounts as-is.
```

With:
```
1. GET /ledger/account?fields=id,number&count=1000 — fetches ALL accounts in ONE call.
   Find the needed account IDs by matching account numbers from the response.
   Do NOT make individual GET /ledger/account?number=XXXX calls.
```
