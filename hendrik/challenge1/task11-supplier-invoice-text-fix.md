# Task 11 — Supplier Invoice from Text: Complete Fix

## Status

- Hendrik deployed POST /supplierInvoice fix -> scored 2/4 checks (1.0 points)
- Checks 1+2 pass, checks 3+4 fail
- Missing step: voucher must be bokfort (posted) via sendToLedger
- Tier 2 task, max 4.0 points. Top team: 3.33.

## Two Problems Found

### Problem 1: Wrong endpoint (FIXED by Hendrik)

Agent was using `POST /ledger/voucher` instead of `POST /supplierInvoice`.
Direct vouchers don't create a `supplierInvoice` object -> checker finds nothing -> 0/4.

### Problem 2: Voucher not bokfort (STILL BROKEN)

`POST /supplierInvoice` creates a voucher with `number: 0` (unposted).
Unbooked voucher postings are INVISIBLE to `GET /ledger/posting` queries.
The checker queries ledger postings by account -> finds nothing -> checks 3+4 fail.

**Proof from sandbox:**
- `GET /ledger/posting?accountId=7000` returns ZERO results for unbooked vouchers
- After `PUT /ledger/voucher/{id}/:sendToLedger`, the same query returns the postings
- Verified in Tripletex UI: bilag 54-2026 appears in Bilagsoversikt with correct postings

## What the 4 Checks Validate

| Check | What | How checker verifies |
|-------|------|---------------------|
| 1 | SupplierInvoice exists | `GET /supplierInvoice?invoiceNumber=X` |
| 2 | Correct supplier linked | supplier.name + organizationNumber on the invoice |
| 3 | Correct expense posting | `GET /ledger/posting?accountId=<expense>` - needs bokfort voucher |
| 4 | Correct AP posting | `GET /ledger/posting?accountId=2400` - needs bokfort voucher |

## Task 11 Prompt Pattern

Always contains (in Norwegian/German/Nynorsk):
- Invoice number: `INV-2026-XXXX`
- Supplier name + org number
- Total amount inklusiv MVA
- Expense account number (varies: 6300, 6500, 6540, 7000, etc.)
- VAT rate: always 25%
- No due date in prompt

## Complete Fix for system-prompt.ts

Replace the "Supplier invoice from text prompt" workflow with:

```
## Workflow: Supplier invoice from text prompt (Task 11)
Register via POST /supplierInvoice — NEVER use POST /ledger/voucher.
1. In parallel: GET /supplier?organizationNumber=X&fields=id,name,
   GET /ledger/account?number=XXXX (expense account from prompt),
   GET /ledger/account?number=2400 (leverandorgjeld)
2. POST /supplierInvoice with {
     invoiceDate: <today>,
     invoiceDueDate: <today + 30 days>,
     supplier: {id},
     invoiceNumber: "<from prompt>",
     amountCurrency: -<totalInclVat>,
     voucher: {
       date: <invoiceDate>,
       description: "<supplier_name> - <invoice_number>",
       postings: [
         {date, description, account:{id:<expense_acct>}, supplier:{id},
          amountGross:<totalInclVat>, amountGrossCurrency:<totalInclVat>,
          vatType:{id:1}, invoiceNumber:"<inv_num>", row:1},
         {date, description, account:{id:<2400_acct>}, supplier:{id},
          amountGross:-<totalInclVat>, amountGrossCurrency:-<totalInclVat>,
          vatType:{id:0}, row:2}
       ]
     }
   }
3. PUT /ledger/voucher/{voucherId}/:sendToLedger with empty body {}
   Use voucher.id from the POST response. This books the voucher so postings
   are visible in ledger queries. WITHOUT THIS STEP, checks 3+4 WILL FAIL.
CRITICAL: amountCurrency MUST be NEGATIVE.
CRITICAL: expense account number varies per prompt — always use the account from the task.
Total: 2 write calls.
```

## Sandbox-Verified Required Fields

| Field | Required | Notes |
|-------|----------|-------|
| `invoiceDate` | Yes | 422 if missing |
| `supplier.id` | Yes | 500 if missing |
| `amountCurrency` | Yes (negative) | 500 if missing |
| `voucher.postings` | Yes | 422 if missing |
| `invoiceNumber` | No, but needed for checks | Set on header AND debit posting |
| `invoiceDueDate` | No | Optional, default to +30 days |

## Sandbox End-to-End Verification

Created supplier invoice E2E-FINAL-001 (21100 NOK inkl MVA, konto 6300):

```
Bilag 54-2026 (posted):
  6300 Leie lokale:           16 880,00  (net, MVA code 1 = 25%)
  2400 Leverandorgjeld:      -21 100,00
  2710 Inngaende MVA:          4 220,00  (auto-generated)
  Kontrollsum:                     0,00
```

All checker-equivalent queries confirmed working:
- GET /supplierInvoice -> found with correct supplier + invoice number
- GET /ledger/posting (account 6300) -> found: amount=16880, gross=21100, vatType=1
- GET /ledger/posting (account 2400) -> found: amount=-21100, supplier=Havbris AS
- GET /ledger/posting (account 2710) -> found: amount=4220 (MVA)

## Expected Score After Fix

| Metric | Value |
|--------|-------|
| Before any fix | 0.0 (0/4 checks) |
| After Hendrik's fix (current) | 1.0 (2/4 checks — missing sendToLedger) |
| After adding sendToLedger | ~3.3-3.5 (4/4 checks, 2 write calls, Tier 2) |
| Top team (Kult Byra) | 3.33 |

## API Call Budget

| Call | Type | Cost |
|------|------|------|
| GET /supplier | GET | Free |
| GET /ledger/account (expense) | GET | Free |
| GET /ledger/account (2400) | GET | Free |
| POST /supplierInvoice | WRITE | 1 call |
| PUT /ledger/voucher/{id}/:sendToLedger | WRITE | 1 call |
| **Total writes** | | **2** |
