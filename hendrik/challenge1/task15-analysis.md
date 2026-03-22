# Task 15 Analysis: Fixed-price project with milestone invoice

## Current Status
- **Best score**: 3.0 / 4.0 (75%)
- **All checks**: 4/4 passed (correctness is perfect)
- **Bottleneck**: Efficiency bonus — too many API calls

## Scoring Data (all Task 15 runs)

| Calls | Errors | Score | Efficiency |
|-------|--------|-------|------------|
| 7     | 0      | 3.00  | 1.50x      |
| 8     | 0      | 2.80  | 1.40x      |
| 9     | 0      | 2.80  | 1.40x      |
| 9     | 1      | 2.64  | 1.32x      |
| 9     | 1      | 2.53  | 1.27x      |
| 10    | 1      | 2.53  | 1.27x      |

To reach **4.0**, we need efficiency 2.0x, which requires **6 API calls**.

## Ideal 6-call flow (verified in sandbox + UI)

```
Call 1: GET /customer?organizationNumber=X&fields=id,name          (parallel)
Call 2: GET /project?name=X&fields=id,name,version,isFixedPrice,fixedprice,projectManager  (parallel)
Call 3: PUT /project/{id}  — set isFixedPrice=true, fixedprice, projectManager:{id}
Call 4: POST /order         — customer, orderDate, deliveryDate, project, invoiceOnAccountVatHigh:true
Call 5: POST /order/orderline — description, count, unitPriceExcludingVatCurrency, vatType:{id:3}
Call 6: POST /invoice?sendToCustomer=false — invoiceDate, invoiceDueDate, orders:[{id}]
```

Tested 2026-03-22 in sandbox (kkpqfuj-amager.tripletex.dev). All 6 calls succeeded.
Verified in Tripletex UI: project, order, invoice all correct.

## Wasted API calls the agent currently makes

### 1. GET /employee (unnecessary)
The project response already includes `projectManager` with `id`, `firstName`, `lastName`.
The prompt says "no need for a separate employee GET" but the agent does it anyway.

### 2. GET /ledger/account?number=1920 (unnecessary in happy path)
The agent checks if bank account 1920 has a bankAccountNumber set.
The prompt says "Do NOT check" but the agent ignores this.

### 3. PUT /ledger/account (unnecessary in happy path)
Sets bankAccountNumber="12345678903" on account 1920.
Only needed if the sandbox has an empty bank account — which causes invoice creation to 422.

## Bank account situation

- Fresh competition sandboxes sometimes have empty bank account on 1920.
- This causes POST /invoice to fail with 422: "Faktura kan ikke opprettes for selskapet har registrert et bankkontonummer."
- However, the competition **reuses the same sandbox** across submissions. Once any run sets the bank account, it persists.
- The best run (score 3.0, 7 calls) got lucky — bank account was already set (version=1) by a previous submission.
- If we skip the bank account check entirely: when it's already set, we get 6 calls = score 4.0. When it's not set, we get a 422 and must recover (9 calls). Best score per task is kept, so we only need one successful 6-call run.

## Root cause summary

The prompt instructions exist but are too soft. The agent ignores:
- "no need for a separate employee GET" → still calls GET /employee
- "Do NOT check or update bank account 1920" → still calls GET + PUT on ledger/account

The prompt needs stronger wording to enforce exactly 6 API calls, with bank account recovery only as a fallback after a 422.
