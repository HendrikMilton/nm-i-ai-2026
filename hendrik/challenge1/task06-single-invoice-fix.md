# Task 06 — Single-Product Create+Send Invoice (Efficiency Fix)

**Date:** 2026-03-21
**Score:** 1.25 (5/5 checks pass) | **Tier:** 1 (max 2.0)
**Problem:** Pure efficiency — all checks pass, too many write calls

---

## Task Description

Create and send an invoice to a customer for a single product/service amount. The product and/or customer may need to be created first.

Example prompt: "Opprett og send ein faktura til kunden Fjelltopp AS (org.nr 927173875) pa 42600 kr eksklusiv MVA. Fakturaen gjeld Nettverksteneste."

---

## Current Approach (4-6 write calls depending on variant)

**Best case (4W) — product+customer exist:**
```
PUT  /ledger/account              <- WRITE 1 (bankAccountNumber)
POST /order                       <- WRITE 2
POST /order/orderline             <- WRITE 3
POST /invoice                     <- WRITE 4
```

**Typical case (5W) — product needs creation:**
```
PUT  /ledger/account              <- WRITE 1
POST /product                     <- WRITE 2
POST /order                       <- WRITE 3
POST /order/orderline             <- WRITE 4
POST /invoice                     <- WRITE 5
```

**Worst case (6W) — product AND customer need creation:**
```
PUT  /ledger/account              <- WRITE 1
POST /product                     <- WRITE 2
POST /customer                    <- WRITE 3
POST /order                       <- WRITE 4
POST /order/orderline             <- WRITE 5
POST /invoice                     <- WRITE 6
```

---

## Root Cause

The agent creates order + orderline + invoice as 3 separate writes. But POST /invoice supports inline order creation.

---

## BREAKTHROUGH: POST /invoice with Inline Order+OrderLines

The POST /invoice endpoint documentation says: "Related Order and OrderLines can be created first, or **included as new objects inside the Invoice**."

This means we can create the order, orderlines, AND invoice in **1 single POST**.

### Sandbox test:
```
POST /invoice?sendToCustomer=false with {
  invoiceDate, invoiceDueDate,
  orders: [{
    customer: {id},
    orderDate, deliveryDate,
    orderLines: [
      {product:{id}, count:1, unitPriceExcludingVatCurrency:25000, vatType:{id:3}},
      {product:{id}, count:1, unitPriceExcludingVatCurrency:15000, vatType:{id:3}}
    ]
  }]
}
-> SUCCESS: Invoice created with 2 lines, amount=50000, exclVat=40000
```

Also tested with 3 lines (Task 05 case): SUCCESS, amount=52500, exclVat=42000.

### UI verification (Invoice #35 and #36):
Both invoices show correct product lines, correct VAT, correct totals, correct bank account, bilag created. Identical to invoices created the old way.

---

## Optimized Approach

**Best case (1W) — product+customer exist, bank already set:**
```
POST /invoice (with inline order+orderlines)   <- WRITE 1
```

**Typical for Task 06 (2-3W):**
```
PUT  /ledger/account                            <- WRITE 1 (if bank empty)
POST /product                                   <- WRITE 2 (if product not found)
POST /invoice (with inline order+orderlines)    <- WRITE 3
```

**For Task 05 multi-product (2W):**
```
PUT  /ledger/account                            <- WRITE 1
POST /invoice (with inline order+3 orderlines)  <- WRITE 2
```

---

## System Prompt Changes Needed

### Workflow: Create invoice (line ~18)
Replace the order+orderline+invoice steps with single inline POST:
```
BEFORE:
  4. POST /order with {customer:{id}, orderDate, deliveryDate}
  5. Add order lines ONE AT A TIME: POST /order/orderline with {...}
  6. POST /invoice?sendToCustomer=true with {invoiceDate, invoiceDueDate, orders:[{id}]}

AFTER:
  4. POST /invoice?sendToCustomer=true with {
       invoiceDate, invoiceDueDate,
       orders: [{
         customer:{id}, orderDate, deliveryDate,
         orderLines: [{product:{id}, count, unitPriceExcludingVatCurrency, vatType:{id}}, ...]
       }]
     }
     This creates order+orderlines+invoice in 1 write call.
```

### Workflow: Create order + invoice + payment (Task 10, line ~26)
Same change — inline order in POST /invoice. Then PUT /:payment as before.

### DO NOT change:
- Fixed-price project milestone invoices (use POST /order for project linking)
- Timesheet invoices (need order with project reference)
- Reminder fee invoices (different flow)

---

## Expected Impact

| Task | Before | After | Gain |
|------|--------|-------|------|
| Task 05 | 1.33 (6W) | 2.0 (2W) | **+0.67** |
| Task 06 | 1.25 (4-6W) | 1.67-2.0 (2-3W) | **+0.42 to +0.75** |
| Task 10 | 2.40 (6W) | 2.40+ (3W) | **+0.0 to +0.27** |
| **Total** | | | **+1.09 to +1.69** |

This is a bigger improvement than the batch orderline fix alone, because it eliminates BOTH the POST /order AND POST /order/orderline calls.

---

## Important: This supersedes the Task 05 batch fix

The Task 05 report recommended POST /order/orderline/list (batch). This inline invoice approach is BETTER — it eliminates the order creation entirely. Use this instead.

Task 05 with inline: 6W -> 2W (vs 6W -> 4W with batch)
