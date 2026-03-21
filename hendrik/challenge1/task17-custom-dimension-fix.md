# Task 17 — Custom Accounting Dimension + Voucher

**Date:** 2026-03-21
**Current score:** 3.50 | **Competitor best:** 3.50 (TIED)
**Tier:** 2 (max 4.0)
**Tries analyzed:** 11+ runs across logs/ and old_logs/

---

## Task Description (parameterized)

Create a custom accounting dimension with a given name (e.g. "Prosjekttype", "Region", "Produktlinje") and two values (e.g. "Internt"/"Forskning"). Then post a voucher on a specified expense account for a given amount, linked to one of the dimension values.

Example prompt:
> "Crie uma dimensao contabilistica personalizada "Prosjekttype" com os valores "Internt" e "Forskning". Em seguida, lance um documento na conta 7000 por 13900 NOK, vinculado ao valor de dimensao "Internt"."

Languages seen: Portuguese, French, Spanish, English, Norwegian.

---

## What the Agent Does (Best Run — 13:45:00Z)

| Step | Action | Write? | Status |
|------|--------|--------|--------|
| 1 | POST /ledger/accountingDimensionName `{dimensionName, active:true}` | YES | 201 |
| 1 | GET /ledger/account?number=7000 | no (free) | 200 |
| 2 | POST /ledger/accountingDimensionValue `{displayName:"Forskning", dimensionIndex:1}` | YES | 201 |
| 2 | POST /ledger/accountingDimensionValue `{displayName:"Internt", dimensionIndex:1}` | YES | 201 |
| 3 | GET /ledger/account?number=2900 | no (free) | 200 |
| 4 | POST /ledger/voucher with `freeAccountingDimension1:{id}` on debit posting | YES | 201 |

**Total: 4 writes, 0 errors, 6 API calls. Execution: 35s.**

All checks appear to pass — dimension name, both values, voucher with correct account/amount/dimension-link all verified in API responses.

---

## Why Score is 3.50 (Not 4.0)

Score formula: `correctness x tier x efficiency_bonus`

- Correctness: 1.0 (all checks pass)
- Tier: 2
- Efficiency bonus: 1.75x (not max 2.0x)

**The bottleneck is efficiency.** 4 write calls gives efficiency multiplier ~1.75x, not the max 2.0x.

This is confirmed by competitor data: **nobody has scored higher than 3.50**, meaning all teams hit the same 4-write ceiling.

---

## Can We Reduce Writes?

The 4 writes are:
1. POST /ledger/accountingDimensionName — **required** (create dimension)
2. POST /ledger/accountingDimensionValue — **required** (value 1)
3. POST /ledger/accountingDimensionValue — **required** (value 2)
4. POST /ledger/voucher — **required** (create voucher)

### API Endpoints Checked

| Endpoint | Can batch-create? |
|----------|-------------------|
| POST /ledger/accountingDimensionValue | Single value only |
| PUT /ledger/accountingDimensionValue/list | "Update" only per spec |
| POST /ledger/accountingDimensionName | Single dimension, no nested values |

**No batch POST endpoint exists for dimension values.**

### Potential Optimization: PUT /list for Creation

The PUT /ledger/accountingDimensionValue/list endpoint officially says "Update accounting dimension values", but some Tripletex PUT endpoints support upsert (create-or-update). If PUT /list can CREATE new values:

```
Step 1: POST /ledger/accountingDimensionName (1 write)
Step 2: PUT /ledger/accountingDimensionValue/list [{displayName:"Internt", dimensionIndex:1}, {displayName:"Forskning", dimensionIndex:1}] (1 write)
Step 3: POST /ledger/voucher with freeAccountingDimension1 (1 write)
= 3 writes total
```

**This could push efficiency from 1.75x to ~1.83-2.0x, giving score 3.67-4.0.**

---

## Comparison: Clean vs Messy Runs

| Run | Writes | Errors | Extra calls | Key difference |
|-----|--------|--------|-------------|----------------|
| 13:45 (best) | 4 | 0 | 1 GET (2900) | Used 2900 as contra |
| 14:20 (old) | 4 | 0 | 0 | Used 1920 as contra |
| 14:39 (old) | 4 | 0 | 0 | Used 1920, parallel steps |
| 13:46 (old) | 7 | 2 | 3 GETs | Tried wrong field names, needed PUT to add dimension after |

Old messy runs tried `accountingDimensionValues` (wrong field, 422) and had to use PUT /voucher to add the dimension after creation. The system prompt fix (using `freeAccountingDimension1`) already solved this.

---

## Action Items

### 1. TEST on sandbox: PUT /list for dimension value creation
```bash
# After creating dimension (note dimensionIndex from response):
curl -s -X PUT -H "Authorization: $AUTH" -H "Content-Type: application/json" \
  "$SANDBOX_URL/ledger/accountingDimensionValue/list" \
  -d '[{"displayName":"TestA","dimensionIndex":1,"active":true},{"displayName":"TestB","dimensionIndex":1,"active":true}]'
```

If this returns 200/201 with created values: **update the system prompt workflow** to use PUT /list instead of 2x POST.

### 2. Minor prompt improvement (regardless of PUT /list result)
Current workflow step 3 says "Look up accounts" but doesn't specify which contra account. The agent sometimes picks 2900 (Forskudd fra kunder) which is semantically wrong. Add guidance:

```
4. POST /ledger/voucher — use 1920 (Bankinnskudd) as contra account for the credit posting.
   Set freeAccountingDimension1/2/3:{id} on the DEBIT posting only.
```

### 3. No correctness fixes needed
All checks pass. The existing system prompt workflow handles this task correctly.

---

## Risk Assessment

| Scenario | Expected score | Gain |
|----------|---------------|------|
| Current (4 writes) | 3.50 | 0 |
| PUT /list works (3 writes) | 3.67-4.00 | +0.17 to +0.50 |
| PUT /list fails | 3.50 (no change) | 0 |

**Low risk, low-to-medium reward.** Worth testing PUT /list but don't prioritize over tasks with bigger point gaps.
