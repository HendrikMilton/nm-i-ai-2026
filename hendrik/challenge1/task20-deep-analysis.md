# Task 20 — Deep Analysis & Confirmed Fix

**Date:** 2026-03-22
**Analysts:** Gabriel + Claude
**Current score:** 2.4/6.0 (5/6 checks pass, Check 5 always fails)
**Task:** Register supplier invoice from attached PDF

---

## Scoring progression

| Phase | Change | Checks | Score |
|-------|--------|--------|-------|
| v1 | Manual voucher, vatType 1 | 1/6 (Check 1 only) | 0.6 |
| v2 | Switch to POST /supplierInvoice | 4/6 (Checks 1-4) | 2.1 |
| v3 | Add PUT /:sendToLedger | 5/6 (Checks 1-4, 6) | 2.4 |
| **fix** | **Upload PDF attachment to voucher** | **6/6** | **4.0-6.0** |

## Important correction

The LONG_LOG_RESEARCH_RESULTS.md recommended changing `vatType:{id:1}` to `vatType:{id:3}`. This is **WRONG**:
- vatType 1 = "Fradrag inngående avgift, høy sats" = **INPUT VAT** (correct for purchases!)
- vatType 3 = "Utgående avgift, høy sats" = **OUTPUT VAT** (for sales — would break score)

**Do NOT change vatType. It is already correct.**

## Root cause of Check 5 failure

**The PDF invoice is never attached to the voucher.**

Evidence:
- Task 11 (supplier invoice from TEXT, no PDF): **4 checks, all pass** (score 4.0)
- Task 20 (supplier invoice from PDF): **6 checks** = same 4 + Check 5 + Check 6
- Check 6 (sendToLedger) was fixed → now passes
- Check 5 is the ONLY remaining failure
- The agent receives the PDF but never uploads it to Tripletex

## Sandbox verification

Tested the full flow in sandbox and verified in Tripletex UI:

1. `POST /supplier` — create supplier ✓
2. `POST /supplierInvoice` — create invoice with postings ✓
3. `PUT /ledger/voucher/{id}/:sendToLedger` — book voucher ✓
4. **`POST /ledger/voucher/{id}/attachment`** — upload PDF as multipart/form-data ✓

After upload, the PDF renders correctly in the Tripletex UI (Bilag #80):
- Shows as "Leverandørfaktura (enkel føring)"
- PDF displayed in right panel
- Postings: 6300 debit 67,300 / 2400 credit -84,125 / 2710 MVA 16,825
- Kontrollsum: 0.00

## Required code changes

The agent currently has no way to upload files — `tripletex.ts` only supports JSON requests.

### 1. `tripletex.ts` — add upload method
Add a method that sends multipart/form-data instead of JSON:
```typescript
async uploadAttachment(voucherId: number, fileContent: Buffer, fileName: string) {
    const formData = new FormData();
    formData.append('file', new Blob([fileContent]), fileName);
    const res = await fetch(`${this.baseUrl}/ledger/voucher/${voucherId}/attachment`, {
        method: 'POST',
        headers: { Authorization: this.auth },
        body: formData,
    });
    // ... logging, response handling
}
```

### 2. `tools.ts` — add upload tool
Add a tool that the agent can call with a voucher ID and filename. The file content comes from `req.body.files[]` (base64), which needs to be passed through to the tool.

### 3. `system-prompt.ts` — add upload step to Task 20 workflow
After sendToLedger, add:
```
5. Upload the invoice PDF: tripletex_upload_attachment with voucher ID and file
```

## Invoice PDF format (consistent across all samples)

All PDFs follow the same structure:
- Supplier name, org.nr, address
- Fakturanummer, Fakturadato, Forfallsdato
- Beskrivelse + Beløp (net amount)
- MVA 25%: (VAT amount)
- Totalt: (gross amount)
- Konto: (expense account number)
- Bankkonto: (supplier bank account)
