# Supplier Invoice — Root Cause Found & Fix Verified

**Date:** 2026-03-21
**Impact:** 3 tasks × ~3.2 points = **+9.6 points**
**Status:** FIX VERIFIED ON SANDBOX

---

## Problem

All supplier invoice tasks score 0/8. The agent tried two approaches:

1. `POST /ledger/voucher` — creates wrong entity type ("Avansert bilag" instead of "Leverandørfaktura")
2. `POST /supplierInvoice` — correct endpoint but always fails with `422: "credit posting missing"`

The agent tried 14+ body variations on `/supplierInvoice` without success.

## Root Cause

**One missing field: `amountGrossCurrency`**

Every failed attempt used only `amountGross` on the postings. The `/supplierInvoice` endpoint requires BOTH `amountGross` AND `amountGrossCurrency`. Without `amountGrossCurrency`, Tripletex does not recognize the credit posting — even though it's structurally present in the body.

```
FAILED:  "amountGross": 25650
WORKED:  "amountGross": 25650, "amountGrossCurrency": 25650
```

## Verified Working API Call

```
POST /supplierInvoice
```

```json
{
  "invoiceNumber": "INV-2026-XXX",
  "invoiceDate": "2026-03-21",
  "supplier": {"id": <supplier_id>},
  "voucher": {
    "date": "2026-03-21",
    "description": "Supplier Name - INV-2026-XXX",
    "postings": [
      {
        "row": 1,
        "date": "2026-03-21",
        "account": {"id": <expense_account_id>},
        "supplier": {"id": <supplier_id>},
        "amountGross": <total_incl_vat>,
        "amountGrossCurrency": <total_incl_vat>,
        "vatType": {"id": 1},
        "description": "Office services",
        "invoiceNumber": "INV-2026-XXX"
      },
      {
        "row": 2,
        "date": "2026-03-21",
        "account": {"id": <2400_leverandorgjeld_id>},
        "supplier": {"id": <supplier_id>},
        "amountGross": <negative_total_incl_vat>,
        "amountGrossCurrency": <negative_total_incl_vat>,
        "description": "Leverandørgjeld"
      }
    ]
  }
}
```

**Response (201 Created):**
```json
{
  "value": {
    "id": 2147580243,
    "url": "kkpqfuj-amager.tripletex.dev/v2/supplierInvoice/2147580243",
    "invoiceNumber": "TEST-API-002",
    "invoiceDate": "2026-03-21",
    "supplier": {"id": 108238866},
    "voucher": {"id": 608896431}
  }
}
```

## Key Details

- **Endpoint:** `POST /supplierInvoice` (NOT `/ledger/voucher`)
- **Debit posting (row 1):** expense account (e.g. 6540, 6300, 7000) with `vatType: {id: 1}` (25% input VAT), positive amounts, include `invoiceNumber`
- **Credit posting (row 2):** account 2400 (Leverandørgjeld), negative amounts, NO vatType needed
- **Both postings** must include `supplier: {id}` and both `amountGross` AND `amountGrossCurrency`
- `supplierVoucherType` field is NOT needed (causes 422 if set to string)
- `vendorInvoiceNumber` on the voucher level is NOT needed — use `invoiceNumber` on the posting instead
- VAT is auto-calculated by Tripletex (splits debit into netto + MVA posting)

## Fields That Do NOT Exist on /supplierInvoice

These were tried and rejected with 422 "field does not exist":
- `paymentDueDate` — use `invoiceDueDate` instead (optional)
- `dueDate` — does not exist
- `postings` at top level — must be inside `voucher.postings`

## What Was Wrong Before

| Field | Old (failed) | New (works) |
|-------|-------------|-------------|
| Endpoint | `/ledger/voucher` | `/supplierInvoice` |
| `amountGrossCurrency` | missing | required on both postings |
| `supplier` on credit posting | sometimes missing | required on both postings |
| `invoiceNumber` on debit posting | sometimes missing | included |

## System Prompt Change Needed

Replace the current supplier invoice section with instructions to use `POST /supplierInvoice` with the verified body structure above. Key rules:
1. Always use `POST /supplierInvoice`, never `POST /ledger/voucher` for supplier invoices
2. Always include BOTH `amountGross` AND `amountGrossCurrency` on every posting
3. Always include `supplier: {id}` on BOTH postings
4. Debit posting: row 1, expense account, positive amounts, vatType {id: 1}
5. Credit posting: row 2, account 2400, negative amounts, no vatType
6. Include `invoiceNumber` on the debit posting
