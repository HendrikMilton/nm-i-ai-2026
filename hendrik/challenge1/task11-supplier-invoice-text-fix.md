# Task 11 — Supplier Invoice from Text: Root Cause Analysis

## Status: 0/4 checks, every attempt. Tier 2 task (max 4.0 points).

## Root Cause

Agent uses `POST /ledger/voucher` instead of `POST /supplierInvoice`.
This creates accounting entries but NO `supplierInvoice` object — checker finds nothing, all 4 checks fail.

## Evidence

| Source | Finding |
|--------|---------|
| 5 log files | Agent always calls `POST /ledger/voucher`, never `/supplierInvoice` |
| Sandbox API | `POST /supplierInvoice` creates queryable supplier invoice; `POST /ledger/voucher` does not |
| Tripletex UI | `/supplierInvoice` voucher labeled "Leverandorfaktura (enkel foring)"; direct voucher has no such label |
| Leaderboard | #1 team (Kult Byra) scores 3.33 on Task 11 — confirms task is solvable, Tier 2 |
| OpenAPI spec | `POST /supplierInvoice` is undocumented but works — agent can't discover it without explicit instructions |

## Why Agent Uses Wrong Endpoint

system-prompt.ts lines 56-57 say:
> `## Workflow: Supplier invoice from text prompt`
> `Same as Task 20 but data comes from prompt text instead of PDF. Use POST /supplierInvoice with the same structure.`

Too vague. Agent either doesn't match the prompt to this workflow or defaults to the simpler `/ledger/voucher`.
Early attempt (Mar 20 21:50) shows agent DID try `/supplierInvoice` but failed 11 times due to wrong field names.

## Task 11 Prompt Pattern

Always contains (in Norwegian/German/Nynorsk):
- Invoice number: `INV-2026-XXXX`
- Supplier name + org number
- Total amount inklusiv MVA
- Expense account number (varies: 6500, 6540, 7000, etc.)
- VAT rate: always 25%
- No due date in prompt

## Fix: Replace lines 56-57 in system-prompt.ts

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
CRITICAL: amountCurrency MUST be NEGATIVE.
CRITICAL: expense account number varies per prompt — always use the account from the task.
Total: 1 write call.
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

## Expected Score After Fix

| Metric | Value |
|--------|-------|
| Current | 0.0 (0/4 checks, every time) |
| After fix | ~3.5-4.0 (4/4 checks, 1 write call) |
| Top team | 3.33 |
| Can beat #1 | Yes — 1 write call = best possible efficiency |

## API Call Budget

| Call | Type | Cost |
|------|------|------|
| GET /supplier | GET | Free |
| GET /ledger/account (expense) | GET | Free |
| GET /ledger/account (2400) | GET | Free |
| POST /supplierInvoice | WRITE | 1 call |
| **Total writes** | | **1** |
