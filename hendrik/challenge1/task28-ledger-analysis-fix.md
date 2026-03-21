# Task 28 — Ledger Analysis + Create Projects/Activities — Fix Report

**Date:** 2026-03-21
**Current score:** 1.50 (2/5 checks passed, raw 5/10)
**Potential score:** ~4.50 (5/5 checks + fewer errors + fewer API calls)
**Impact:** +3.00 points
**Tier:** 3 (x3 multiplier)

---

## Task Description

"Analyze the ledger from January to February 2026. Identify the 3 expense accounts with the largest increase. Create an internal project for each, and an activity for each project."

## Root Cause: Missing POST /project/projectActivity

The agent creates 3 projects and 3 activities correctly, but **never links them together**. The system prompt has this as step 6 (line 130), but the agent stops after creating activities.

### Scoring Breakdown

| Check | Result | What it checks |
|-------|--------|---------------|
| Check 1 | PASSED | Analysis correct — top 3 accounts identified |
| Check 2 | FAILED | Project 1 has activity linked |
| Check 3 | FAILED | Project 2 has activity linked |
| Check 4 | FAILED | Project 3 has activity linked |
| Check 5 | PASSED | Projects/activities exist with correct fields |

### UI Verification

Tested on sandbox by creating two projects — one with `POST /project/projectActivity`, one without:

- **Linked project:** Budsjett tab → Aktiviteter section shows the activity with startDate
- **Unlinked project:** Budsjett tab → Aktiviteter section is empty

The scorer checks `projectActivities` on each project via the API. Without linking, this field is `[]`.

### API Verification

Full correct flow tested on sandbox:

```
POST /project → 201 (×3, name=account_name, isInternal=true)
POST /activity → 201 (×3, name=account_name, activityType=PROJECT_GENERAL_ACTIVITY, isChargeable=false)
POST /project/projectActivity → 201 (×3, one at a time, with startDate=today)
```

All fields verified field-by-field — names, types, booleans, dates all match between agent's output and correct flow. The ONLY difference is the missing linking step.

---

## Secondary Issue: 3 Wasted Error Calls

The agent tries endpoints the prompt explicitly warns against (line 125):

| Call | Status | Prompt says |
|------|--------|-------------|
| `GET /ledger/openPostings` | 404 | "Do NOT use /ledger/openPostings (404)" |
| `GET /resultbudget` (nested fields) | 400 | "Do NOT use /resultbudget with nested fields (400)" |
| `GET /resultbudget` (nested fields) | 400 | Same |

Additional wasted calls:
- `GET /ledger/account?numberFrom=4000...` — returned wrong range (1000-1640), not needed at all
- `GET /resultbudget?fields=*` ×2 — returned 0 results
- First `POST /activity` attempt ×3 — used invalid fields (`isProjectActivity`, `isGeneral`)

**Total: 15 API calls, 3 errors. Ideal: 12 calls, 0 errors.**

---

## Analysis Verification

The agent's analysis was correct regardless of amount vs amountGross:

| Account | Name | January | February | Increase |
|---------|------|---------|----------|----------|
| 7100 | Bilgodtgjoerelse oppgavepliktig | 5,000 | 12,000 | **+7,000** |
| 6500 | Motordrevet verktoey | 2,400 | 8,000 | **+5,600** |
| 5000 | Loenn til ansatte | 150,000 | 155,000 | **+5,000** |
| 7300 | Salgskostnad | 6,400 | 9,600 | +3,200 |
| 6300 | Leie lokale | 16,000 | 16,500 | +500 |
| 7400 | Kontingent | 4,800 | 5,200 | +400 |

Top 3 are the same whether using `amount` (net) or `amountGross` (incl VAT).

---

## System Prompt Changes Needed

The workflow (lines 122-130) has the right steps. The problem is the agent doesn't follow them. Changes:

### 1. Move warnings BEFORE step 1 (make them impossible to miss)

```
## Workflow: Analyze ledger + create projects and activities (Task 28)
ONLY use GET /ledger/posting for data. Do NOT call /ledger/openPostings (404), /resultbudget (400), or /ledger/account.
```

### 2. Make linking step unmissable

Current (line 130):
```
6. Link each activity to its project ONE AT A TIME: POST /project/projectActivity with {project:{id}, activity:{id}, startDate:today}
```

Change to:
```
6. CRITICAL — DO NOT SKIP: Link each activity to its project ONE AT A TIME:
   POST /project/projectActivity with {project:{id}, activity:{id}, startDate:today}
   Without this step, the task is INCOMPLETE and will score 0 on 3 checks.
```

### 3. Specify exact activity fields

```
5. POST /activity x3 in parallel: {name:<account_name>, activityType:"PROJECT_GENERAL_ACTIVITY", isChargeable:false}
   Use ONLY these 3 fields. Do NOT include isProjectActivity, isGeneral, or other fields.
```

---

## Ideal API Call Sequence (12 calls, 0 errors)

```
1. GET /ledger/posting (Jan, accounts 4000-7999)     — parallel
   GET /ledger/posting (Feb, accounts 4000-7999)     — parallel
2. [Agent analyzes: aggregate by account, find top 3]
3. GET /employee?fields=id&count=1
4. POST /project (account 1 name, isInternal:true)    — parallel
   POST /project (account 2 name, isInternal:true)    — parallel
   POST /project (account 3 name, isInternal:true)    — parallel
5. POST /activity (account 1 name)                    — parallel
   POST /activity (account 2 name)                    — parallel
   POST /activity (account 3 name)                    — parallel
6. POST /project/projectActivity (project1, activity1) — sequential
   POST /project/projectActivity (project2, activity2) — sequential
   POST /project/projectActivity (project3, activity3) — sequential
```
