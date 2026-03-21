# Task 05 — Multi-Product Invoice (Efficiency Fix)

**Date:** 2026-03-21
**Score:** 1.33 (7/7 checks pass) | **Tier:** 1 (max 2.0)
**Problem:** Pure efficiency — all checks pass, too many write calls

**UPDATE:** Inline invoice approach found (see below) — better than batch orderlines. 6W -> 2W.

---

## Task Description

Create an invoice for a customer with 3 product lines (different VAT rates: 25%, 15%, 0%). The agent creates an order, adds order lines, then converts to invoice.

Example prompt: "Create an invoice for the customer Oakwood Ltd (org no. 820641566) with three product lines: Analysis Report (7049) at 19500 NOK with 25% VAT, Consulting Hours (5126) at 14200 NOK with 15% VAT, and Network Service (8806) at 8300 NOK with 0% VAT."

Verified across 10 logs — all have identical 6-write pattern.

---

## Current Approach (6 write calls)

```
GET  /customer                    (free)
GET  /product x 3                 (free)
GET  /ledger/account?number=1920  (free)
PUT  /ledger/account/xxx          <- WRITE 1 (set bankAccountNumber)
POST /order                       <- WRITE 2
POST /order/orderline             <- WRITE 3 (product 1)
POST /order/orderline             <- WRITE 4 (product 2)
POST /order/orderline             <- WRITE 5 (product 3)
POST /invoice                     <- WRITE 6
```

**6 writes, 0 errors -> efficiency = 1.33 -> score = 1.33**

---

## Root Cause

The agent creates order + orderlines + invoice as separate writes. But POST /invoice supports creating the order and orderlines inline.

---

## BEST FIX: POST /invoice with Inline Order+OrderLines (2 writes)

POST /invoice docs: "Related Order and OrderLines can be created first, or **included as new objects inside the Invoice**."

### Sandbox test:
```
POST /invoice?sendToCustomer=false with {
  invoiceDate, invoiceDueDate,
  orders: [{
    customer:{id}, orderDate, deliveryDate,
    orderLines: [
      {product:{id}, count:1, unitPriceExcludingVatCurrency:19500, vatType:{id:3}},
      {product:{id}, count:1, unitPriceExcludingVatCurrency:14200, vatType:{id:3}},
      {product:{id}, count:1, unitPriceExcludingVatCurrency:8300, vatType:{id:3}}
    ]
  }]
}
-> SUCCESS: Invoice with 3 lines, amount=52500, exclVat=42000
```

### UI verification (Invoice #36)
All 3 product lines visible in invoice PDF:
- Kontorpult: 14 200 ekskl, 3 550 mva, 17 750 inkl
- Kontorpult 2: 8 300 ekskl, 2 075 mva, 10 375 inkl
- Testprodukt: 19 500 ekskl, 4 875 mva, 24 375 inkl
- Sum: 42 000 ekskl, 10 500 mva, 52 500 inkl
- Identical to traditionally-created invoice #34

---

## Optimized Approach (2 write calls)

```
GET  /customer                         (free)
GET  /product x 3                      (free)
GET  /ledger/account?number=1920       (free)
PUT  /ledger/account/xxx               <- WRITE 1 (bankAccountNumber, if empty)
POST /invoice (with inline order+lines)<- WRITE 2 (creates order+3 lines+invoice in 1 call)
```

**2 writes, 0 errors -> expected efficiency ~2.0 -> score = 2.0**

---

## Alternative: Batch Orderlines (4 writes, SUPERSEDED)

Also tested POST /order/orderline/list (batch). It works but inline invoice is better:
- Batch: 6W -> 4W
- Inline: 6W -> 2W

Also tested inline orderLines on POST /order — does NOT work (0 lines created).

---

## System Prompt Changes Needed

### Workflow: Create invoice (line ~18)
Replace order+orderline+invoice steps with single inline POST:
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
- Fixed-price project milestone invoices (need POST /order for project linking)
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
