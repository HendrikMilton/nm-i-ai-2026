# Session Handoff — Challenge 1 Ultra-Optimization

## Mission
NM i AI competition. Every 0.01 point matters. Score = correctness × tier × efficiency_bonus.

## Scoring (from official docs)
- **Correctness**: field-by-field checks, normalized 0-1. Each check has a point value.
- **Tier multiplier**: Tier 1 (×1), Tier 2 (×2), Tier 3 (×3). Non-perfect = correctness × tier, no bonus.
- **Efficiency bonus**: ONLY applies to PERFECT (1.0) correctness. Can up to DOUBLE the tier score.
  - Based on WRITE calls only (POST, PUT, DELETE, PATCH). **GET requests are FREE — read as much as you need.**
  - Also penalized by 4xx errors on write calls. Zero errors = best bonus.
  - Benchmarks recalculated every 12h against best-known solutions.
- **Max per task**: 6.0 (perfect Tier 3 × 2)
- **Leaderboard**: sum of best scores across all 30 task types. Bad runs never lower your score.

### CRITICAL INSIGHT
GETs don't count for efficiency! Only minimize POST/PUT/DELETE calls and avoid 4xx errors on writes.
Focus: (1) get all checks passing first, (2) then minimize write calls.

## Current State
- Rank ~62, score ~38.28, 18/30 tasks touched
- Server running: `bun --watch run src/index.ts` on port 4001
- SSH tunnel: `ssh -N -R 0.0.0.0:4001:localhost:4001 root@157.90.171.156`
- Endpoint: https://tripletex.hycapital.io/solve
- Sandbox: TRIPLETEX_SANDBOX_URL + TOKEN in .env (use `-u "0:$TOKEN"` for curl, or TripletexClient)

## Task Type Map (discovered so far)
| Task | Type | Our Score | Best | Status |
|------|------|-----------|------|--------|
| 1 | Simple employee creation | 1.5 | 2.0 | Needs optimization — check write calls |
| 10 | Order + invoice + payment | 2.4 | 2.67 | All checks pass, write call efficiency gap |
| 12 | Payroll (salary transaction) | 0.0 | ? | ALL CHECKS FAIL — unknown root cause |
| 15 | Fixed-price project + milestone invoice | 2.8 | 3.0 | Skip GET /employee (project includes projectManager) |
| 19 | Employee from contract PDF | 2.45 | ? | occupationCode fix deployed, address missing? |
| 20 | Supplier invoice from PDF | 0.6 | ? | bankAccounts field broken, need email+invoiceEmail on supplier |
| 21 | Employee onboarding from offer letter PDF | 2.36 | ? | Need POST /employee/standardTime |
| 23 | Bank reconciliation (CSV match) | 0.0 | ? | Must use CSV dates, handle supplier payments via voucher |
| 26 | Monthly closing (journal vouchers) | 4.0 | 6.0 | Was 18 calls, workflow fixed. Don't re-fetch, don't guess accounts |
| 28 | Analyze ledger + create projects | 1.5 | 2.0 | Must link activities to projects via POST /project/projectActivity |
| 29 | Complete project lifecycle | 1.64 | ? | Timesheet sequential, supplier voucher needs project:{id} |

## Key Fixes Already in system-prompt.ts
- "First step — identify the workflow" instruction
- Task-specific workflows with exact API call sequences
- occupationCode: search by nameNO, never use STYRK code as id
- bankAccounts on supplier: BROKEN, never include
- Supplier email: always set dummy email
- Timesheet entries: sequential (parallel causes 409)
- Don't re-fetch created resources
- Don't guess at additional accounts

## Key Files
- `src/system-prompt.ts` — THE file to optimize. Contains workflows + API reference
- `src/agent.ts` — logs API calls to file, saves PDF attachments
- `src/tripletex.ts` — client with full req/resp logging
- `src/validators.ts` — auto-generated, catches bad POSTs before they hit API
- `scripts/autoloop.ts` — submit one task, wait for score
- `scripts/check-score.sh` — leaderboard position
- `scripts/check-latest-scoring.sh` — latest submission details
- `validations/taskXX/replicate.ts` — sandbox test scripts

## Optimization Strategy
1. User manually submits — never start any app, never tail logs, wait for user to tell you when to check
2. Read latest log file — check EVERY API call. Task number, score, and best competitor score are appended at the end of the log file by the user
3. If checks fail: create replicate.ts in validations/, test on sandbox
4. If efficiency low: reduce WRITE calls in workflow, update system-prompt.ts
5. Commit after every change

## Critical Efficiency Rules
- **GETs are FREE** — only write calls (POST/PUT/DELETE) count for efficiency
- Every unnecessary write call = lower efficiency bonus
- Every 4xx error on a write call = score penalty
- Priority: (1) pass ALL checks, (2) minimize write calls, (3) zero write errors
- Unnecessary department/division creation = wasted writes if they already exist

## Unsolved Problems
- Task 12 (payroll): 4/4 checks fail despite correct-looking data. No API finalization endpoint exists. Need more investigation.
- Task 23 (bank reconciliation): Agent used wrong dates and missed supplier payments. Workflow added but untested.
- Tasks 11, 22, 24, 25, 27, 30: Never seen these task types yet.
