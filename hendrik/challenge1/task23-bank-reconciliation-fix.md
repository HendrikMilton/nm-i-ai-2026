# Task 23 — Bank Reconciliation (CSV) — Analysis

**Date:** 2026-03-21
**Current score:** 0.00 (0/2 checks)
**Status:** PARTIALLY INVESTIGATED — bank reconciliation API found but import format unclear
**Tier:** 3 (x3 multiplier)

---

## Task Description

"Avstem bankutskrifta (vedlagt CSV) mot opne fakturaer i Tripletex. Match innbetalingar til kundefakturaer og utbetalingar til leverandorfakturaer. Handter delbetalingar korrekt."

Translation: "Reconcile the bank statement (attached CSV) against open invoices in Tripletex. Match incoming payments to customer invoices and outgoing payments to supplier invoices. Handle partial payments correctly."

## What the Agent Did (WRONG)

1. Parsed the CSV bank statement
2. Fetched open customer invoices via GET /invoice
3. Tried to find supplier invoices (GET /supplierInvoice — got 400 on amountOutstanding field)
4. Matched CSV lines to invoices manually
5. Registered payments directly via PUT /invoice/{id}/:payment
6. Score: 0/2 checks — both failed

The agent bypassed the entire bank reconciliation system and just registered payments manually.

## Bank Reconciliation API (Found)

Tripletex has a dedicated bank reconciliation system:

```
POST /bank/statement/import       — Upload bank statement file
POST /bank/reconciliation         — Create a bank reconciliation
POST /bank/reconciliation/match   — Create matches between bank transactions and postings
PUT  /bank/reconciliation/match/:suggest — Auto-suggest matches
GET  /bank/statement/transaction  — List bank transactions
```

### Schemas

**BankReconciliation:** {account, accountingPeriod, voucher, transactions, isClosed, type, bankAccountClosingBalanceCurrency}

**BankReconciliationMatch:** {bankReconciliation, type, transactions, postings}

## Problem: CSV Format

The task provides a CSV with columns: `Dato;Forklaring;Inn;Ut;Saldo`

This doesn't match any standard bank format:
- NORDEA_CSV → expects: Tid og dato, Tjenestenavn, Filnavn, etc.
- DANSKE_BANK_CSV → expects: Bokfort dato, Rentedato, Tekst, Belop, etc.
- DNBNOR_CSV, SPAREBANK1_CSV, HANDELSBANKEN_CSV → 404 (not available on sandbox)

The CSV format is custom and no fileFormat parameter works for import.

## Actual CSV Content (from log)

```csv
Dato;Forklaring;Inn;Ut;Saldo
2026-01-17;Innbetaling fra Lunde AS / Faktura 1001;9437.50;;109437.50
2026-01-19;Innbetaling fra Neset AS / Faktura 1002;8187.50;;117625.00
2026-01-21;Innbetaling fra Kvamme AS / Faktura 1003;15750.00;;133375.00
2026-01-22;Innbetaling fra Stolsvik AS / Faktura 1004;7375.00;;140750.00
2026-01-25;Innbetaling fra Stolsvik AS / Faktura 1005;11050.00;;151800.00
2026-01-27;Betaling Leverandor Brekke AS;;-6100.00;145700.00
2026-01-30;Betaling Leverandor Kvamme AS;;-18400.00;127300.00
2026-01-31;Betaling Leverandor Vik AS;;-12300.00;115000.00
2026-02-02;Bankgebyr;;-967.04;114032.96
2026-02-03;Bankgebyr;1097.62;;115130.58
```

Contains:
- 5 incoming customer payments (some full, some partial)
- 3 outgoing supplier payments
- 2 bank fee lines

## What Needs More Investigation

1. **Can we create bank transactions manually?** No POST endpoint for individual transactions — only import
2. **Is there a way to create a reconciliation without importing?** POST /bank/reconciliation might work with manually created data
3. **Should the agent just register payments correctly?** Maybe the scorer checks payment registrations, not the reconciliation entity. But the agent scored 0 even though it registered 5 customer payments
4. **Supplier payments missing** — the agent only handled incoming payments. The CSV has 3 outgoing supplier payments that were never registered. This could be the critical missing piece
5. **Bank fees** — the CSV has bank fee lines that need to be accounted for (probably as a ledger voucher)
6. **Should we investigate the UI "Bank" or "Bankavstemming" module?** This could reveal the correct flow

## Possible Correct Flow

```
1. Parse CSV — identify customer payments, supplier payments, bank fees
2. Register customer invoice payments: PUT /invoice/{id}/:payment (existing approach)
3. Register supplier invoice payments: POST /supplierInvoice/{id}/:addPayment
4. Register bank fees: POST /ledger/voucher (debit bank fee account, credit bank 1920)
5. Maybe: POST /bank/reconciliation to create reconciliation entity
6. Maybe: POST /bank/reconciliation/match to link transactions
```

## Risk Assessment

This is a complex task that may require:
- Full bank reconciliation API integration (undocumented flow)
- Supplier payment handling (untested)
- Bank fee posting
- Partial payment handling (both customer and supplier)

The fact that the agent got 0/2 even after correctly registering 5 customer payments suggests the scorer needs something fundamentally different — possibly the bank reconciliation entity itself, or the supplier payments were the actual checks.

## Recommendation

- **High effort, uncertain reward** — the bank reconciliation API flow is complex and untested
- **Quick win:** at minimum, handle ALL lines in the CSV — supplier payments and bank fees, not just customer payments
- **UI investigation recommended:** check Bank → Bankavstemming in the Tripletex UI to see the correct flow
