# Task 23 — Bank Reconciliation: Complete Fix v3

## Status: 0.6 points (1/2 checks). Tier 3 (max 6.0). Top team: 6.0.

## Check Structure

2 checks, 5 points each:
- Check 1 (5 pts): Reconciliation CLOSED with avvik=0 — ALWAYS FAILS
- Check 2 (5 pts): Customer payments registered — PASSES after CSV fix

## Root Causes for Check 1 Failure

### Problem 1: Wrong accounting period

Agent uses January period but CSV spans Jan-Feb.
System prompt says "use period of LAST CSV date" but agent picks first date's period.
Last CSV date is in February → should use February period.
With January period, Feb entries (Skattetrekk, Renteinntekter) get rejected (422).

### Problem 2: Agent uses adjustments for supplier payments (correct!) but then fails

The agent actually uses Bankgebyr adjustments for supplier payments — this IS correct.
Adjustments DO create postings on 1920 (verified in sandbox + UI).
But the 422 error from wrong period causes agent to drop some entries.

### Problem 3: Unhandled CSV line types

CSV has "Skattetrekk" which is not in the system prompt parsing rules.
Agent doesn't know what to do with it → skips it → 1920 balance mismatch → avvik != 0.

### Problem 4: Missing "Lieferant" keyword

German CSVs use "Betaling Lieferant" for supplier payments.
System prompt only lists: Leverandor/Fornecedor/Fournisseur.

## CSV Format Analysis (from 6 saved CSV files)

All CSVs follow: `Dato;Forklaring;Inn;Ut;Saldo`

### Line types seen:

| Description | Column | Action | Adjustment Type |
|------------|--------|--------|----------------|
| Innbetaling fra X / Faktura N | Inn | PUT /invoice/:payment | - |
| Betaling Fournisseur/Fornecedor/Leverandor/Lieferant X | Ut | Adjustment | Bankgebyr |
| Bankgebyr | Ut | Adjustment | Bankgebyr |
| Bankgebyr | Inn | Adjustment | Renteinntekter |
| Renteinntekter | Ut | Adjustment | Rentekostnader |
| Renteinntekter | Inn | Adjustment | Renteinntekter |
| Skattetrekk | Ut | Adjustment | Bankgebyr |
| Skattetrekk | Inn | Adjustment | Renteinntekter |

### Generic rule:
- "Innbetaling" → customer payment (PUT /invoice/:payment)
- Everything else in INN column → Renteinntekter adjustment
- Everything else in UT column → Bankgebyr adjustment

## Sandbox + UI Verification

### Adjustments create real postings on 1920:
```
Bankgebyr adjustment:     → 1920 debit -1000 (Ut av konto) ✓
Renteinntekter adjustment: → 1920 credit +500 (Inn pa konto) ✓
Rentekostnader adjustment: → 1920 debit -200 (Ut av konto) ✓
```
Verified in August reconciliation UI (bilag 64-2026).

### Full end-to-end reconciliation closed:
```
September 2026:
  Inngaende saldo:              75 218,86
  Customer payment (voucher):   +5 000,00 (Inn pa konto)
  Bankgebyr adjustment:         -1 000,00 (Ut av konto)
  Renteinntekter adjustment:      +200,00 (Inn pa konto)
  Utgaende saldo fra regnskap:  79 418,86
  Utgaende fra kontoutskrift:   79 418,86
  Avvik:                              0,00
  Godkjenn avstemming:          CHECKED ✓
```
Verified in UI: bilag 66-2026, reconciliation closed successfully.

## Updated System Prompt

Key changes to the workflow:

```
## Workflow: Bank reconciliation from CSV (Task 23)

2. Parse CSV. Uses semicolons (;): Dato;Forklaring;Inn;Ut;Saldo
   - "Innbetaling" in description → customer payment (PUT /invoice/:payment)
   - EVERYTHING ELSE is a reconciliation adjustment:
     * If INN column filled → Renteinntekter adjustment type (money IN)
     * If UT column filled → Bankgebyr adjustment type (money OUT)
   This covers: supplier payments (Fournisseur/Fornecedor/Leverandor/Lieferant),
   Bankgebyr, Renteinntekter, Skattetrekk, and any other line types.
   Accounting period: use period containing the LAST transaction date in CSV.
   Closing balance: the LAST Saldo value in the CSV.
```

Steps 3-8 remain the same, but critical additions:
- Step 4: Add ALL non-Innbetaling lines as adjustments in ONE call
- Step 5: type:"MANUAL" (avoid 422)
- Step 7: GET version after adjustment (version increments)
- Step 8: Close with correct closing balance = last CSV saldo

## Expected Score

| Metric | Value |
|--------|-------|
| Current | 0.6 (1/2 checks) |
| After fix | 6.0 (2/2 checks, Tier 3) |
| Top team | 6.0 |
