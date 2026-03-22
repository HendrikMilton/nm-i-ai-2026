# Log Analysis — Challenge 1 Failures & Fixes

**Date**: 2026-03-22
**Logs analyzed**: ~116 files in logs/, focus on most recent 50+
**Current total score**: 71.30 / 180 (max 6.0 × 30 tasks)

---

## Current Leaderboard (Best Scores Per Task)

| Task | Best Score | Max | Status |
|------|-----------|-----|--------|
| 01 | 1.50 | 6.0 | Needs work |
| 02 | 2.00 | 6.0 | OK |
| 03 | 2.00 | 6.0 | OK |
| 04 | 2.00 | 6.0 | OK |
| 05 | 1.33 | 6.0 | Needs work |
| 06 | 1.25 | 6.0 | Needs work |
| 07 | 2.00 | 6.0 | OK |
| 08 | 2.00 | 6.0 | OK |
| 09 | 2.40 | 6.0 | OK |
| 10 | 2.40 | 6.0 | OK |
| **11** | **0.00** | 6.0 | **ZERO — highest priority** |
| **12** | **0.00** | 6.0 | **ZERO — highest priority** |
| 13 | 2.50 | 6.0 | OK |
| 14 | 4.00 | 6.0 | Good |
| 15 | 2.80 | 6.0 | OK |
| 16 | 2.67 | 6.0 | OK |
| 17 | 3.50 | 6.0 | Good |
| 18 | 4.00 | 6.0 | Good |
| 19 | 2.45 | 6.0 | OK |
| **20** | **0.60** | 6.0 | **Critical** |
| 21 | 2.57 | 6.0 | OK |
| **22** | **0.00** | 6.0 | **ZERO — highest priority** |
| **23** | **0.00** | 6.0 | **ZERO — highest priority** |
| 24 | 2.25 | 6.0 | OK |
| 25 | 4.50 | 6.0 | Great |
| 26 | 4.00 | 6.0 | Good |
| 27 | 6.00 | 6.0 | PERFECT |
| **28** | **1.50** | 6.0 | **Low** |
| 29 | 2.73 | 6.0 | OK |
| **30** | **1.80** | 6.0 | **Low** |

**Total: 71.30** — Biggest gains come from fixing zero-score tasks (11, 12, 22, 23).

---

## CRITICAL FAILURES (Score = 0)

### Task 11 — Supplier Invoice from Text (Score: 0.00, leaderboard shows 0 but one recent log got 1.0)

**What it is**: Register a supplier invoice from text (not PDF). E.g., "INV-2026-4647 from Cascade SARL, 30000 NOK TTC, account 6860, 25% deductible VAT."

**What the agent does**: Creates supplier invoice via `POST /supplierInvoice` correctly. Gets 2/4 checks passing (Checks 1 & 2), but Checks 3 & 4 always fail.

**Root cause — Wrong vatType on debit posting**:
- Agent uses `vatType:{id:1}` (utgående MVA / output VAT 25%)
- Should use `vatType:{id:3}` (inngående MVA / input/deductible VAT 25%)
- vatType 1 = seller's output VAT; vatType 3 = buyer's input/deductible VAT
- For supplier invoices, the buyer is DEDUCTING VAT, so it must be vatType 3

**Evidence** (from `2026-03-21T20-12-52-733Z.log`):
```
POST /supplierInvoice body={"invoiceDate":"2026-03-21", ...,
  "voucher":{"postings":[
    {"account":{"id":375057987}, "amountGross":30000, "vatType":{"id":1}, ...},   ← WRONG: should be id:3
    {"account":{"id":375057755}, "amountGross":-30000, "vatType":{"id":0}, ...}
  ]}}
```
Score: 2/4 checks passed, normalized_score: 1.0

**Fix in system-prompt.ts**: In the "Supplier invoice from text prompt" and "Supplier invoice from PDF" workflows, change the debit posting vatType from `{id:1}` to `{id:3}`. The workflow already says `vatType:{id:1}` in the template — change it to `vatType:{id:3}` for the expense posting.

Specifically, in the Task 20 workflow line:
```
{date, description, account:{id:expense}, supplier:{id}, amountGross:<totalInclVat>, amountGrossCurrency:<totalInclVat>, vatType:{id:1}, invoiceNumber, row:1}
```
Change `vatType:{id:1}` → `vatType:{id:3}` (input VAT, not output VAT).

---

### Task 12 — Payroll / Salary Transaction (Score: 0.00)

**What it is**: Execute payroll for an employee. Base salary + bonus.

**What the agent does**: Finds employee, sets dateOfBirth/bankAccountNumber, creates employment, creates salary transaction, then tries to finalize with `PUT /tsk/salaryv2/transaction/{id}/:run` — gets **403 Forbidden**.

**Root cause — 403 on salary run endpoint**:
- The agent dismisses the 403 as "normal per the workflow" but this means the payroll is NEVER finalized
- The salary transaction is created but not processed — no lønnsbilag (payslip voucher) is generated
- All 4 checks fail because the actual payroll voucher entries don't exist

**Evidence** (from `2026-03-21T20-05-14-713Z.log`):
```
PUT /tsk/salaryv2/transaction/6958048/:run → 403
{"message":"You do not have permission to access this feature."}
```
API calls: 13, errors: 1, all 4 checks failed.

**Possible fixes**:
1. The sandbox might not have permission for `/tsk/salaryv2/transaction/:run`. Try the regular salary payment endpoint instead
2. Try `PUT /salary/transaction/{id}/:payment` or `PUT /salary/payslip/{id}/:payment` as an alternative
3. Check if there's a different salary finalization endpoint in the OpenAPI spec
4. The transaction might need to be in a specific state before `:run` works
5. Try posting the payroll directly as a ledger voucher with the correct salary accounts (5000 debit, 2930/2600 credit) as a workaround — though this might not pass checks that expect a proper salary transaction

**Investigation needed**: Search the OpenAPI spec for alternative salary/payroll endpoints. The current `:run` endpoint under `/tsk/` may be a test-only endpoint.

---

### Task 22 — Receipt/Expense Registration (Score: 0.00, 5/5 checks fail EVERY time)

**What it is**: Register a single expense item from a receipt PDF to a specific department. E.g., "We need the Kaffemøte expense from this receipt posted to department Utvikling."

**What the agent does**:
1. GET employee, department, costCategory, paymentType
2. POST /travelExpense (creates travel expense)
3. PUT /travelExpense/{id}/convert (converts to type 0 = ansattutlegg)
4. POST /travelExpense/cost (adds cost with correct category)
5. PUT /travelExpense/{id} (sets department + travel details)
6. PUT /travelExpense/:deliver (submits)

All API calls succeed (0 errors), yet ALL 5 checks fail.

**Evidence** (from `2026-03-21T19-15-15-767Z.log`):
- Prompt: "Precisamos da despesa de Kaffemøte deste recibo registada no departamento Utvikling"
- Receipt PDF: kvittering_pt_04.pdf (has multiple items including Kaffemøte 6600 NOK)
- Agent correctly identifies Kaffemøte, uses "Representasjon - fradragsb." category, 6600 NOK, Utvikling department
- Expense delivered successfully with state=DELIVERED
- Score: 0/10, all 5 checks failed

**Possible root causes**:
1. **Title becomes empty after convert**: After `PUT /travelExpense/{id}/convert`, the `title` field becomes `""`. The checker might require a non-empty title on the expense.
2. **Receipt has MULTIPLE items**: The PDF typically contains several items (e.g., Togbillett 14100, Skrivebordlampe 3200, Kaffemøte 6600). The task asks for ONE specific item. Maybe the checker expects ALL items from the receipt, not just the one mentioned?
3. **Wrong expense type entirely**: Maybe the checker expects a direct accounting voucher (POST /ledger/voucher) rather than the travelExpense/cost workflow for receipt items?
4. **The convert step changes behavior**: Converting from travel (type 1) to expense (type 0) might not be the right approach. Maybe the checker expects a type-1 travel expense, not a converted type-0.
5. **Missing fields on the cost**: The cost might need `vatType` explicitly set, or `quantity`, or other fields.

**Investigation needed**:
- Try WITHOUT the convert step (leave as travel expense type 1)
- Try posting all receipt items, not just the one mentioned
- Try setting `title` explicitly after convert
- Check if checks are looking for specific voucher postings on certain ledger accounts

---

### Task 23 — Bank Reconciliation from CSV (Score: 0.00)

**What it is**: Match a bank statement CSV against open invoices/supplier invoices. Register payments, handle bank fees and interest, create reconciliation.

**What the agent does**:
1. Fetches invoices, supplier invoices, payment types, accounts, periods
2. Parses CSV (semicolon-separated)
3. Matches customer payments to invoices (PUT /invoice/:payment)
4. Posts supplier payments as vouchers (POST /ledger/voucher)
5. Posts bank fees/interest as vouchers
6. Creates bank reconciliation (POST /bank/reconciliation)
7. BUT: runs out of the 25 max steps before closing the reconciliation

**Evidence** (from `2026-03-21T20-09-26-073Z.log`):
- 33 API calls, 1 error (400 on amountOutstanding field)
- Used all 25 steps
- Reconciliation created but NOT closed (isClosed:false)
- Agent then tried to post an opening balance voucher (100000 to 1920/2050) because accounting balance (54935.84) didn't match bank closing balance (154935.84)
- No SCORING data found — may have timed out or scored 0

**Root causes**:
1. **Agent uses wrong fields**: `amountOutstanding` doesn't exist on SupplierInvoiceDTO (causes 400)
2. **Runs out of steps**: 25 max steps is not enough for the complex reconciliation workflow
3. **Opening balance issue**: The agent discovers a 100,000 NOK discrepancy and tries to post an opening balance voucher, but this shouldn't be needed — the opening balance should already exist
4. **Reconciliation not closed**: Even if all payments are registered, the reconciliation must be closed with `isClosed:true` and the correct version
5. **Adjustment step missing**: Bank fees/interest should be added via `PUT /bank/reconciliation/{id}/:adjustment`, not as separate vouchers
6. **Period selection**: Agent might pick wrong accounting period

**Fix in system-prompt.ts**:
- Remove `amountOutstanding` from supplier invoice queries (not a valid field)
- Streamline the workflow to use fewer steps (batch operations where possible)
- Ensure the reconciliation close step (PUT with isClosed:true) always happens
- Don't post opening balance vouchers — trust the existing data
- Use `:adjustment` endpoint for fees/interest, not manual vouchers

---

## HIGH-PRIORITY FAILURES (Score < 2.0)

### Task 20 — Supplier Invoice from PDF (Score: 0.60, only Check 1 passes)

**What it is**: Register a supplier invoice from an attached PDF.

**Root cause**: Similar to Task 11 — vatType issue. The workflow in system-prompt.ts explicitly uses `vatType:{id:1}` on the expense posting, but it should be `vatType:{id:3}` for input/deductible VAT.

Additionally, in some logs the agent uses `POST /ledger/voucher` directly instead of `POST /supplierInvoice`. The workflow should always use `/supplierInvoice`.

**Fix**: Same as Task 11 — change `vatType:{id:1}` → `vatType:{id:3}` in the supplier invoice workflow debit posting.

---

### Task 30 — Simplified Year-End Closing (Score: 1.80)

**What it is**: Post depreciation, prepaid reversal, and tax provision for year-end closing.

**Root cause — Conflict between prompt and system-prompt.ts**:
- The task prompt explicitly says "Use account 1209 for accumulated depreciation"
- But system-prompt.ts says "ALWAYS credit the ASSET ACCOUNT DIRECTLY (e.g. 1250, 1230, 1210) — NEVER create or use accumulated depreciation accounts (1209, 1029, etc.)"
- The agent follows system-prompt.ts (credits asset directly), but the scorer checks for postings to the accumulated depreciation account (1209)

**Evidence** (from `2026-03-21T20-24-25-613Z.log`):
- Prompt: "Use account 6010 for depreciation expense and **1209 for accumulated depreciation**"
- Agent: Credits 1210, 1240, 1250 directly (ignoring 1209 instruction)
- All 6 checks failed

**Other issues in this task**:
- Account 8700 (Skattekostnad) sometimes doesn't exist and must be created — agent handles this
- Tax calculation depends on correct P&L result aggregation

**Fix in system-prompt.ts**:
- Remove the blanket "NEVER use accumulated depreciation accounts" instruction for Task 30
- Instead: "If the task specifies an accumulated depreciation account (e.g. 1209), USE IT as the credit account. Only credit the asset account directly if no accumulated depreciation account is specified."
- This way Task 26 (monthly closing, which works well at 4.0) continues to credit asset accounts directly, while Task 30 follows the prompt's instruction

---

### Task 28 — Analyze Ledger + Create Projects/Activities (Score: 1.50, 3/5 checks fail)

**What it is**: Analyze expense accounts for Jan vs Feb increases, create 3 internal projects and activities, link them.

**Root cause — Activity linking or naming issues**:
- Agent creates projects and activities, then links them via POST /project/projectActivity
- But 3/5 checks still fail consistently
- Checks 1, 2, 4 fail in some runs; Checks 2, 3, 4 in others

**Possible issues**:
1. The activity names might not match what the checker expects
2. The project names might need to match the account names exactly
3. The top-3 expense increase calculation might be wrong
4. The projectActivity linking might need different parameters

**Investigation needed**: Read a full Task 28 log carefully to see exact calculations and naming.

---

### Task 05 — Department Creation? (Score: 1.33)
### Task 06 — Create Invoice (Score: 1.25)
### Task 01 — Simple Employee Creation (Score: 1.50)

These are lower-tier tasks but consistently underperform. Not enough log data from recent runs to diagnose precisely. Worth investigating when higher-priority tasks are fixed.

---

## COMMON ERROR PATTERNS

### 1. Wrong vatType for Supplier Invoices
- **Affects**: Tasks 11, 20
- **Pattern**: Using vatType 1 (output VAT) instead of vatType 3 (input/deductible VAT)
- **Fix**: Change `vatType:{id:1}` → `vatType:{id:3}` in supplier invoice workflow

### 2. Invalid API Field Names (400 errors)
- `amountOutstanding` is NOT a field on SupplierInvoiceDTO (use `amount` instead)
- `year` is NOT a field on AccountingPeriodDTO (use `number` or date fields)
- `description` is NOT a field on InvoiceDTO for queries
- `name` is NOT a field on EmployeeDTO for queries (use firstName/lastName)

### 3. 403 on Salary Run
- `PUT /tsk/salaryv2/transaction/:run` always returns 403
- Need to find an alternative finalization endpoint or workaround

### 4. Step Exhaustion
- Bank reconciliation (Task 23) uses all 25 steps without completing
- Need more efficient workflows or higher maxSteps for complex tasks

### 5. Reconciliation Not Closed
- Agent creates bank reconciliation but forgets/can't close it
- Must always end with PUT /{id} with isClosed:true

---

## RECOMMENDED FIX PRIORITY (by estimated point gain)

| Priority | Task | Current | Est. Gain | Fix Difficulty | Fix Description |
|----------|------|---------|-----------|----------------|-----------------|
| 1 | 11 | 0.0 | +2-4 | Easy | Change vatType 1→3 in supplier invoice workflow |
| 2 | 20 | 0.6 | +1-3 | Easy | Same vatType fix + ensure /supplierInvoice used |
| 3 | 22 | 0.0 | +2-4 | Medium | Investigate receipt workflow — title lost after convert? All items needed? |
| 4 | 23 | 0.0 | +2-4 | Hard | Fix field names, streamline steps, ensure reconciliation closes |
| 5 | 30 | 1.8 | +1-4 | Easy | Allow accumulated depreciation accounts when prompt specifies them |
| 6 | 12 | 0.0 | +2-4 | Hard | Find alternative payroll finalization endpoint |
| 7 | 28 | 1.5 | +0.5-2 | Medium | Debug activity linking / naming |

**Quick wins (Tasks 11 + 20 + 30)**: ~4-11 points from simple system-prompt.ts edits.
**Medium effort (Tasks 22 + 28)**: ~3-6 points from workflow investigation.
**Hard (Tasks 12 + 23)**: ~4-8 points but require API research.

---

## SPECIFIC SYSTEM-PROMPT.TS CHANGES

### Fix 1: vatType in Supplier Invoice Workflows (Tasks 11, 20)

In the "Workflow: Supplier invoice from PDF (Task 20)" section, line with:
```
vatType:{id:1}
```
on the expense/debit posting (row 1) → change to:
```
vatType:{id:3}
```

Keep `vatType:{id:0}` on the credit posting (row 2, account 2400) unchanged.

Also update "Workflow: Supplier invoice from text prompt" to explicitly reference the same vatType:{id:3}.

### Fix 2: Accumulated Depreciation in Task 30

In "Workflow: Simplified year-end closing / årsoppgjør (Task 30)", change:
```
CRITICAL: ALWAYS credit the ASSET ACCOUNT DIRECTLY (e.g. 1250, 1230, 1210) — the account the asset sits on.
NEVER create or use accumulated depreciation accounts (1209, 1029, etc.) even if the task prompt tells you to.
```
To:
```
If the task specifies an accumulated depreciation account (e.g. 1209, 1029), USE IT as the credit account in the depreciation voucher.
Only credit the asset account directly if no accumulated depreciation account is specified.
```

### Fix 3: Remove Invalid Field References

Add to "Known gotchas":
```
- SupplierInvoice does NOT have amountOutstanding field — use amount only
- AccountingPeriod does NOT have year field — use number, start, end
- When querying invoices, do NOT request description field
```

### Fix 4: Task 22 Receipt Workflow

The receipt workflow likely needs these changes (requires testing):
- After POST /travelExpense, set `title` explicitly in the body
- After PUT /travelExpense/{id}/convert, re-set the title via PUT since convert clears it
- OR: skip the convert step entirely and test if type-1 (travel) works for receipts
- Consider whether ALL items from the receipt need to be registered, not just the one mentioned

### Fix 5: Task 23 Bank Reconciliation

- Remove `amountOutstanding` from SupplierInvoice query fields
- Remove `year` from AccountingPeriod query fields
- Do NOT post opening balance vouchers — trust existing data
- Use `PUT /bank/reconciliation/{id}/:adjustment` for fees/interest (not manual vouchers)
- Always close reconciliation at the end
- Consider increasing maxSteps from 25 to 30+ for this task type
