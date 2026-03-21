# Task 23 — Bank Reconciliation: Deep Analysis v2

**Date:** 2026-03-21
**Score:** 0/10 on ALL runs (never scored above 0)
**Tier:** 3 (max 6.0)
**Potential gain:** +3.0 to +4.5 points

---

## ROOT CAUSE: Agent Cannot Read CSV Files (Code Bug in agent.ts)

**File: `src/agent.ts` lines 86-91**

The code handles images and PDFs correctly, but CSV files fall into the else branch:

```javascript
// Current code:
if (f.mime_type.startsWith('image/')) {
    // image handling ✓
} else if (f.mime_type === 'application/pdf') {
    // PDF handling ✓
} else {
    // CSV/text files: ONLY passes filename, DROPS content!
    userContent.push({
        type: 'text',
        text: `[Attached file: ${f.filename} (${f.mime_type}), base64 length: ${f.content_base64.length}]`,
    });
}
```

The agent only sees: `[Attached file: bankutskrift_pt_05.csv (text/csv), base64 length: 952]`

It then HALLUCINATES the CSV content. Proof from 18:49 log:

| Field | Agent's hallucinated CSV | ACTUAL CSV |
|-------|--------------------------|------------|
| Lines | 6 | 11 |
| Dates | March 2026 | January-February 2026 |
| Customer payments | 4 (wrong amounts) | 5 |
| Supplier payments | 0 | 3 (totaling 43,150) |
| Fee/interest lines | 1 (45 kr) | 3 (216.09, 349.14, 331.14) |
| Closing saldo | 55,955 | 122,560.81 |

Everything is fabricated because the agent never received the data.

### Fix (agent.ts)

Add handler BEFORE the else for text-based files:

```javascript
} else if (f.mime_type.startsWith('text/') || f.filename.endsWith('.csv') || f.filename.endsWith('.txt')) {
    const decoded = Buffer.from(f.content_base64, 'base64').toString('utf-8');
    userContent.push({
        type: 'text',
        text: `Content of ${f.filename}:\n${decoded}`,
    });
} else {
    userContent.push({
        type: 'text',
        text: `[Attached file: ${f.filename} (${f.mime_type}), base64 length: ${f.content_base64.length}]`,
    });
}
```

Note: check for `.csv` extension as fallback in case the platform sends `application/csv` or `application/octet-stream` instead of `text/csv`.

---

## SECONDARY: System Prompt Efficiency Fixes

Even after the CSV fix, two preventable errors waste writes every run.

### Error 1: POST /bank/reconciliation missing type field

Agent sends without `type` -> 422: "type: Kan ikke vaere null"
Then retries with `type:"MANUAL"` -> 201

**Fix:** Always include `type:"MANUAL"` in step 5 of the workflow.

Tested on sandbox: works on first try. No 422.

### Error 2: PUT close uses wrong version

After PUT /:adjustment, version increments (0 -> 1).
Agent sends version:0 -> 409 conflict.
Then GETs version, retries -> 200.

**Fix:** Always GET reconciliation after adjustment to get current version before closing.

Tested on sandbox: works on first try. No 409.

---

## TERTIARY: Fee/Interest Direction Handling

Reconciliation adjustment types have FIXED directions:

| Type | Effect on 1920 | Account |
|------|---------------|---------|
| Bankgebyr | Money OUT (-) | Debit 7770, Credit 1920 |
| Kortgebyr | Money OUT (-) | Same as Bankgebyr |
| Renteinntekter | Money IN (+) | Debit 1920, Credit 8050 |
| Rentekostnader | Money OUT (-) | Debit expense, Credit 1920 |

Negative amounts NOT allowed (422: "Ma vaere minimum 0").

CSV lines can appear in EITHER Inn or Ut column. Rules:

| CSV line | In Inn column (money IN) | In Ut column (money OUT) |
|----------|--------------------------|--------------------------|
| Bankgebyr | Use voucher: debit 1920 +amt, credit 7770 -amt | Use adjustment type Bankgebyr |
| Renteinntekter | Use adjustment type Renteinntekter | Use adjustment type Rentekostnader |
| Bankgebyr (normal) | Rare — fee refund | Use adjustment type Bankgebyr |

All tested on sandbox. Verified in UI (Juli 2026 reconciliation).

---

## QUATERNARY: Supplier Payments

POST /supplierInvoice/:addPayment unreliable on sandbox. Alternative approach verified:

Register supplier payments as voucher postings:
```
POST /ledger/voucher with:
  Row 1: account 2400, supplier:{id}, amountGross: +amount, vatType:{id:0}
  Row 2: account 1920, amountGross: -amount, vatType:{id:0}
```

Tested: balance decreases correctly. Shows as "Ut av konto" in UI.

The agent must match supplier names from CSV ("Betaling Fornecedor Costa Lda") to existing supplier invoices by supplier name and/or amount.

---

## Accounting Period Selection

The CSV may span multiple months (e.g., Jan 16 to Feb 7). The reconciliation needs ONE period.

**Rule:** Use the period containing the LAST transaction date in the CSV.
- CSV last date 2026-02-07 -> use February period (2026-02-01 to 2026-03-01)
- CSV last date 2026-03-20 -> use March period

Also: do NOT request `year` field from /ledger/accountingPeriod (causes 400 error). Use `fields=id,name,start,end,number`.

---

## Full Sandbox + UI Verification

| Test | Sandbox | UI Verified |
|------|---------|-------------|
| Customer payment (PUT /invoice/:payment) | 201 | Inn pa konto |
| Supplier payment (POST voucher 2400/1920) | 201 | Ut av konto |
| Bankgebyr adjustment (Ut) | 200 | Bankgebyr section |
| Bankgebyr refund (Inn, via voucher) | 201 | Inn pa konto |
| Rentekostnader adjustment (Ut) | 200 | Rentekostnader section |
| Renteinntekter adjustment (Inn) | 200 | Verified |
| Multiple adjustments in 1 call | 200 | All shown |
| type:"MANUAL" on POST reconciliation | 201 first try | Created |
| GET version before close | No 409 | Correct version |
| Closing balance = accounting balance | avvik=0 | Godkjenn checked |
| Full reconciliation close | 200 | Mai + Juli 2026 |

UI screenshots verified for Mai 2026 (full flow) and Juli 2026 (fee/interest handling).

---

## Updated System Prompt Workflow

```
## Workflow: Bank reconciliation from CSV (Task 23)
CRITICAL: The CSV file content is provided as text. Read it carefully line by line.

1. In parallel: GET /invoice (open), GET /supplierInvoice (open, do NOT use amountOutstanding field),
   GET /invoice/paymentType, GET /ledger/accountingPeriod?fields=id,name,start,end,number (NO year field),
   GET /bank/reconciliation/paymentType?fields=id,description, GET /ledger/account?number=1920&fields=id

2. Parse CSV carefully. The CSV uses semicolons (;) as separator:
   Dato;Forklaring;Inn;Ut;Saldo
   - Inn column filled + "Innbetaling" = customer payment -> match by invoice number in description
   - Ut column filled + "Leverandor/Fornecedor" = supplier payment -> match by supplier name
   - "Bankgebyr" in Ut = bank fee -> reconciliation adjustment type Bankgebyr
   - "Bankgebyr" in Inn = fee refund -> POST /ledger/voucher (debit 1920, credit 7770)
   - "Renteinntekter" in Inn = interest income -> adjustment type Renteinntekter
   - "Renteinntekter" in Ut = interest expense -> adjustment type Rentekostnader
   - LAST Saldo value = closing balance for reconciliation

3. Register customer payments: PUT /invoice/{id}/:payment
   Match by customer name from CSV to invoice customer. Use date FROM CSV.
   paidAmount = Inn value (handles partial payments automatically)

4. Register supplier payments: POST /ledger/voucher
   {date:<CSV_date>, description:"Betaling <supplier>", postings:[
     {account:{id:2400}, supplier:{id}, amountGross:<positive_amount>, vatType:{id:0}},
     {account:{id:1920}, amountGross:<negative_amount>, vatType:{id:0}}
   ]}

5. POST /bank/reconciliation with {
     account:{id:<1920>}, accountingPeriod:{id:<period_matching_last_CSV_date>},
     bankAccountClosingBalanceCurrency:<LAST_SALDO_FROM_CSV>,
     isClosed:false, type:"MANUAL"
   }

6. Add ALL fee/interest adjustments in ONE call:
   PUT /bank/reconciliation/{id}/:adjustment with [{postingDate, description, amount:<POSITIVE>,
   paymentType:{id}}]
   Use correct payment type based on direction (see rules above).
   Amount must be positive (negative not allowed).

7. GET /bank/reconciliation/{id} to get current version
8. Close: PUT /bank/reconciliation/{id} with {id, version:<from_GET>, ..., isClosed:true}
   Only succeeds when avvik = 0 (accounting balance = bank statement closing balance).
   If all payments + fees registered correctly and closing balance = CSV last saldo, avvik will be 0.
```

---

## Expected Impact

| Fix | Effect |
|-----|--------|
| CSV reading fix (agent.ts) | Agent sees real data instead of hallucinating |
| All payments registered correctly | avvik = 0 with correct closing balance |
| type:MANUAL + version GET | -2 wasted writes, -2 errors |
| **Score** | **0 -> 3.0 to 4.5** |

This is the single biggest improvement available across all tasks.
