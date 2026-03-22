# Task 22 — Receipt Expense: Root Cause Found

**Date:** 2026-03-22
**Impact:** Task 22 scores 0/5 EVERY attempt (11 attempts, 0 points ever)
**Status:** ROOT CAUSE CONFIRMED via sandbox + UI testing

---

## Root Cause

The agent registers receipt expenses as **manual ledger vouchers** (`POST /ledger/voucher` with credit to 2910). The evaluator expects a **supplier invoice** (`POST /supplierInvoice` with credit to 2400 + supplier linked).

## Evidence

### UI confirmation
Tripletex's "Enkel føring" (Simple entry) for receipts creates a **Leverandørfaktura** (supplier invoice), NOT a manual voucher:
- Credit goes to **2400 Leverandørgjeld** (with supplier entity linked)
- Payment via **1920 Manuelt betalt nettbank** (company card)
- NOT 2910 Gjeld til ansatte (employee debt)

### Sandbox test — Bilag comparison
Created both approaches in sandbox and compared in Tripletex UI:

**Bilag 73 — Supplier invoice (CORRECT):**
```
7140 Reisekostnad           11 280,00  (MVA kode 1, 25%)
2400 Leverandørgjeld, NSB  -14 100,00  (supplier linked!)
2710 Inng. MVA høy sats      2 820,00  (auto-generated)
```

**Bilag 70 — Manual voucher (CURRENT, WRONG):**
```
7140 Reisekostnad           12 589,29  (MVA kode 13, 12%)
2910 Gjeld til ansatte     -14 100,00  (no supplier)
2712 Inng. MVA lav sats      1 510,71  (auto-generated)
```

### Differences

| Field | Current (wrong) | Expected (correct) |
|-------|----------------|-------------------|
| API endpoint | `POST /ledger/voucher` | `POST /supplierInvoice` |
| Credit account | 2910 (Gjeld til ansatte) | 2400 (Leverandørgjeld) |
| Supplier entity | Not created | Created + linked on postings |
| VAT rate | costCategory rate (12% for Tog) | 25% (receipt states "herav MVA 25%") |
| MVA account | 2712 (lav sats) | 2710 (høy sats) |
| Net amount | 12 589.29 | 11 280.00 |
| Send to ledger | Not needed | Required (`PUT /voucher/:sendToLedger`) |

## Why ALL attempts scored 0

- Manual voucher approach: 0/5 — wrong credit account, no supplier, often wrong VAT
- TravelExpense approach: 0/5 — leaves expense in DELIVERED state, no voucher posted
- Even with correct VAT (25%): 0/5 — still missing supplier entity + 2400 credit

## Proposed Fix

Change Task 22 workflow to use the **supplier invoice flow** (same as Task 11):

```
## Workflow: Receipt/expense registration (Task 22)
Register receipt expenses as supplier invoices — NOT manual vouchers or travelExpense.
1. In parallel: GET /department?name=<dept>&fields=id,name,
   GET /travelExpense/costCategory?fields=id,description,account(id,number),vatType(id)
   (for expense account mapping only — do NOT use travelExpense API)
2. Create supplier from receipt: POST /supplier with {name:<store>, organizationNumber:<org_nr>,
   email:"post@example.org", invoiceEmail:"post@example.org"}
3. POST /supplierInvoice with {
     invoiceDate:<receipt_date>, invoiceDueDate:<receipt_date + 14 days>,
     supplier:{id}, invoiceNumber:"<receipt_date>",
     amountCurrency: -<item_amount_incl_vat>,
     voucher: {date:<receipt_date>, description:"<item> - <store>", postings: [
       {date:<receipt_date>, description:"<item>", account:{id:<expense_account>},
        supplier:{id}, department:{id}, amountGross:<item_amount>,
        amountGrossCurrency:<item_amount>, vatType:{id:1}, invoiceNumber:"<receipt_date>", row:1},
       {date:<receipt_date>, description:"<item>", account:{id:<2400>},
        supplier:{id}, amountGross:-<item_amount>,
        amountGrossCurrency:-<item_amount>, vatType:{id:0}, row:2}
     ]}
   }
   CRITICAL: amountCurrency must be NEGATIVE.
   CRITICAL: Always use vatType:{id:1} (25% MVA) — the receipt states "herav MVA 25%".
   Do NOT use the costCategory vatType — it's for travel expense flow only.
   Use the costCategory ONLY for the expense account number mapping.
4. PUT /ledger/voucher/{voucherId}/:sendToLedger with empty body {}
Total: 2 write calls (3 if supplier created).
```

## Expense Account Mapping (from costCategory)

| Receipt item | costCategory match | Expense account |
|-------------|-------------------|-----------------|
| Togbillett | Tog | 7140 |
| USB-hub | Data/EDB-kostnad | 6810 |
| Skrivebordlampe | Kontorrekvisita | 6800 |
| Hotell/Overnatting | Hotell | 7140 |
| Kaffemøte | Møte, kurs, oppdatering | 6860 |
| Middag representasjon | Representasjon - fradragsb. | 7350 |

## Expected Score After Fix

| Metric | Value |
|--------|-------|
| Current | 0.0 (0/5 checks, 11 attempts) |
| After fix | 4-6 points (Tier 3, 2-3 write calls) |
