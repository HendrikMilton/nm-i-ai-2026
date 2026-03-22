## Log Monitor Notes

Started: 2026-03-22 ~09:30 UTC

| Time (UTC) | Task | Score | Checks | Time | Errors | Notes |
|------------|------|-------|--------|------|--------|-------|
| 09:12 | T07 | 7/7 | 2p/0f | 15.0s | 0 | perfect |
| 09:13 | T16 | 8/8 | 4p/0f | 38.7s | 1 | perfect |
| 09:14 | ? | 8/8 | 4p/0f | 40.1s | 1 | perfect, unknown task |
| 09:18 | T19 | 8/8 | 7p/0f | 26.8s | 0 | perfect! was 20/22 before |
| 09:19 | T27 | 2/10 | 1p/3f | 75.2s | 1 | currency task, struggling |
| 09:21 | ? | ?/? | 0p/0f | ?s | ? | pending/in progress |
| 09:11 | T26 | 10/10 | 6p/0f | 49.9s | 0 | perfect, consistent |
| 09:13 | T22 | 0/10 | 0p/5f | 20.2s | 0 | supplierInvoice approach, still 0. see notes below |
| 09:22 | T22 | 0/10 | 0p/5f | 31.2s | 0 | same - supplierInvoice+sendToLedger, still 0/5 |
| 09:21 | T24 | 7.5/10 | 3p/1f | 55.1s | 0 | Check 3 fails. was 10/10 before, variant issue? |
| 09:19 | T27 | 2/10 | 1p/3f | 75.2s | 1 | currency/disagio task. only Check 1 pass |
| 09:23 | ? | ?/? | pending | | | in progress |

## Thoughts

### Task 22 — still 0/5 despite supplierInvoice approach
The agent now does: POST /supplier → POST /supplierInvoice → PUT sendToLedger. All 200s.
But still 0/5. Looking at the data:
- Uses account 6800 (Kontorrekvisita) for "Oppbevaringsboks" — seems reasonable
- Credits 2400 with supplier linked ✓
- vatType:{id:1} (25%) ✓
- sendToLedger called ✓
- amountCurrency: -3950 ✓

What could be wrong? Possibilities:
1. The expense account might be wrong — "Oppbevaringsboks" could map to a different account
2. The receipt might have a specific item the scorer checks for that we're not matching
3. Maybe the scorer checks department on BOTH postings (we only set it on debit)
4. Maybe the scorer checks for payment registration (PUT /supplierInvoice/:addPayment) after creating
   — the receipt says "Betalt med: Bedriftskort" which means it's already paid

**Hypothesis**: The scorer might expect the invoice to be PAID (registered payment via company card).
If so, we need: POST /supplierInvoice → sendToLedger → PUT /:addPayment or register payment.

### Round 2 (09:23-09:25)

| 09:23 | T04 | 6/6 | 4p/0f | 11.1s | 0 | perfect |
| 09:24 | T11 | 8/8 | 4p/0f | 20.4s | 0 | **NEW BEST! Was 4/8, now PERFECT.** supplierInvoice+sendToLedger working |
| 09:24 | T14 | 8/8 | 5p/0f | 27.3s | 15 | perfect but 15 errors — sloppy execution |
| 09:25 | T14 | 12/14 | 9p/1f | 49.4s | 0 | Check 5 fails. Different variant, 10-check version |

**Task 11 — 8/8 PERFECT!** This is huge. Was stuck at 4/8 (2 checks failing). The supplierInvoice
+ sendToLedger approach now works perfectly. That's +4 points potential gain on the leaderboard.

**Task 14** — 12/14 variant has Check 5 failing. This is the "credit note" task with more checks.
Check 5 could be about the credit note date or amount. The 8/8 variant works perfectly though.

### Task 27 — currency/disagio
This is a currency exchange loss task. Agent finds invoice, calculates disagio, but 3 checks fail.
Likely needs a specific voucher for the exchange difference on account 8160 (Disagio).
The agent seems to be calculating but not posting the correction properly.

### Task 24 — Check 3 variant
Was getting 10/10, now 7.5/10. Check 3 fails on this variant. Probably a specific error type
that the prompt doesn't handle well (missing VAT correction maybe — Elias added vatType 1 fix).
