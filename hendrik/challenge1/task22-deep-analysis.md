# Task 22 — Deep Analysis & Proposed Fix

**Date:** 2026-03-22
**Analysts:** Gabriel + Claude
**Current score:** 0.0 (14 attempts, 0/5 checks every time)
**Top teams:** 6.0 points (Tier 3, perfect)

---

## Summary

Task 22 receives a receipt PDF with multiple items and asks to register ONE specific item to a specific department. Every approach tried so far scores 0/10 (5/5 checks fail). We identified that the **travelExpense approach WITHOUT the convert step** has never been tested in competition.

## All approaches tried (all score 0/10)

### 1. Travel expense with convert (earliest approach)
```
POST /travelExpense → PUT /convert → POST /travelExpense/cost → PUT (dept) → PUT /:deliver
```
- **Problem confirmed in sandbox:** `PUT /convert` clears the `title` to `""` and changes `type` from 1 to 0
- Agent only delivered, never approved
- No voucher created (no ledger postings)

### 2. Manual voucher (replaced approach 1)
```
POST /ledger/voucher (debit expense account, credit 2910)
```
- Creates correct ledger postings
- But NO travelExpense object exists — if checker queries travelExpense API, finds nothing

### 3. Supplier invoice (current approach)
```
POST /supplier → POST /supplierInvoice → PUT /:sendToLedger
```
- Creates correct ledger postings with supplier linked to 2400
- But NO travelExpense object exists
- Also `supplierInvoice.amount` is always 0 (normal for simple invoices)

## Sandbox testing results

| Test | Result |
|------|--------|
| Convert clears title? | YES — title becomes `""`, type changes 1→0 |
| travelExpense without convert? | Works — title preserved, type stays 1 |
| Deliver without travelDetails? | Works — only need employee + cost + department |
| Approve after deliver? | Works — state goes OPEN→DELIVERED→APPROVED |
| createVoucher via API? | Returns 204 but voucher stays null (only UI button works) |
| PaymentType in competition? | Only "Privat utlegg" available (same as sandbox) |
| Checker can find travelExpense? | Yes — queryable via GET /travelExpense regardless of type |

## The untested approach

**travelExpense WITHOUT convert, with deliver + approve:**

```
1. POST /travelExpense {employee:{id}, title:"<item> - <store>", department:{id}}
2. POST /travelExpense/cost {travelExpense:{id}, costCategory:{id}, paymentType:{id}, date, amountCurrencyIncVat, comments}
3. PUT /travelExpense/:deliver?id={id}
4. PUT /travelExpense/:approve?id={id}
```

This creates a proper travelExpense object with:
- Title preserved (not cleared by convert)
- Type = 1 (original, not converted to 0)
- Correct cost category and amount
- Correct department
- State = APPROVED

### Why this might work
- The checker likely queries the travelExpense API
- All 3 previous approaches either had NO travelExpense (approaches 2+3) or a CORRUPTED one (approach 1 with convert)
- This is the only approach that creates a clean travelExpense with all correct fields

### Cost category mapping for expense account
| Receipt item | costCategory | Account |
|-------------|-------------|---------|
| Togbillett | Tog | 7140 |
| USB-hub / Tastatur | Data/EDB-kostnad or Kontorrekvisita | 6810 or 6800 |
| Oppbevaringsboks | Kontorrekvisita | 6800 |
| Overnatting | Hotell | 7140 |
| Kaffemøte | Representasjon - fradragsb. or Møte, kurs | 7350 or 6860 |

### System prompt change needed
Replace the current Task 22 workflow (supplier invoice) with the travelExpense flow above. Key points:
- NO convert step
- Set department at creation or via PUT before deliver
- Use costCategory for account+VAT mapping (let Tripletex handle VAT via the category)
- Deliver AND approve
- PaymentType: use the first result from GET /travelExpense/paymentType
