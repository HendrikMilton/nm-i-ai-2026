# Task 20 — Supplier Invoice from PDF Deep Analysis

**Date:** 2026-03-22
**Analyzed by:** Gabriel + Claude
**Current score:** 2.4/6.0 (best run: 8/10, 5/6 checks)
**Target:** 6.0

## Task Description

Register a supplier invoice from an attached PDF. Create the supplier if it doesn't exist. Use correct expense account and input VAT.

## Check Mapping (deduced from score progression)

| Check | What it validates | Status |
|-------|------------------|--------|
| Check 1 | Supplier exists (correct org number, name, bank account) | PASS |
| Check 2 | SupplierInvoice record exists (not just a ledger voucher) | PASS |
| Check 3 | Invoice number, date, due date correct | PASS |
| Check 4 | Correct expense account and VAT treatment | PASS |
| **Check 5** | **??? — ALWAYS FAILS** | **FAIL** |
| Check 6 | Voucher sent to ledger (postings visible) | PASS |

Evidence for check mapping:
- **2/10 runs** (early): Used `POST /ledger/voucher` instead of `POST /supplierInvoice` → only Check 1 passed (supplier created)
- **7/10 runs**: Used `POST /supplierInvoice` but NO `sendToLedger` → Check 5 + 6 failed
- **8/10 runs** (current): Used `POST /supplierInvoice` + `sendToLedger` → only Check 5 fails

## What the agent does correctly

1. Extracts all PDF fields: supplier name, org number, address, bank account, invoice number, dates, amounts, expense account
2. Creates supplier with `bankAccountPresentation[{bban}]`
3. Creates supplierInvoice with inline voucher postings (expense debit with vatType:{id:1}, AP credit with vatType:{id:0})
4. Calls `PUT /ledger/voucher/{id}/:sendToLedger` to book the voucher
5. Total: 6 API calls, 0 errors

## What Check 5 could be — tested theories

### Ruled out
| Theory | Test result |
|--------|------------|
| `amountExcludingVatCurrency` field not set | API ignores this field — always stays 0 regardless of input |
| `amount` field is 0 | API ignores explicit `amount` value — always calculates as 0 for NOK invoices |
| Invoice approval (`PUT /:approve`) | Returns 422 "Denne bilagstypen kan ikke attesteres" — can't approve this voucher type |
| `PUT /supplierInvoice/voucher/{id}/postings` | Different schema, doesn't accept same fields as inline postings |
| Wrong VAT amount/split | Tripletex auto-splits correctly: expense gets net, 2710 gets VAT, 2400 gets total |
| Wrong expense account | PDF explicitly says "Konto: 6300" — agent uses it correctly |

### Top candidates (not yet testable without live run)

**1. PDF document attachment (STRONGEST)**
- The agent never attaches the source PDF to the supplier invoice
- `sendToLedger` response shows `"document":null, "attachment":null"`
- Task explicitly says "see attached PDF" — implies document should be linked
- `originalInvoiceDocumentId: 0` on the supplierInvoice
- API has `POST /documentArchive/reception` for uploading documents
- This is standard accounting practice: always attach source documents
- Would require: upload PDF → get document ID → link to invoice

**2. Missing field on supplierInvoice**
- Some field the agent doesn't set that the checker validates
- Hard to determine without API documentation for POST /supplierInvoice (not in api-compact.json!)

## Recommended next steps

1. **Test PDF attachment in live run**: Modify the agent to upload the PDF via `POST /documentArchive/reception` and link it to the supplier invoice
2. **Check Tripletex UI**: Create a supplier invoice manually in the UI to see what fields/steps are involved
3. **Check competitor approaches**: If possible, see how top teams handle supplier invoices

## Impact

Fixing Check 5 would move Task 20 from 8/10 → 10/10:
- 10/10 = perfect score → eligible for efficiency bonus
- With Tier 2 (x2) + efficiency bonus: up to 6.0 points
- Current: 2.4 → potential: 6.0 = **+3.6 points**
