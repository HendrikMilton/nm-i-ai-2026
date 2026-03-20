# Challenge 1 — Log Analysis & Scoring Assessment

**Date:** 2026-03-20
**Logs analyzed:** 18:11 – 18:55 UTC (13 real submissions + 8 empty logs from wrong-server routing)

---

## Summary

| Log timestamp | Task type | Score | Max | Status |
|---|---|---|---|---|
| 18:11 | Order→Invoice→Payment (Portuguese) | 8/8 | 8 | ALL PASSED |
| 18:13 – 18:22 | (6 empty logs) | — | — | Hit wrong server (routing issue) |
| 18:23 | Reverse payment (Spanish) | 8/8 | 8 | ALL PASSED |
| 18:25 | Fixed-price project + milestone invoice (Spanish) | **6/8** | 8 | **Check 2 FAILED** |
| 18:27 | Create supplier (English) | **6/7** | 7 | **Check 5 FAILED** |
| 18:45 | Test ping | — | — | N/A |
| 18:46–18:47 | (2 empty logs) | — | — | Hit wrong server |
| 18:48 | Create product (Spanish) | 7/7 | 7 | ALL PASSED |
| 18:49 | Create employee with employment (Nynorsk) | 8/8 | 8 | ALL PASSED |
| 18:50 | Timesheet + project invoice (Norwegian) | 8/8 | 8 | ALL PASSED |
| 18:52 | Create project (French) | 7/7 | 7 | ALL PASSED |
| 18:54 | Create+send invoice (Nynorsk) | 7/7 | 7 | ALL PASSED |
| 18:55 | **Run payroll** (Nynorsk) | **0/8** | 8 | **ALL 4 FAILED** |

**Pass rate (real tasks):** 8/11 perfect, 2 partial, 1 total failure

---

## Issue 1: PAYROLL — 0/8 (CRITICAL)

**Task:** "Køyr løn for Brita Stølsvik — grunnløn 36000 kr + eingongsbonus 15400 kr"

**What the agent did:**
Created a manual journal voucher (`POST /ledger/voucher`) with debit 5000 / credit 1920 for 51400 NOK.

**Why this fails:**
The competition checks for a **salary transaction** (`POST /salary/transaction`), NOT a manual voucher. The system prompt already has the correct instructions for salary/transaction, but the agent ignored them and used a simpler voucher approach.

**Root cause confirmed on sandbox:**
- `POST /salary/transaction?generateTaxDeduction=true` works correctly
- Salary types available: `2000` (Fastlønn, id varies), `2002` (Bonus, id varies)
- Requires: employee with employment + division, salary type lookup, proper payslip structure

**The agent needs to:**
1. Find employee
2. Look up salary types (GET /salary/type?number=2000, GET /salary/type?number=2002)
3. Ensure employee has employment with division
4. POST /salary/transaction with payslips array containing specifications for each pay component

**Fix:** The system prompt already describes this correctly under "### Run payroll (salary transaction)". The agent simply chose the wrong approach. Need stronger language in the prompt to enforce using `/salary/transaction` and **explicitly forbid** using `/ledger/voucher` for payroll.

---

## Issue 2: FIXED-PRICE PROJECT + MILESTONE — 6/8 (Check 2 failed)

**Task:** "Set fixed price 457650 NOK on project 'Implementación ERP', invoice 25% as milestone"

**What the agent did:**
1. Found customer + employee ✓
2. Created project with isFixedPrice=true, fixedprice=457650 ✓
3. Created order linked to project with invoiceOnAccountVatHigh=true ✓
4. Added order line: 114412.50 NOK (25% of 457650) ✓
5. Created invoice ✓

**What Check 2 might be checking:**
- The order line description was "Pago parcial - 25% del precio fijo" — the system prompt example says `"Milestone payment - X%"` as the description format. The competition may check for specific keywords.
- Alternatively, Check 2 could verify the project's `fixedprice` field or the milestone percentage calculation.
- Another possibility: The department GET was unnecessary (wasted call, but shouldn't cause check failure).

**Potential fix:** Use the exact description format from system prompt: `"Milestone payment - 25%"` instead of translating to the task language. Or investigate if there's a specific Tripletex "akonto" mechanism that should be used differently.

---

## Issue 3: SUPPLIER CREATION — 6/7 (Check 5 failed)

**Task:** "Register supplier Silveroak Ltd, org 889586605, email faktura@silveroakltd.no"

**What the agent did:**
- POST /supplier with: name, organizationNumber, email, invoiceEmail (both set to same value), showProducts: true

**What Check 5 might be checking:**
- The prompt doesn't mention a phone number, and the system prompt says "ALSO set phoneNumber field if a phone number is given" — no phone was given, so this seems fine.
- `showProducts: true` was set but never asked for — the sandbox default is `false`. This extra field might cause a mismatch.
- Possibly the check verifies `isCustomer: false` explicitly, or `language`, or some other default field.

**Potential fix:** Don't set `showProducts` unless asked. Keep supplier creation minimal: only name, organizationNumber, email, invoiceEmail.

---

## Issue 4: EMPTY LOGS (8 logs, routing problem)

**Cause:** Two servers sharing the same port (4001) on the remote VPS via SSH tunnels. Requests were load-balanced randomly — ~50% hit the wrong server which had no agent running.

**Status:** FIXED — now using separate port 4002 with /gabriel/solve path prefix and dedicated k8s ingress rule.

---

## Efficiency Observations

| Task | API calls | Unnecessary calls | Notes |
|---|---|---|---|
| Order+Invoice+Payment | 10 | 0 | Clean execution |
| Reverse payment | 4 | 0 | Clean |
| Fixed-price project | 9 | 1 | GET /department unnecessary |
| Create supplier | 1 | 0 | Clean, but missing field? |
| Create product | 2 | 0 | Clean |
| Create employee | 3 | 0 | Clean |
| Timesheet+invoice | 12 | 0 | Complex task, reasonable |
| Create project | 3 | 0 | Clean |
| Create+send invoice | 8 | 0 | Clean |
| Payroll (WRONG) | 4 | 4 | ALL wrong — used voucher |

---

## Recommended System Prompt Changes

### Priority 1: Fix payroll (0/8 → potential 8/8)
- Add explicit rule: **"NEVER use /ledger/voucher for payroll. ALWAYS use /salary/transaction."**
- Ensure the payroll section is prominent and clear

### Priority 2: Fix supplier creation
- Remove `showProducts` from default supplier creation
- Keep creation minimal: name, organizationNumber, email, invoiceEmail

### Priority 3: Fix fixed-price project milestone
- Standardize milestone description to exactly: `"Milestone payment - X%"`
- Remove unnecessary GET /department for project creation (already noted in prompt but agent still did it)

### Priority 4: Efficiency
- The agent fetches GET /department even for project creation (prompt says not to)
- Could save 1 API call per project task

---

## UI Verification: Payroll (Lønn) Flow

Verified the correct payroll flow in the Tripletex sandbox UI:

### Steps in UI (Lønn → Ny lønnsutbetaling):
1. **Setup wizard** (one-time): Lønnsutbetalinger (etterskudd), Pensjonsavtale (Ingen), Feriepenger (5 uker, 12%)
2. **Ny lønnsutbetaling**: Select period (Mars 2026), select employee, click "Opprett lønnsutbetaling"
3. **Lønnsdetaljer**: Add salary lines via "Ny rad +"

### Payslip structure confirmed in UI:

| Lønnsrader | Antall | Sats | Beløp | Til utbetaling |
|---|---|---|---|---|
| 2000 Fastlønn | 1 | 36,000.00 | 36,000.00 | 36,000.00 |
| 2002 Bonus | 1 | 15,400.00 | 15,400.00 | 15,400.00 |
| 6000 Skattetrekk (auto) | — | — | -20,560.00 | -20,560.00 |
| **Total** | | | | **30,840.00** |

- Tax deduction auto-generated at 40% of gross (51,400) = 20,560
- This matches `generateTaxDeduction=true` in the API
- The 6000 Skattetrekk line is system-generated, not manually added

### Correct API call (confirmed working on sandbox):
```json
POST /salary/transaction?generateTaxDeduction=true
{
  "date": "2026-03-20",
  "year": 2026,
  "month": 3,
  "isHistorical": false,
  "payslips": [{
    "employee": {"id": <employee_id>},
    "date": "2026-03-20",
    "year": 2026,
    "month": 3,
    "specifications": [
      {
        "salaryType": {"id": <2000_fastlonn_id>},
        "rate": 36000,
        "count": 1,
        "amount": 36000,
        "year": 2026,
        "month": 3,
        "employee": {"id": <employee_id>}
      },
      {
        "salaryType": {"id": <2002_bonus_id>},
        "rate": 15400,
        "count": 1,
        "amount": 15400,
        "year": 2026,
        "month": 3,
        "employee": {"id": <employee_id>}
      }
    ]
  }]
}
```

### Key takeaway:
The agent MUST use `POST /salary/transaction` — NOT `POST /ledger/voucher`. The voucher approach creates a journal entry on account 5000, but the competition checks for an actual salary transaction with payslips and specifications. These are fundamentally different objects in Tripletex.
