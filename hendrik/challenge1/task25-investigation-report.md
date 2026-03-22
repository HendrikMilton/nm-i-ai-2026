# Task 25 Investigation Report — 2026-03-22

## Current Score
- **4.8 / 6.0 points** (Tier 3, max possible 6.0, top team has 6.0)
- Raw score: 10/10 (all checks pass every run)
- Issue is purely **efficiency bonus** — too many API calls

## Task Description
Find overdue invoice, post reminder fee (debit 1500, credit 3400), create and send reminder invoice, register partial payment of 5000 NOK.

## Scoring Formula
- normalized = correctness × tier × efficiency
- 4.8 = 1.0 × 3.0 × 1.6 (efficiency bonus 1.6)
- 6.0 = 1.0 × 3.0 × 2.0 (max efficiency bonus 2.0)

## Current API Calls (best run: 9 calls, 0 errors)

| # | Call | Needed? |
|---|------|---------|
| 1 | GET /ledger/account?number=3400 | YES — need account ID for product |
| 2 | GET /invoice/paymentType | YES — need paymentTypeId |
| 3 | GET /ledger/account?number=1920 | **NO — never used, pure waste** |
| 4 | GET /invoice | YES — find overdue invoice |
| 5 | POST /product | YES — create reminder fee product |
| 6 | POST /order | **NO — replace with inline** |
| 7 | POST /order/orderline | **NO — replace with inline** |
| 8 | POST /invoice?sendToCustomer=true | YES — but should include inline order+orderlines |
| 9 | PUT /invoice/:payment | YES — partial payment |

## Optimizations (verified in sandbox)

### 1. Remove GET /ledger/account?number=1920 (saves 1 call)
Agent fetches bank account info but never uses it in this task. Pure waste.

### 2. Inline order+orderlines in POST /invoice (saves 2 calls)
Instead of 3 separate calls (POST /order → POST /order/orderline → POST /invoice), use 1 call with inline data:
```json
POST /invoice?sendToCustomer=true
{
  "invoiceDate": "2026-03-22",
  "invoiceDueDate": "2026-04-05",
  "orders": [{
    "customer": {"id": 123},
    "orderDate": "2026-03-22",
    "deliveryDate": "2026-03-22",
    "orderLines": [{
      "product": {"id": 456},
      "count": 1,
      "unitPriceExcludingVatCurrency": 70,
      "vatType": {"id": 0}
    }]
  }]
}
```
This pattern is already used successfully in Task 10 workflow. Verified working in sandbox — returns 201 with correct amount=70.

### 3. Product with account:{number:3400} — DOES NOT WORK
Tested creating product with `account:{number:3400}` instead of `account:{id:xxx}` to skip the GET lookup. Returns 422: "account.name: Kan ikke være null." The account ID lookup is required.

## Optimized Flow (6 API calls)

| # | Call | Notes |
|---|------|-------|
| 1 | GET /invoice | find overdue, parallel |
| 2 | GET /ledger/account?number=3400 | account ID, parallel |
| 3 | GET /invoice/paymentType | paymentTypeId, parallel |
| 4 | POST /product | purregebyr, vatType 0, account 3400 |
| 5 | POST /invoice?sendToCustomer=true | inline order+orderlines |
| 6 | PUT /invoice/:payment | partial 5000 |

**6 calls total, 0 errors. Down from 9 (33% reduction).**

## Prompt Change Needed

Lines 207-216 in system-prompt.ts. Change steps 3-4:

Current:
```
3. POST /order with customer, then POST /order/orderline with product — sequential.
4. POST /invoice?sendToCustomer=true with the order.
```

New:
```
3. POST /invoice?sendToCustomer=true with INLINE order+orderlines:
   {invoiceDate, invoiceDueDate, orders:[{customer:{id}, orderDate, deliveryDate,
     orderLines:[{product:{id}, count:1, unitPriceExcludingVatCurrency:<fee>, vatType:{id:0}}]}]}
```

Also: remove GET /ledger/account?number=1920 from step 1 parallel calls. Only need GET /invoice, GET /ledger/account?3400, GET /invoice/paymentType.

## Confidence
- **95%** — both optimizations verified in sandbox
- All checks already pass 10/10, only efficiency changes
- Risk is very low
