# Supplier Invoice (Task 20) — Complete Fix Report v2

**Date:** 2026-03-21
**Current score:** 0.60 (5/6 checks failed, only Check 5 passed)
**Potential score:** 5.40 (Tier 3 x3 multiplier)
**Impact:** +4.80 points

---

## What the Agent Does Now (WRONG)

The system prompt (lines 39, 178) says:
```
Register via POST /ledger/voucher — do NOT use POST /supplierInvoice.
Supplier invoices: use POST /ledger/voucher — NEVER use POST /supplierInvoice
```

This creates a **generic "Avansert bilag"** (advanced voucher), NOT a proper "Leverandorfaktura".

### Evidence from Task 20 log (2026-03-21T11-48-59-624Z):
- Agent calls `POST /ledger/voucher` → 201 Created
- Response shows: `supplierVoucherType: null`, `vendorInvoiceNumber: null`
- The voucher lives at `/execute/voucherMenu?voucherId=X` (generic voucher module)
- Does NOT appear in `GET /supplierInvoice` search
- Scorer can't find a proper supplier invoice entity → 5/6 checks fail

### Additional issues in this run:
1. Supplier created with `email: ""` (empty) — prompt says to use dummy email
2. `bankAccounts` field sent → 422 error (1 wasted API call)
3. `vendorInvoiceNumber` sent on voucher body → silently dropped by API

---

## The Fix: Use POST /supplierInvoice

**This was already verified working on sandbox on 2026-03-20** (see supplier-invoice-fix.md).
**Re-verified on 2026-03-21** — still works, creates proper entity.

### POST /supplierInvoice — Verified Working Call

```json
POST /supplierInvoice

{
  "invoiceNumber": "INV-2026-8795",
  "invoiceDate": "2026-03-06",
  "supplier": {"id": <supplier_id>},
  "voucher": {
    "date": "2026-03-06",
    "description": "Supplier Name - INV-2026-8795",
    "postings": [
      {
        "row": 1,
        "date": "2026-03-06",
        "account": {"id": <expense_account_id>},
        "supplier": {"id": <supplier_id>},
        "amountGross": <total_incl_vat>,
        "amountGrossCurrency": <total_incl_vat>,
        "vatType": {"id": 1},
        "description": "Description from invoice",
        "invoiceNumber": "INV-2026-8795"
      },
      {
        "row": 2,
        "date": "2026-03-06",
        "account": {"id": <2400_account_id>},
        "supplier": {"id": <supplier_id>},
        "amountGross": <negative_total_incl_vat>,
        "amountGrossCurrency": <negative_total_incl_vat>,
        "description": "Leverandorgjeld"
      }
    ]
  }
}
```

### What This Creates (verified on sandbox)

| Field | POST /ledger/voucher (current) | POST /supplierInvoice (fix) |
|-------|-------------------------------|----------------------------|
| Entity type | "Avansert bilag" | "Leverandorfaktura (enkel foring)" |
| supplierVoucherType | null | TYPE_SUPPLIER_INVOICE_SIMPLE |
| vendorInvoiceNumber | null (silently dropped) | VERIFY-TEST-001 (persisted!) |
| In GET /supplierInvoice | NO | YES |
| UI module | /execute/voucherMenu | /execute/incomingInvoiceMenu |
| voucherType ID | null (generic) | 9812369 (Leverandorfaktura) |

### Critical Rules for POST /supplierInvoice

1. Both postings MUST have `amountGross` AND `amountGrossCurrency` — missing amountGrossCurrency causes 422 "credit posting missing"
2. Both postings MUST have `supplier: {id}`
3. Debit posting (row 1): expense account, positive amounts, `vatType: {id: 1}`, include `invoiceNumber`
4. Credit posting (row 2): account 2400, negative amounts, NO vatType
5. Do NOT include `supplierVoucherType` (causes 422 if set as string)
6. `invoiceNumber` goes on the top level AND on the debit posting
7. Postings go INSIDE `voucher.postings`, not at top level

---

## System Prompt Changes Needed

### 1. Replace supplier invoice workflow (lines 38-50)

Replace:
```
## Workflow: Supplier invoice from PDF (Task 20)
Register via POST /ledger/voucher — do NOT use POST /supplierInvoice.
```

With:
```
## Workflow: Supplier invoice from PDF (Task 20)
Register via POST /supplierInvoice — do NOT use POST /ledger/voucher.
Extract ALL fields from PDF: supplier name, org number, address, invoice number, date, due date, amounts, account number.
1. In parallel: GET /supplier?organizationNumber=X&fields=id,name, GET /ledger/account?number=XXXX (expense), GET /ledger/account?number=2400 (leverandorgjeld)
2. If supplier not found, create: POST /supplier with {name, organizationNumber, email:"post@example.org", invoiceEmail:"post@example.org", postalAddress:{addressLine1, postalCode, city}}
   NEVER include bankAccounts field — it causes 422.
3. POST /supplierInvoice with {invoiceNumber:"INV-...", invoiceDate, supplier:{id}, voucher:{date:<invoice_date>, description:"Supplier Name - INV-...", postings:[
     {row:1, date, account:{id:expense}, supplier:{id}, amountGross:<totalInclVat>, amountGrossCurrency:<totalInclVat>, vatType:{id:1}, description, invoiceNumber:"INV-..."},
     {row:2, date, account:{id:2400}, supplier:{id}, amountGross:<negative>, amountGrossCurrency:<negative>, description:"Leverandorgjeld"}
   ]}}
```

### 2. Remove contradictory rules (line 178)

Delete:
```
- Supplier invoices: use POST /ledger/voucher — NEVER use POST /supplierInvoice
```

Replace with:
```
- Supplier invoices: use POST /supplierInvoice — NEVER use POST /ledger/voucher for supplier invoices
- Supplier invoice postings go inside voucher.postings, NOT at top level
- Both postings MUST include amountGrossCurrency (same value as amountGross for NOK)
```

### 3. Also update "Supplier invoice from text prompt" section (lines 49-50)

Same change — use POST /supplierInvoice instead of POST /ledger/voucher.

---

## Other Endpoints Investigated (Don't Work)

| Endpoint | Status | Why |
|----------|--------|-----|
| POST /incomingInvoice | 403 Forbidden | "Restricted API for pilot customers" |
| POST /ledger/voucher with voucherType={id:9812369} | Creates voucher but NOT a supplier invoice | supplierVoucherType and vendorInvoiceNumber silently ignored |
| PUT /ledger/voucher/{id} with supplierVoucherType | Silently ignored | API accepts but doesn't persist |
| PUT /supplierInvoice/voucher/{id}/postings | Only works on empty vouchers | "Can not put postings on a voucher that already have postings" |

**POST /supplierInvoice is the ONLY working approach.**

---

## Sandbox Verification Log

```
# Create supplier invoice
POST /supplierInvoice → 201 Created
  id=2147595963
  invoiceNumber=VERIFY-TEST-001
  supplier.id=108238866
  voucher.id=608971437

# Check underlying voucher
GET /ledger/voucher/608971437
  voucherType: {id: 9812369} (Leverandorfaktura)
  supplierVoucherType: TYPE_SUPPLIER_INVOICE_SIMPLE
  vendorInvoiceNumber: VERIFY-TEST-001

# Appears in supplier invoice search
GET /supplierInvoice/2147595963 → 200
  invoiceNumber: VERIFY-TEST-001
```
