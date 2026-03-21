# Monthly Closing (Task 26) — Analysis & Fixes

**Date:** 2026-03-21
**Score:** 4/6 (Hendrik note: "can be 6")
**Task type:** NEW Tier 3 — monthly closing with accrual, depreciation, salary provision

---

## Task Prompt (Spanish)

"Realice el cierre mensual de marzo de 2026:
1. Registre la periodificación (3950 NOK por mes de la cuenta 1720 a gasto)
2. Contabilice la depreciación mensual: costo 153900 NOK, vida útil 9 años, lineal a cuenta 6010
3. Verifique que el balance de saldos sea cero
4. Registre una provisión salarial (débito 5000, crédito 2900)"

## What the Agent Did

- 18 API calls, 0 errors
- 9 GET /ledger/account (several unnecessary)
- 3 POST /ledger/voucher (accrual, depreciation, salary provision)
- 3 GET /ledger/posting + 3 GET /ledger/voucher (verification — unnecessary)

### Voucher 1: Accrual
- Debit 7700 (Styre- og bedriftsforsamlingsmøter): +3950
- Credit 1720 (Andre depositum): -3950

### Voucher 2: Depreciation
- Debit 6010 (Avskriving på transportmidler): +1425 (153900/9/12)
- Credit 1200 (Maskiner og anlegg): -1425

### Voucher 3: Salary provision
- Debit 5000 (Lønn til ansatte): +3950
- Credit 2900 (Forskudd fra kunder): -3950

## Issues Found (why 2 checks fail)

### Issue 1: Salary provision amount is WRONG
- Agent used **3950 NOK** — copied from the accrual amount
- The prompt does NOT specify the salary provision amount
- Agent should use a reasonable amount or derive it from context, not reuse 3950
- This is a bug in the agent's reasoning

### Issue 2: Wrong expense account for accrual
- Agent used **7700** (Styre- og bedriftsforsamlingsmøter — board/corporate assembly meetings)
- The prompt says "de la cuenta 1720 a gasto" (from account 1720 to expense)
- Account 1720 is "Andre depositum" (other deposits/prepaid)
- The correct expense account depends on what the prepaid represents
- Agent should look at what expense category 1720 relates to, or use a general expense account

### Issue 3: Depreciation credit account may be wrong
- Agent credited **1200** (Maskiner og anlegg — machinery and equipment) directly
- In Norwegian accounting, depreciation typically credits an accumulated depreciation account (e.g. 1209, 1290)
- Agent searched for 1209 but it didn't exist on this sandbox
- Crediting 1200 directly reduces the asset — this might be acceptable but is not standard practice

### Issue 4: Efficiency — too many API calls
- 9 GET calls for accounts when only 4-5 were needed
- Unnecessary lookups: 1790, 1209, 1210, 7700 (agent was guessing)
- 6 verification GETs at the end (posting + voucher checks) — unnecessary for scoring
- **Optimal:** 4 GETs (1720, 6010, 5000, 2900) + 3 POSTs = 7 calls total

## Recommended Fixes for System Prompt

### 1. Monthly closing / accrual instructions
```
When registering a periodification/accrual from a prepaid account (e.g. 1720):
- The expense account should match what the prepaid represents
- If account 1720 "Andre depositum" → expense is typically the related operating expense
- Do NOT guess random expense accounts — if unsure, use the account mentioned in the prompt
```

### 2. Depreciation instructions
```
For depreciation:
- Calculate: cost / useful_life_years / 12 = monthly depreciation
- Debit: depreciation expense account (e.g. 6010)
- Credit: the SAME asset account (e.g. 1200) — Tripletex may not have separate accumulated depreciation accounts
- Do NOT search for accumulated depreciation sub-accounts (1209 etc.) — just credit the asset account directly
```

### 3. Salary provision
```
For salary provision:
- The prompt specifies which accounts to debit/credit
- If the amount is NOT specified, do NOT copy from another entry
- Look at existing salary data or use a reasonable estimate
```

### 4. Efficiency
```
- Only look up accounts explicitly mentioned in the prompt
- Do NOT verify postings after creating vouchers — the scorer checks independently
- Aim for minimal API calls: GET accounts + POST vouchers only
```

## No UI Investigation Needed

This is a prompt engineering problem, not an API endpoint issue. The voucher creation mechanism (`POST /ledger/voucher`) works correctly. The agent just needs better instructions on account selection and amount calculation.
