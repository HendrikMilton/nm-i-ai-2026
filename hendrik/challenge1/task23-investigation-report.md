# Task 23 Investigation Report — 2026-03-22

## Current Score
- **0.6 / 6.0 points** (Tier 3, max possible 6.0, top team has 6.0)
- Best raw score: 2/10 (1/2 checks pass)
- 11 attempts used

## Task Description
Reconcile a bank statement (attached CSV) against open invoices in Tripletex. Match incoming payments to customer invoices and outgoing payments to supplier invoices. Handle partial payments.

## Check Pattern (consistent across all runs)

| Check | Status | Points | What it tests |
|-------|--------|--------|---------------|
| Check 1 | **Always fails** | 8 pts | Reconciliation CLOSED with avvik=0 |
| Check 2 | **Always passes** | 2 pts | Customer payments registered correctly |

## Root Cause: Wrong paymentType from description confusion

### The bug

The CSV has deliberately misleading descriptions. Examples from real CSVs:

| CSV Line | Column | Description | Agent uses | Should use |
|----------|--------|-------------|------------|------------|
| Renteinntekter;; -483.95 | **Ut** | "Renteinntekter" | Renteinntekter (money IN) | **Bankgebyr** (money OUT) |
| Bankgebyr;258.36;; | **Inn** | "Bankgebyr" | Bankgebyr (money OUT) | **Renteinntekter** (money IN) |
| Skattetrekk;624.26;; | **Inn** | "Skattetrekk" | Bankgebyr (money OUT) | **Renteinntekter** (money IN) |

The agent reads the description text and picks the matching paymentType name, **ignoring which CSV column the amount is in**.

### The math

Latest run (09-55, German CSV bankutskrift_de_03.csv):

```
Opening balance 1920:     100,000.00
Customer payments (Inn):  +82,662.50
Supplier payments (Ut):   -41,150.00  (correct, Bankgebyr type)
Renteinntekter (Ut):       +483.95    ← WRONG! Should be -483.95
Skattetrekk (Ut):          -1,115.70  (correct, Bankgebyr type)
                          -----------
Accounting balance:       140,880.75
CSV closing balance:      139,912.85
Avvik:                        967.90  = exactly 2 × 483.95
```

Using Renteinntekter paymentType for an Ut item creates a +483.95 posting instead of -483.95, causing a double error of 967.90.

### The prompt says the right thing but not strongly enough

Current prompt (line 326):
```
paymentType: Bankgebyr for UT items, Renteinntekter for INN items.
```

This is correct but the LLM gets confused by the description text. The CSVs are deliberately designed to trick: "Renteinntekter" appears in Ut column, "Bankgebyr" appears in Inn column.

### Fix needed

Replace line 326 with:
```
CRITICAL: paymentType is determined ONLY by which CSV column has the amount, NEVER by description text:
  - Amount in Ut column → ALWAYS use Bankgebyr paymentType (even if description says "Renteinntekter")
  - Amount in Inn column → ALWAYS use Renteinntekter paymentType (even if description says "Bankgebyr" or "Skattetrekk")
The CSV descriptions are DELIBERATELY MISLEADING — IGNORE them for paymentType selection.
```

## Secondary Issues (from older runs)

### Issue 2: Agent creates manual vouchers instead of adjustments
In run 07-36 (pt_03), the agent created `POST /ledger/voucher` for Skattetrekk lines instead of using reconciliation adjustments. This violates the prompt rule "NEVER create manual ledger vouchers for ANY CSV line." The vouchers don't count as reconciliation adjustments so the balance doesn't match.

### Issue 3: Supplier payment handling
The current prompt includes a step 4 for supplier payments via `POST /supplierInvoice/{id}/:addPayment`. This has caused 422 errors in some runs and adds complexity. The fix doc v3 approach (treating supplier payments as Bankgebyr adjustments) was simpler and worked.

### Issue 4: Wrong accounting period
Some runs pick January period when CSV spans Jan-Feb. The last CSV date determines the period. This is stated in the prompt but sometimes ignored by the agent.

## CSV Examples Analyzed

All CSVs follow: `Dato;Forklaring;Inn;Ut;Saldo`

Seen across 6 different CSVs (nb, pt, fr, de, es, nn variants):
- Languages: Norwegian, Portuguese, French, German, Spanish, Nynorsk
- Supplier keywords: Leverandor, Fornecedor, Fournisseur, Lieferant
- Deliberately swapped: Renteinntekter in Ut, Bankgebyr in Inn, Skattetrekk in Inn
- Partial payments present (customer pays less than invoice amount)

## Confidence
- **80%** that fixing the paymentType confusion resolves Check 1
- The math is exact — wrong type creates precisely the observed avvik
- Previous sandbox test (fix doc v3) successfully closed a reconciliation end-to-end

## Expected Score After Fix
- Check 1 passes (8 pts) + Check 2 passes (2 pts) = 10/10
- With Tier 3: 3.0 base, up to 6.0 with efficiency bonus
- Top team already has 6.0
