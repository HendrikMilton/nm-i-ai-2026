# Task 05 — Multi-Product Invoice (Efficiency Fix)

**Date:** 2026-03-21
**Score:** 1.33 (7/7 checks pass) | **Tier:** 1 (max 2.0)
**Problem:** Pure efficiency — all checks pass, too many write calls

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

The agent adds order lines ONE AT A TIME with 3 separate POST /order/orderline calls. The system prompt explicitly says "Add order lines ONE AT A TIME".

---

## Fix: Use POST /order/orderline/list (Batch Endpoint)

### Sandbox verification

**Test 1 — Batch creation:**
```
POST /order/orderline/list with [
  {order:{id}, product:{id:84383247}, count:1, unitPriceExcludingVatCurrency:19500, vatType:{id:3}},
  {order:{id}, product:{id:84383248}, count:1, unitPriceExcludingVatCurrency:14200, vatType:{id:3}},
  {order:{id}, product:{id:84383249}, count:1, unitPriceExcludingVatCurrency:8300, vatType:{id:3}}
]
-> 201: Created 3 order lines in 1 POST
```

**Test 2 — Full end-to-end flow:**
Order 402027122 -> batch 3 lines -> Invoice created
- amount (incl VAT) = 52 500.00
- amountExclVat = 42 000.00
- 3 order lines on invoice

**Test 3 — Inline orderLines on POST /order:**
```
POST /order with {customer, orderDate, orderLines:[...]}
-> Order created but orderLines = 0 (NOT supported — must use separate call)
```

### UI verification (Invoice #34)
All 3 product lines visible in invoice PDF:
- Kontorpult: 14 200 ekskl, 3 550 mva, 17 750 inkl
- Kontorpult 2: 8 300 ekskl, 2 075 mva, 10 375 inkl
- Testprodukt: 19 500 ekskl, 4 875 mva, 24 375 inkl
- Sum: 42 000 ekskl, 10 500 mva, 52 500 inkl
- Kontrollsum: correct, Kontonummer: shown, Bilag created

---

## Optimized Approach (4 write calls)

```
GET  /customer                         (free)
GET  /product x 3                      (free)
GET  /ledger/account?number=1920       (free)
PUT  /ledger/account/xxx               <- WRITE 1 (bankAccountNumber, if empty)
POST /order                            <- WRITE 2
POST /order/orderline/list             <- WRITE 3 (ALL 3 lines in 1 call)
POST /invoice                          <- WRITE 4
```

**4 writes, 0 errors -> expected efficiency ~1.67-2.0**

---

## System Prompt Changes Needed

Two lines need to change:

**Line 23 (Workflow: Create invoice):**
```
BEFORE: 5. Add order lines ONE AT A TIME: POST /order/orderline with {order:{id}, product:{id}, count, unitPriceExcludingVatCurrency, vatType:{id}}
AFTER:  5. Add ALL order lines in ONE call: POST /order/orderline/list with [{order:{id}, product:{id}, count, unitPriceExcludingVatCurrency, vatType:{id}}, ...] — NEVER add lines one at a time
```

**Line 31 (Workflow: Create order + invoice + payment, Task 10):**
```
BEFORE: 3. Add order lines ONE AT A TIME: POST /order/orderline with {order:{id}, product:{id}, count:1, unitPriceExcludingVatCurrency, vatType:{id:3}}
AFTER:  3. Add ALL order lines in ONE call: POST /order/orderline/list with [{order:{id}, product:{id}, count:1, unitPriceExcludingVatCurrency, vatType:{id:3}}, ...] — NEVER add lines one at a time
```

DO NOT change lines 77, 127, 147, 154 — those are single-line tasks (milestone invoices, project invoices) where batch isn't needed.

---

## Note: Task 06 is a DIFFERENT task type

Task 06 is single-product create+send invoice (not multi-product). It has variable writes (4-6) depending on whether product/customer need to be created. Requires separate analysis.

---

## Expected Impact

| Task | Before | After | Gain |
|------|--------|-------|------|
| Task 05 | 1.33 | 1.67-2.0 | +0.34 to +0.67 |
| Task 10 | 2.40 | 2.40+ | +0.0 to +0.27 |

Also benefits any future multi-line invoice/order task.
