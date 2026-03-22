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

### Round 3 (09:27-09:30)

| 09:27 | T18 | 8/8 | 3p/0f | 22.0s | 0 | perfect |
| 09:28 | T22 | 0/10 | 0p/5f | 48.0s | 0 | still 0. supplierInvoice approach not working |
| 09:29 | T21 | 0/14 | 0p/10f | ?s | ? | **DISASTER** — agent too slow, scorer timed out |

**Task 21 — 0/14 timeout issue**: Agent spent 1.5 min on occupation code lookup before
creating employee. POST /employee happened at 09:31:20 but scoring was already done.
The employee creation is the FIRST thing that should happen — not the last.
System prompt says "create employee first" but agent doesn't follow it on this variant.
This is a priority ordering issue — employee should be step 1, occupation code lookup in parallel.

**Task 22 — still 0/5 consistently**: 3 attempts now, all 0/5 with supplierInvoice approach.
The approach itself seems correct (supplier created, invoice created, sent to ledger).
Need to investigate: maybe payment registration is required, or maybe the expense account
mapping is wrong, or maybe we need to include the receipt PDF as attachment on the voucher.

### Round 4 (~09:31-09:35) — slow, one long-running task

50/300 daily submissions used. Autoloop running but waiting on a long processing task.

## Patterns so far

**Consistently perfect:** T02, T03, T04, T05, T07, T08, T09, T10, T13, T15, T16, T17, T18, T25, T26
**Improved:** T11 (0→8/8!), T19 (0→20/22→8/8), T20 (2→7/10), T21 (12→8/8 sometimes)
**Still broken:** T22 (0/10 always), T27 (2/10), T30 (0/10)
**Inconsistent:** T21 (8/8 or 0/14 - speed issue), T24 (10/10 or 7.5/10), T28 (7/7 or 5/10), T29 (8/11)

**Biggest remaining opportunities:**
1. T22 — 0/10, worth 4.5pts. supplierInvoice approach still fails. Maybe needs payment step.
2. T30 — 0/10, worth 4.5pts. Haven't seen a run with the new prompt yet.
3. T27 — 2/10, currency/disagio. No workflow in prompt for this.
4. T21 — sometimes 0/14 due to slowness. Need to ensure employee created FIRST.
5. T29 — stuck at 8/11. 2 checks always fail.

### Round 5 (09:36)

| 09:36 | T30 | 0/10 | 0p/6f | 77.8s | 0 | 1209 used correctly + remaining balance. STILL 0/6 |

**Task 30 — deep mystery.** Everything looks correct now:
- Created account 1209 ✅
- All 3 depreciation vouchers credit 1209 ✅
- Prepaid reversal uses remaining balance (5295.87, not 63550) ✅
- Tax calculated after adjustments ✅
- Separate vouchers ✅

Yet still 0/6! Possibilities:
1. Depreciation amounts wrong? 90200/7=12885.71, 484450/9=53827.78, 246550/5=49310 — seem correct
2. Maybe checker expects expense account per asset (not generic 6010 for all)
3. Maybe the prepaid expense account is wrong (used 6300? or something else?)
4. Maybe the tax amount is wrong because prepaid balance calc is off
5. Maybe 1209 needs to be a different account type or have specific properties

This needs sandbox testing to figure out — we're doing everything the fix doc says but still scoring 0.

### Leaderboard @ 09:40 UTC
**Us: #23 with 76.24 points** (30/30 tasks touched)
- #1: the-grind 104.26
- Gap to top 10: ~7 points
- Gap to #1: ~28 points

We started at 66.75 yesterday. Up +9.5 points overall.
Key gains: T11 (0→perfect), T19 (0→mostly perfect), T20 (2→7/10), T24 (new perfect scores).
Still losing points on: T22 (0), T30 (0→6.5!), T27 (2/10), slow T21 runs (0).

### Round 6 (09:43-09:46)

| 09:43 | T30 | 6.5/10 | 4p/2f | 66.1s | 0 | **NEW BEST!** Checks 1-4 pass, 5-6 fail |
| 09:44 | T18 | 8/8 | 3p/0f | 48.6s | 0 | perfect |

**Task 30 BREAKTHROUGH — 6.5/10!** Was always 0/10. Checks 1-4 pass (depreciation + prepaid).
Checks 5-6 fail — likely tax calc or structural. The 1209 + remaining balance fix IS working.
Different variant scored differently — some variants may have calculation edge cases.

### Task 27 — currency/disagio
This is a currency exchange loss task. Agent finds invoice, calculates disagio, but 3 checks fail.
Likely needs a specific voucher for the exchange difference on account 8160 (Disagio).
The agent seems to be calculating but not posting the correction properly.

### Task 24 — Check 3 variant
Was getting 10/10, now 7.5/10. Check 3 fails on this variant. Probably a specific error type
that the prompt doesn't handle well (missing VAT correction maybe — Elias added vatType 1 fix).
