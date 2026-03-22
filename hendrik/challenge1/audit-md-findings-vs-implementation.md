# Audit: .md Analysis Files vs Implementation Status

Date: 2026-03-22
Score at yesterday 6pm: 66.75
Score now: 78.39 (+11.64)
Rank: 18

## Score Changes Since Yesterday 6pm

| Task | Before | After | Change |
|------|--------|-------|--------|
| 11 | 0.00 | 4.00 | +4.00 |
| 20 | 0.60 | 2.40 | +1.80 |
| 24 | 2.25 | 3.75 | +1.50 |
| 09 | 2.40 | 3.00 | +0.60 |
| 10 | 2.40 | 3.00 | +0.60 |
| 23 | 0.00 | 0.60 | +0.60 |
| 25 | 4.50 | 4.80 | +0.30 |
| 19 | 2.45 | 2.73 | +0.27 |
| 06 | 1.25 | 1.50 | +0.25 |
| 15 | 2.80 | 3.00 | +0.20 |
| 30 | 1.80 | 1.95 | +0.15 |
| 16 | 2.67 | 2.33 | -0.33 (regression) |

## Fixes That Were Implemented AND Worked

- Task 11: Supplier invoice from text — went from 0 to 4.00 (max for Tier 2)
- Task 24: Ledger corrections — went from 2.25 to 3.75
- Task 20: PDF invoice extraction — went from 0.60 to 2.40
- Task 25: Reminder fee — went from 4.50 to 4.80
- Task 19: Employee creation — went from 2.45 to 2.73
- Task 26: Monthly closing — hit 4.00 (max for Tier 2)

## Fixes That Were Implemented But Still Score 0

### Task 12 — Payroll (score=0.00, 23 attempts)
- Files: `task12-payroll-fix.md`, `task12-payroll-split-postings-fix.md`, `TASK_12_SALARY_API_FIX.md`, `payroll-finalization-fix.md`
- Current approach: Manual ledger voucher with split postings (5000/2600/2910)
- Result: 0/4 checks pass in ALL 23 attempts. This approach is provably dead.
- **UNIMPLEMENTED FIX**: `TASK_12_SALARY_API_FIX.md` recommends switching to salary/transaction API with finalization endpoint. This was never applied.
- Potential gain: +2.0 points

### Task 22 — Receipt/Expense (score=0.00, 15 attempts)
- Files: `task22-receipt-expense-fix.md`, `task22-receipt-expense-fix-v2.md`, `task22-receipt-expense-fix-v3.md`, `task22-travelexpense-fix.md`, `task22-deep-analysis.md`
- Current approach: travelExpense without convert, with deliver+approve
- Result: Latest workflow IS in the system prompt, but 8/9 runs still score 0.
- Issue: Agent appears to ignore the workflow or deviate from it. The fix v3 (no convert, deliver then approve) was sandbox-tested and worked, but the agent doesn't follow it consistently.
- Potential gain: +4.0-4.5 points if agent compliance is fixed

## Fixes Written But NOT Implemented

### Task 29 — Complete Project Lifecycle (score=2.73, max 6.0)
- Files: `task29-investigation-report.md`, `task29-deep-analysis.md`, `TASK_29_FIX.md`
- Root cause proven: Agent uses POST /ledger/voucher for supplier cost. Evaluator checks via GET /supplierInvoice. Manual vouchers are invisible to that endpoint.
- `task29-investigation-report.md`: Proven in sandbox+UI that POST /supplierInvoice + PUT /:sendToLedger fixes the issue. Same pattern as Task 11 which scores 4.0.
- `TASK_29_FIX.md`: Says remove x1.25 multiplication on supplier cost and use vatType:0
- **STATUS: PARTIALLY IMPLEMENTED** — supplierInvoice approach may be in prompt but the VAT handling fix from TASK_29_FIX.md is NOT applied. Checks 5-6 still fail.
- Potential gain: +3.27 points

### Task 20 — Supplier Invoice from PDF (score=2.40, max 4.0)
- Files: `task20-deep-analysis.md`, `task20-supplier-invoice-pdf-fix-v3.md`
- `task20-deep-analysis.md`: Check 5 (the one that fails) = missing PDF attachment on the voucher. Needs POST /ledger/voucher/{id}/attachment to upload the original PDF.
- **STATUS: NOT IMPLEMENTED** — requires adding upload method to tripletex.ts and upload tool to tools.ts. No code changes were made.
- Potential gain: +1.6 points

### Task 16 — Timesheet + Project Invoice (score=2.33, max 4.0)
- Files: `task16-optimization-findings.md`, `task16-timesheet-invoice-fix.md`
- `task16-optimization-findings.md`: Thoroughly tested in sandbox+UI. Inline invoice (order+orderlines in single POST) reduces writes from 7 to 2-3. Employee PUT not needed. Description field on orderline prevents 422.
- **STATUS: NOT IMPLEMENTED** — findings documented and verified but system prompt not updated.
- Potential gain: +1.67 points

### Task 12 — Payroll (alternative approach)
- File: `TASK_12_SALARY_API_FIX.md`
- Recommends salary/transaction API instead of manual voucher
- **STATUS: NOT IMPLEMENTED** — current manual voucher approach has scored 0 in ALL attempts
- Potential gain: +2.0 points

## Summary: Potential Points From Unimplemented .md Fixes

| Task | Current | Potential | Gain | Fix Source |
|------|---------|-----------|------|------------|
| 29 | 2.73 | ~5.5 | +2.77 | task29-investigation-report.md, TASK_29_FIX.md |
| 12 | 0.00 | ~2.0 | +2.00 | TASK_12_SALARY_API_FIX.md |
| 16 | 2.33 | ~4.0 | +1.67 | task16-optimization-findings.md |
| 20 | 2.40 | ~4.0 | +1.60 | task20-deep-analysis.md |
| 22 | 0.00 | ~4.0 | +4.00 | task22-deep-analysis.md (agent compliance issue) |
| **Total** | | | **~12.04** | |

Current total: 78.39. If all fixes applied: ~90+ points.

## Recommendation

The .md analysis files contain correct, sandbox-verified fixes. The main issue is that several were never implemented in the system prompt or code. Priority order for implementation:

1. **Task 22** (+4.0) — Fix is in prompt but agent ignores it. May need stronger instructions or different prompt structure.
2. **Task 29** (+2.77) — Apply supplierInvoice pattern + VAT fix from TASK_29_FIX.md
3. **Task 12** (+2.0) — Switch to salary/transaction API per TASK_12_SALARY_API_FIX.md
4. **Task 16** (+1.67) — Apply inline invoice optimization per task16-optimization-findings.md
5. **Task 20** (+1.6) — Add PDF attachment upload tool per task20-deep-analysis.md
