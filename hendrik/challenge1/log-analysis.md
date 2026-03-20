# Challenge 1 — Full Log Analysis & Scoring Assessment

**Date:** 2026-03-20
**Total logs:** 121 | **Scored tasks:** 19 | **Leaderboard:** rank #9, score 37.85, 18/30 tasks
**Leader:** "hackers" at 46.02 | **Gap:** 8.17 points

---

## Overall Results

| Metric | Value |
|--------|-------|
| Scored tasks | 19 |
| Perfect score (8/8 or 7/7) | 13 (68%) |
| Partial score (6/7 or 6/8) | 2 (11%) |
| Zero score (0/8) | 4 (21%) |
| Total points | 111 / 152 (73%) |
| Avg duration | 33.5s |
| Avg API calls | 6.5 |
| Token expiry incidents | 4 |

### Score Distribution

```
8/8  ████████████████  8 tasks  — invoice, timesheet, order+payment
7/7  ██████████        5 tasks  — project, customer, supplier, product
6/8  ████              2 tasks  — milestone invoice, supplier creation
0/8  ████████          4 tasks  — payroll(3), supplier invoice(1)
```

---

## Scored Task Log

| Timestamp | Task | Score | Checks | Duration | API calls | Errors |
|-----------|------|-------|--------|----------|-----------|--------|
| 18:03:20 | Project "Migrasjon Vestfjord" | 7/7 | 4/4 | 18.2s | 3 | 0 |
| 18:04:46 | Multi-VAT invoice (3 products, 25/15/0%) | 8/8 | all | 49.5s | 11 | 0 |
| 18:07:14 | Supplier invoice Sierra SL | **0/8** | 0/4 | 22.2s | 5 | 1 |
| 18:10:35 | Order→Invoice→Payment (Portuguese) | 8/8 | all | 46.7s | 10 | 0 |
| 18:11:55 | Order→Invoice→Payment | 8/8 | all | ~45s | 10 | 0 |
| 18:23:51 | Reverse payment (Spanish) | 8/8 | all | 27.8s | 4 | 0 |
| 18:25:15 | Fixed-price project + milestone | **6/8** | 3/4 | 44.1s | 9 | 0 |
| 18:27:15 | Supplier Silveroak Ltd | **6/7** | 4/5 | 7.0s | 1 | 0 |
| 18:48:28 | Create product (Spanish) | 7/7 | all | ~10s | 2 | 0 |
| 18:49:35 | Employee + employment (Nynorsk) | 8/8 | all | ~20s | 3 | 0 |
| 18:50:56 | Timesheet + project invoice | 8/8 | all | 54.4s | 12 | 0 |
| 18:52:51 | Project creation (French) | 7/7 | all | ~15s | 3 | 0 |
| 18:54:01 | Create+send invoice (Nynorsk) | 7/7 | all | ~30s | 8 | 0 |
| 18:55:28 | **Payroll Brita Stølsvik** | **0/8** | 0/4 | ~25s | 4 | 0 |
| 18:57:54 | Project "Intégration Montagne" | 7/7 | 4/4 | 17.3s | 3 | 0 |
| 18:59:13 | Order+invoice+payment Étoile SARL | 8/8 | 5/5 | 45.8s | 10 | 0 |
| 19:00:53 | Supplier invoice Montaña SL | **0/8** | 0/4 | 31.8s | 5 | 1 |
| 19:05:53 | Timesheet+invoice Leonor Almeida | 8/8 | 4/4 | 62.5s | 13 | 0 |
| 19:07:53 | **Payroll Raphaël Bernard** | **0/8** | 0/4 | 55.4s | 11 | 0 |
| 19:09:48 | **Payroll Sarah Moreau** | **0/8** | 0/4 | 64.6s | 11 | 0 |

---

## Failure Analysis

### FAILURE #1: Payroll — 0% pass rate (3 scored, all 0/8)

This is the **highest-impact issue**. Fixing payroll alone could add ~9.6 normalized points, enough to overtake #1.

#### Two approaches tried, both failed:

**Approach A — Voucher (18:55:28Z, Brita Stølsvik):**
```
POST /ledger/voucher with debit 5000 / credit 1920 for 51,400 NOK
```
Wrong endpoint entirely. Scorer expects `POST /salary/transaction`.

**Approach B — Salary transaction (19:07:53Z Raphaël, 19:09:48Z Sarah):**
```
POST /salary/transaction with payslips + specifications
  → 201 Created, transaction ID assigned, payslip generated
  → Still 0/8 on all checks
```

This is the puzzling one. The agent used the correct endpoint, created division + employment + salary transaction with proper specifications, got 201 back, yet all checks failed.

#### Detailed trace (19:09:48Z — Sarah Moreau):

| Step | Action | Result |
|------|--------|--------|
| 1 | GET employee, GET salary/type 2000, GET salary/type 2002 | Found all three |
| 2 | GET employment, GET employee details | No employment, dateOfBirth null |
| 3 | PUT employee (set dateOfBirth), GET division | Updated, no divisions |
| 4 | GET municipality | Got ID 1 (Agdenes) |
| 5 | POST division | Created "Hovedvirksomhet" (ID 108262889) |
| 6 | POST employment | Created (ID 2801601) |
| 7 | POST /salary/transaction | **Created** (ID 6956734, payslip 32627752) |
| 8 | Response text (success summary) | — |

**Score: 0/8, all 4 checks failed.**

#### UI Investigation (Tripletex Dashboard)

We opened the Tripletex UI and verified the payroll state directly:

**Lønnsoversikt:** All salary transactions show as **"Lønnsutbetaling (under bearbeiding)"** — draft status. None are finalized.

**Inside a payroll entry (51,400 NOK — Brita Stølsvik):**
- 2000 Fastlønn: 1 × 36,000 = 36,000 ✓
- 2002 Bonus: 1 × 15,400 = 15,400 ✓
- 6000 Skattetrekk: -20,560 (40% of 51,400) ✓ — **tax deduction IS generated**
- Til utbetaling: 30,840 ✓
- **"Fullfør lønnsutbetaling"** button visible at top right (not clicked by agent)

**Two warnings blocking finalization:**
1. ⚠️ **"Bankkontonummer mangler. Gå til arbeidsforholdet"** — employee has no bank account number
2. ℹ️ **"Månedsoversikten er ikke godkjent. Gå til månedsoversikten"** — monthly overview not approved

#### Hypotheses ruled out by UI investigation:

| Hypothesis | Status | Evidence |
|-----------|--------|----------|
| `generateTaxDeduction` not sent as query param | ❌ **RULED OUT** | Tax line (6000 Skattetrekk) is present in UI. Also confirmed in code: `tools.ts` passes `params` to `client.post()`, and `tripletex.ts` sets them as `url.searchParams` |
| Payroll wizard not configured | ❌ **RULED OUT** | "Kom i gang med Lønn" is checked off in the dashboard onboarding checklist |
| Salary type IDs wrong | ❌ **RULED OUT** | Correct types (Fastlønn, Bonus, Skattetrekk) visible in UI with correct amounts |
| Wrong endpoint used | ❌ **RULED OUT** (for Approach B) | Transactions appear in Lønnsoversikt, not as manual vouchers |

#### ROOT CAUSE CONFIRMED: Missing employee `bankAccountNumber`

**Evidence from logs:** In all 3 failed payroll tasks, the employee's `bankAccountNumber` is `""` (empty string):

```json
// 19:09:48Z — Sarah Moreau (Step 2, GET employee details)
"bankAccountNumber": ""    ← EMPTY

// 19:07:53Z — Raphaël Bernard (Step 3, GET employee details)
"bankAccountNumber": ""    ← EMPTY

// 18:55:28Z — Brita Stølsvik (used voucher approach, but same issue)
```

The agent updates `dateOfBirth` (required for employment) but **never sets `bankAccountNumber`**. Without it:
- The UI shows "Bankkontonummer mangler" warning
- The "Fullfør lønnsutbetaling" button cannot complete
- The transaction stays in draft ("under bearbeiding")
- The scorer checks for a completed payroll → all checks fail

#### No finalization endpoint in the API

We checked the full API reference (`api-compact.json`). Under `salary/transaction`, the only mutating endpoints are:
- `POST /salary/transaction` — Create
- `DELETE /salary/transaction/{id}` — Delete
- `POST /salary/transaction/{id}/attachment` — Upload attachment

There is **no** `PUT /salary/transaction/{id}/:complete` or `:payment` or `:post` endpoint. The "Fullfør lønnsutbetaling" button in the UI does not map to a documented API call. This means the transaction likely auto-completes when all prerequisites are met (valid employee with bank account, etc.), or the scorer simply checks the transaction data regardless of draft state.

**Either way, setting `bankAccountNumber` is the fix.** It removes the blocker and may allow the transaction to auto-finalize, or at minimum satisfies whatever field-level checks the scorer performs.

#### Recommended fix

**One-line change in system prompt** — add `bankAccountNumber` to the employee update that already happens for `dateOfBirth`:

```
// Current (system-prompt.ts, payroll section):
PUT /employee/{id} with {id, version, dateOfBirth: "1990-01-01"}

// Fixed:
PUT /employee/{id} with {id, version, dateOfBirth: "1990-01-01", bankAccountNumber: "12345678903"}
```

No extra API calls needed — the agent already does a `PUT /employee/{id}` to set `dateOfBirth`. Just include `bankAccountNumber` in the same request.

---

### FAILURE #2: Supplier Invoice — 0% pass rate (2 scored, both 0/8)

#### 18:07:14Z — Sierra SL (INV-2026-8702, 6,850 NOK incl. VAT)

- Used `GET /supplier` to find supplier → correct
- Created voucher with VAT postings → API returned 201
- All 4 checks failed

#### 19:00:53Z — Montaña SL (INV-2026-1443, 50,050 NOK incl. VAT)

- First attempt included `supplierVoucherType: "SUPPLIER_INVOICE"` → **422 validation error**
- Retry without field → 201 success
- All 4 checks failed

#### System prompt contradiction:
```
Line 117: "Do NOT include voucherType or guiRow — they cause errors"
Line 118: "DO include supplierVoucherType: 'SUPPLIER_INVOICE' for supplier invoices"
```

The agent follows line 118, gets a 422, removes the field, and succeeds at API level but fails scoring. The scorer likely requires `supplierVoucherType` to be set — but the API rejects it as an invalid enum value.

**Possible root cause:** The `supplierVoucherType` field may need a different value, or it may need to be set via a different mechanism (e.g., a separate PUT after creation, or a specific voucher type endpoint).

**Alternative hypothesis:** The supplier invoice voucher is created correctly, but the scorer checks for a specific accounting structure (e.g., debit on a different expense account, or specific row ordering) that doesn't match.

---

### FAILURE #3: Payment Reversal — Token Expiry

**19:00:53Z (Étoile SARL):** This log contains TWO tasks back-to-back:
1. Supplier invoice for Montaña SL → completed (scored 0/8)
2. Payment reversal for Étoile SARL → **19 consecutive "Invalid or expired token" errors**

The auth token expired between task 1 and task 2 in the same session. The agent retried 10 times over 11 steps before giving up.

This is a **session management issue**, not a logic issue. The reversal logic described by the agent was correct (negative `paidAmount` on `PUT /invoice/{id}/:payment`).

---

### Partial Failures

#### 18:25:15Z — Fixed-price project + milestone (6/8, Check 2 failed)
- Created project with `isFixedPrice=true, fixedprice=457650` ✓
- Created order + order line for 25% (114,412.50 NOK) ✓
- Description used: `"Pago parcial - 25% del precio fijo"` instead of `"Milestone payment - 25%"`
- **Fix:** Use exact description format from system prompt

#### 18:27:15Z — Supplier Silveroak Ltd (6/7, Check 5 failed)
- Created supplier with `showProducts: true` (not requested)
- **Fix:** Don't set `showProducts` unless asked. Keep creation minimal.

---

## Token Expiry Analysis

4 incidents across 121 logs. Pattern:

| Log | Trigger | Calls before expiry |
|-----|---------|---------------------|
| 13:30:47Z | 9 validation errors on employment tax codes | 18 |
| 14:10:05Z | Repeated 422s on employment creation | ~15 |
| 14:29:37Z | Same pattern | ~15 |
| 19:00:53Z | Previous task consumed session | 0 |

**Root cause:** Agent retries validation errors aggressively with no backoff. High error rate burns through the session token.

**Fix:** Add to system prompt: *"After 3 consecutive 4xx errors on the same endpoint, STOP. Do not retry. Report the error and move on."*

---

## Success Patterns

Tasks that consistently score 8/8:

1. **Parallel lookups in step 1** — customer, employee, products, payment types fetched simultaneously
2. **No redundant GETs** — IDs from POST responses reused directly
3. **Hardcoded VAT IDs** — 3 (25% output), 1 (25% input), 31 (15%), 6 (0% exempt)
4. **Bank account checked proactively** — `GET /ledger/account?number=1920` in parallel with setup
5. **Sequential order lines** — never parallel (avoids 409 conflicts)
6. **Clean error rate** — 0 errors = no score penalty

---

## Impact-Prioritized Recommendations

### P0: Fix payroll (potential +9.6 points → overtake #1)

**Root cause confirmed:** Employee `bankAccountNumber` is empty. Transaction stays in draft.

1. **Add `bankAccountNumber: "12345678903"` to employee PUT** — same call that sets `dateOfBirth`, zero extra API calls
2. Add explicit system prompt rule: *"NEVER use /ledger/voucher for payroll. ALWAYS use /salary/transaction."*
3. Add rule: *"When updating employee for payroll, ALWAYS set both `dateOfBirth` and `bankAccountNumber`"*

### P1: Fix supplier invoice (potential +3.2 points)

5. Resolve `supplierVoucherType` contradiction in system prompt
6. Test correct field value and delivery mechanism
7. Verify supplier lookup uses correct endpoint for voucher context

### P2: Fix partial failures (+1.5 points)

8. Milestone description: use `"Milestone payment - X%"` exactly
9. Supplier creation: remove `showProducts: true` default

### P3: Prevent token expiry (saves ~1 task per session)

10. Add retry limit (max 3 consecutive 4xx on same endpoint)
11. Distinguish retryable (429, 500) vs non-retryable (400, 422) errors

---

## Path to #1

Current: 37.85 points (rank #9)
Target: 46.02 points (rank #1 "hackers")
Gap: 8.17 points

| Fix | Estimated gain | Running total |
|-----|---------------|---------------|
| Payroll (3 tasks × ~3.2) | +9.6 | 47.45 |
| Supplier invoice (1 task × ~3.2) | +3.2 | 50.65 |
| Partial failures (2 tasks × ~0.75) | +1.5 | 52.15 |

**Fixing payroll alone closes the gap.** The remaining 12 unscored tasks (of 30 total) would add further points.
