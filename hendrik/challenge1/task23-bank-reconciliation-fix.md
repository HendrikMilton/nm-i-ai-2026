# Task 23 — Bank Reconciliation (CSV) — Fix Report

**Date:** 2026-03-21
**Current score:** 0.00 (0/2 checks)
**Potential score:** ~4.50 (Tier 3 x3)
**Impact:** +4.50 points
**Status:** FULLY VERIFIED on sandbox + UI

---

## Task Description

"Avstem bankutskrifta (vedlagt CSV) mot opne fakturaer i Tripletex. Match innbetalingar til kundefakturaer og utbetalingar til leverandorfakturaer. Handter delbetalingar korrekt."

Translation: "Reconcile the bank statement (attached CSV) against open invoices. Match incoming payments to customer invoices and outgoing to supplier invoices. Handle partial payments correctly."

---

## Why the Agent Fails

The agent registers customer payments via `PUT /invoice/{id}/:payment` but:
1. **Never creates a bank reconciliation entity** — the scorer checks for this
2. **Never registers supplier payments** — outgoing CSV lines ignored
3. **Never registers bank fees** — fee lines ignored
4. **Never sets closing balance or approves the reconciliation**

Even with all 5 customer payments registered correctly, the score was 0/2. The scorer requires a **closed bank reconciliation entity**, not just payment registrations.

---

## The Fix: Complete Bank Reconciliation Flow (Verified)

### Full API flow:

```
1. Parse CSV — extract:
   - Customer payments (Inn column): match to invoices by invoice number/customer name
   - Supplier payments (Ut column): match to supplier invoices
   - Bank fees (Bankgebyr lines): amounts for reconciliation adjustment
   - Opening saldo (first line) and closing saldo (last line)

2. In parallel: GET open invoices + payment types + accounting period
   - GET /invoice?invoiceDateFrom=2020-01-01&invoiceDateTo=2026-12-31&fields=id,invoiceNumber,customer(id,name),amount,amountOutstanding
   - GET /invoice/paymentType?fields=id,description → find "Betalt til bank"
   - GET /supplierInvoice?invoiceDateFrom=2020-01-01&invoiceDateTo=2026-12-31&fields=id,invoiceNumber,supplier(id,name),amount
   - GET /ledger/accountingPeriod → find period matching CSV dates
   - GET /bank/reconciliation/paymentType?fields=id,description → find "Bankgebyr"
   - GET /ledger/account?number=1920&fields=id

3. Register customer invoice payments ONE AT A TIME:
   PUT /invoice/{id}/:payment with paymentDate, paymentTypeId ("Betalt til bank"), paidAmount
   — use paidAmount from CSV Inn column (handles partial payments automatically)

4. Register supplier invoice payments ONE AT A TIME:
   POST /supplierInvoice/{id}/:addPayment with paymentDate, amount, useDefaultPaymentType=true
   — for partial payments, set partialPayment=true

5. Create bank reconciliation:
   POST /bank/reconciliation with {
     account: {id: <1920_id>},
     accountingPeriod: {id: <matching_period_id>},
     bankAccountClosingBalanceCurrency: <CSV_final_saldo>,
     isClosed: false
   }

6. Add bank fees (if any in CSV):
   PUT /bank/reconciliation/{id}/:adjustment with [{
     postingDate: "<fee_date>",
     description: "Bankgebyr",
     amount: <fee_amount>,  (positive number)
     paymentType: {id: <bankgebyr_type_id>}
   }]

7. Close the reconciliation:
   PUT /bank/reconciliation/{id} with {
     id, version,
     account: {id},
     accountingPeriod: {id},
     bankAccountClosingBalanceCurrency: <same_closing_balance>,
     isClosed: true
   }
   — this only succeeds when accounting balance matches bank statement balance (avvik = 0)
```

---

## Sandbox Verification

```
POST /bank/reconciliation → 201 (id=12705390, type=MANUAL)
PUT /bank/reconciliation/12705390/:adjustment → 200 (bank fee 500 NOK added)
PUT /bank/reconciliation/12705390 (set closingBalance=74100) → 200
PUT /bank/reconciliation/12705390 (isClosed=true) → 200 (CLOSED!)
```

## UI Verification

Confirmed in **Bank → Bankavstemming → Manuell → Mars 2026**:
- Voucher "28-2026 – Manuell bankavstemming" created
- All postings on account 1920 listed (payments in/out)
- Bank fee "Bankgebyr 500,00" in the fees section
- Utgaende saldo fra regnskap = 74,100.00
- Utgaende saldo fra kontoutskrift = 74,100.00
- Avvik = 0 (balanced!)
- "Godkjenn avstemming" checkbox is CHECKED

---

## CSV Format

The task provides a semicolon-separated CSV:
```
Dato;Forklaring;Inn;Ut;Saldo
2026-01-17;Innbetaling fra Lunde AS / Faktura 1001;9437.50;;109437.50
2026-01-25;Innbetaling fra Stolsvik AS / Faktura 1005;11050.00;;151800.00
2026-01-27;Betaling Leverandor Brekke AS;;-6100.00;145700.00
2026-02-02;Bankgebyr;;-967.04;114032.96
```

Agent must parse and categorize each line:
- **Inn column filled** → customer payment → match by invoice number in description
- **Ut column filled, "Leverandor"** → supplier payment → match by supplier name
- **"Bankgebyr"** → bank fee → add via reconciliation adjustment
- **First "Saldo" line** → opening balance
- **Last "Saldo" value** → closing balance for reconciliation

---

## Key API Details

### Accounting Period
```
GET /ledger/accountingPeriod → returns periods like:
  id=23734304, start=2026-01-01, end=2026-02-01 (January)
  id=23734305, start=2026-02-01, end=2026-03-01 (February)
  id=23734306, start=2026-03-01, end=2026-04-01 (March)
```
Match the CSV date range to the correct period.

### Bank Reconciliation Payment Types
```
GET /bank/reconciliation/paymentType → returns:
  Bankgebyr (bank fees)
  Kortgebyr (card fees)
  Renteinntekter (interest income)
  Rentekostnader (interest expenses)
```

### Supplier Invoice Payment
```
POST /supplierInvoice/{invoiceId}/:addPayment
  params: paymentDate, amount, useDefaultPaymentType=true, partialPayment=true/false
```
Note: `amountOutstanding` is NOT a valid field on SupplierInvoiceDTO (agent got 400 error on this).

### Closing the Reconciliation
- Can only close when `avvik = 0` (accounting balance = bank statement balance)
- All payments + fees must be registered first
- Then `PUT /bank/reconciliation/{id}` with `isClosed: true`

---

## What the Agent Did Wrong

| Step | Agent (wrong) | Correct |
|------|--------------|---------|
| Parse CSV | Only extracted customer payments | Must extract ALL lines: customer, supplier, fees |
| Customer payments | Registered correctly | Same — PUT /invoice/:payment |
| Supplier payments | Skipped entirely | POST /supplierInvoice/:addPayment |
| Bank fees | Skipped entirely | PUT /bank/reconciliation/:adjustment |
| Reconciliation | Never created | POST /bank/reconciliation + close with isClosed:true |
| Closing balance | Never set | bankAccountClosingBalanceCurrency from CSV |
| GET /supplierInvoice | Got 400 (amountOutstanding invalid field) | Remove amountOutstanding from fields |
| GET /ledger/openPostings | Got 404 | Don't use this endpoint |

---

## System Prompt Addition Needed

```
## Workflow: Bank reconciliation from CSV (Task 23)
Reconcile a bank statement (CSV) against open invoices. Parse ALL lines in the CSV.
1. In parallel: GET /invoice (open), GET /supplierInvoice (open, without amountOutstanding field),
   GET /invoice/paymentType, GET /ledger/accountingPeriod, GET /bank/reconciliation/paymentType,
   GET /ledger/account?number=1920
2. Parse CSV: categorize each line as customer payment (Inn), supplier payment (Ut/Leverandor),
   or bank fee (Bankgebyr). Note the final Saldo value as closing balance.
3. Register customer payments ONE AT A TIME: PUT /invoice/{id}/:payment with correct date and amount
4. Register supplier payments ONE AT A TIME: POST /supplierInvoice/{id}/:addPayment
   with paymentDate, amount, useDefaultPaymentType=true
5. Create reconciliation: POST /bank/reconciliation with {account:{id:1920}, accountingPeriod:{id},
   bankAccountClosingBalanceCurrency:<CSV_final_saldo>, isClosed:false}
6. Add bank fees: PUT /bank/reconciliation/{id}/:adjustment with [{postingDate, description:"Bankgebyr",
   amount:<positive>, paymentType:{id:<bankgebyr_id>}}]
7. Close: PUT /bank/reconciliation/{id} with isClosed:true
   Only succeeds when accounting balance = bank statement balance (avvik = 0).
```
