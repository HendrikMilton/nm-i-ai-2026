# Challenge 1 — Full Log Analysis & Scoring Assessment

**Date:** 2026-03-20
**Total logs:** 125 | **Scored tasks:** 23 | **Leaderboard:** rank #9, score 37.85, 18/30 tasks
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
| 19:23:11 | **Multi-VAT invoice Oakwood Ltd** | **0/8** | 0/6 | 80.4s | 11 | 0 |
| 19:27:57 | **Supplier invoice Brattli AS** | **0/8** | 0/4 | 43.4s | 5 | 1 |

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

#### UI VERIFICATION — FIX CONFIRMED

We manually tested the fix in the Tripletex UI:

1. **Opened employee "Arbeidsforhold" tab** — found `Bankkontonummer` field empty under "Innstillinger for lønnsutbetalinger"
2. **Entered `12345678903`** in the bank account field and clicked "Lagre"
3. **Returned to payroll entry** — bank account warning **gone**. Now shows "Til kontonr. 1234.56.78903"
4. **Clicked "Fullfør lønnsutbetaling"** — **SUCCESS**

**Result:**
- Dialog: **"Lønnskjøringen er fullført"** (Payroll run completed)
- Title changed from "Lønnsutbetaling (under bearbeiding)" → **"Lønnsbilag 1-2026"** (posted voucher)
- Green banner confirms completion
- Buttons changed to post-completion actions: "Endre betaling", "Reverser lønnsutbetaling"

**This proves that `bankAccountNumber` was the ONLY blocker.** The monthly overview warning ("Månedsoversikten er ikke godkjent") did NOT prevent finalization. Only the missing bank account did.

#### Recommended fix

**One-line change in system prompt** — add `bankAccountNumber` to the employee update that already happens for `dateOfBirth`:

```
// Current (system-prompt.ts, payroll section, line ~141):
PUT /employee/{id} with {id, version, dateOfBirth: "1990-01-01"}

// Fixed:
PUT /employee/{id} with {id, version, dateOfBirth: "1990-01-01", bankAccountNumber: "12345678903"}
```

No extra API calls needed — the agent already does a `PUT /employee/{id}` to set `dateOfBirth`. Just include `bankAccountNumber` in the same request.

Also update the system prompt text at line ~141:
```diff
- Employee MUST have dateOfBirth set for employment creation. If null, PUT /employee/{id} with dateOfBirth: "1990-01-01" first
+ Employee MUST have dateOfBirth and bankAccountNumber set. If missing, PUT /employee/{id} with dateOfBirth: "1990-01-01", bankAccountNumber: "12345678903"
```

---

### FAILURE #2: Supplier Invoice — 0% pass rate (3 scored, all 0/8)

**Potential impact: +9.6 points (3 tasks × ~3.2)**

All 3 supplier invoice tasks follow the identical pattern — API succeeds, all checks fail:

| Log | Supplier | Invoice | Amount | API errors | Score |
|-----|----------|---------|--------|------------|-------|
| 18:07:14Z | Sierra SL | INV-2026-8702 | 6,850 NOK | 0 | 0/8 |
| 19:00:53Z | Montaña SL | INV-2026-1443 | 50,050 NOK | 1 (422 on supplierVoucherType) | 0/8 |
| 19:27:57Z | Brattli AS | INV-2026-2388 | 25,650 NOK | 1 (422 on supplierVoucherType) | 0/8 |

#### What the agent does (all 3 identical):
1. `GET /supplier?organizationNumber=X` — finds supplier ✓
2. `GET /ledger/account?number=XXXX` — gets expense account ✓
3. `GET /ledger/account?number=2400` — gets leverandørgjeld ✓
4. `POST /ledger/voucher` with debit/credit postings — **201 Created** ✓
5. Tripletex auto-generates MVA line (25% inngående) ✓

#### Critical observation — `vendorInvoiceNumber` silently dropped

In all 3 logs, the agent sends `vendorInvoiceNumber: "INV-2026-XXXX"` in the POST body, but the **response shows `vendorInvoiceNumber: null`**:

```json
// Request body includes:
"vendorInvoiceNumber": "INV-2026-8702"

// Response shows:
"vendorInvoiceNumber": null    ← SILENTLY DROPPED
```

The API accepts the field but doesn't persist it. This means the scorer can't find the vendor invoice number on the voucher.

#### `supplierVoucherType` rejected by API

```json
// Agent sends:
"supplierVoucherType": "SUPPLIER_INVOICE"

// API responds:
422: "Verdien er ikke av korrekt type for dette feltet"
(The value is not of the correct type for this field)
```

The field expects a **different type** (likely an integer/enum ID, not a string). The response also shows `supplierVoucherType: null` on successfully created vouchers.

#### System prompt contradiction:
```
Line 117: "Do NOT include voucherType or guiRow — they cause errors"
Line 118: "DO include supplierVoucherType: 'SUPPLIER_INVOICE' for supplier invoices"
```

#### UI VERIFICATION — ROOT CAUSE CONFIRMED

We created a supplier invoice through the Tripletex UI ("Bilag → Nytt bilag → Enkel føring") and compared it with an API-created voucher. The difference is fundamental:

**UI-created supplier invoice (voucher 17-2026):**
- Title: **"Leverandørfaktura (enkel føring)"** — typed as supplier invoice
- URL: `/execute/incomingInvoiceMenu?voucherId=608842577` — lives in the **incoming invoice module**
- Shows "Fakturadetaljer" with Leverandør, Fakturanummer (TEST-001), Totalt beløp
- Has proper supplier invoice metadata (due date, payment tracking, invoice number)
- Payment section shows supplier debt tracking with "Utestående" balance

**API-created voucher via POST /ledger/voucher (voucher 16-2026):**
- Title: **"Avansert bilag"** — classified as a generic advanced voucher
- URL: `/execute/voucherMenu?voucherId=608827879` — lives in the **generic voucher module**
- Shows "Bilagsdetaljer" with just Bilagsnummer, Beskrivelse, Bilagsdato
- No supplier invoice metadata (no invoice number field, no due date, no supplier-specific fields)
- Raw debit/credit postings only

**These are completely different entity types in Tripletex.** The scorer checks for a proper "Leverandørfaktura" entity and finds only a generic "Avansert bilag".

#### Root cause confirmed

`POST /ledger/voucher` creates a **generic journal entry**, not a supplier invoice. The resulting voucher:
- Lives in the wrong module (voucherMenu vs incomingInvoiceMenu)
- Has no supplier invoice metadata
- `vendorInvoiceNumber: null` — silently dropped
- `supplierVoucherType: null` — API rejects the string value "SUPPLIER_INVOICE"

The UI's "Leverandørfaktura (enkel føring)" form uses a **different internal API flow** that creates a proper incoming invoice entity with all metadata.

#### Investigation needed

1. **Check if there's a dedicated incoming invoice API endpoint** — the UI URL suggests `/incomingInvoice` or similar. Search the API reference for endpoints containing "incoming", "purchase", or "supplierInvoice"
2. **Test `supplierVoucherType` with integer values** — the 422 error says "wrong type", so try `0`, `1`, `2` instead of the string `"SUPPLIER_INVOICE"`
3. **Check if the "enkel føring" UI form makes different API calls** — use browser dev tools (Network tab) while creating a supplier invoice to capture the actual API request
4. **Alternative approach:** Create the voucher, then use a PUT or separate endpoint to "convert" it to a supplier invoice type

---

### FAILURE #3: Payment Reversal — Token Expiry

**19:00:53Z (Étoile SARL):** This log contains TWO tasks back-to-back:
1. Supplier invoice for Montaña SL → completed (scored 0/8)
2. Payment reversal for Étoile SARL → **19 consecutive "Invalid or expired token" errors**

The auth token expired between task 1 and task 2 in the same session. The agent retried 10 times over 11 steps before giving up.

This is a **session management issue**, not a logic issue. The reversal logic described by the agent was correct (negative `paidAmount` on `PUT /invoice/{id}/:payment`).

---

### FAILURE #4: Multi-VAT Invoice — 0/8 (19:23:11Z, Oakwood Ltd)

**6/6 checks failed** despite flawless API execution (0 errors, 11 API calls).

Task: Create invoice with 3 products at different VAT rates:
- Analysis Report (7049): 12,250 NOK @ 25% VAT → vatType id=3 ✓
- Cloud Storage (5725): 3,750 NOK @ 15% VAT → vatType id=31 ✓
- Consulting Hours (9683): 10,750 NOK @ 0% VAT → vatType id=6 ✓

Everything looks correct. An almost identical task (18:04:46Z) scored 8/8 earlier the same day.

**Why this likely fails:** This task ran at 19:23Z, after the leaderboard shows `tasks=18/30`. The scoring sandbox may have been a **different company instance** than earlier tasks. Each scored task likely gets its own fresh sandbox — if the products/customer don't exist in that sandbox, the scorer can't validate them.

Alternatively, the scorer may have checked for `sendToCustomer=true` vs `false`, or the task context may have changed between the two similar tasks.

**Lower priority** — this may be an environment issue rather than a code fix.

---

### Partial Failures

#### 18:25:15Z — Fixed-price project + milestone (6/8, Check 2 failed)
- Created project with `isFixedPrice=true, fixedprice=457650` ✓
- Created order + order line for 25% (114,412.50 NOK) ✓
- Description used: `"Pago parcial - 25% del precio fijo"` instead of `"Milestone payment - 25%"`
- Unnecessary `GET /department` call (system prompt says not needed for projects)
- **Fix:** Use exact description format from system prompt: `"Milestone payment - 25%"`

#### 18:27:15Z — Supplier Silveroak Ltd (6/7, Check 5 failed)
- Used `POST /supplier` directly instead of `POST /customer` with `isSupplier: true` (system prompt line 56 says to use `/customer`)
- Added `showProducts: true` (not requested)
- **Fix 1:** Use `POST /customer` with `isSupplier: true` instead of `POST /supplier`
- **Fix 2:** Don't set `showProducts` unless asked

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

### P1: Fix supplier invoice (potential +9.6 points — 3 tasks)

**Root cause:** `vendorInvoiceNumber` silently dropped, `supplierVoucherType` rejected as wrong type.

4. **Test `supplierVoucherType` with integer values** (0, 1, 2) instead of string `"SUPPLIER_INVOICE"`
5. **Test setting `vendorInvoiceNumber` via PUT** after initial POST creation
6. Remove `supplierVoucherType` line from system prompt until correct value is found
7. Fix system prompt contradiction (lines 117 vs 118)

### P2: Fix partial failures (+1.5 points)

8. Milestone description: use `"Milestone payment - X%"` exactly (not translated)
9. Supplier creation: use `POST /customer` with `isSupplier: true` (not `POST /supplier`)
10. Don't set `showProducts: true` unless asked

### P3: Prevent token expiry (saves ~1 task per session)

11. Add retry limit: *"After 3 consecutive 4xx errors on the same endpoint, STOP and report."*
12. Distinguish retryable (429, 500) vs non-retryable (400, 422) errors

---

## All Zero-Score Logs

| Log | Task type | Score | Root cause | Fix status |
|-----|-----------|-------|------------|------------|
| 18:07:14Z | Supplier invoice (Sierra SL) | 0/8 | vendorInvoiceNumber dropped | **NEEDS FIX** |
| 18:55:28Z | Payroll voucher (Brita) | 0/8 | Wrong endpoint + no bankAccountNumber | **FIX READY** |
| 19:00:53Z | Supplier invoice (Montaña SL) | 0/8 | vendorInvoiceNumber dropped | **NEEDS FIX** |
| 19:07:53Z | Payroll (Raphaël) | 0/8 | Missing bankAccountNumber | **FIX READY** |
| 19:09:48Z | Payroll (Sarah) | 0/8 | Missing bankAccountNumber | **FIX READY** |
| 19:23:11Z | Multi-VAT invoice (Oakwood) | 0/8 | Likely environment issue | Low priority |
| 19:27:57Z | Supplier invoice (Brattli AS) | 0/8 | vendorInvoiceNumber dropped | **NEEDS FIX** |

---

## Path to #1

Current: 37.85 points (rank #9)
Target: 46.02 points (rank #1 "hackers")
Gap: 8.17 points

| Fix | Tasks | Estimated gain | Running total |
|-----|-------|---------------|---------------|
| Payroll (bankAccountNumber) | 3 | +9.6 | 47.45 |
| Supplier invoice (vendorInvoiceNumber) | 3 | +9.6 | 57.05 |
| Partial failures (description + supplier) | 2 | +1.5 | 58.55 |

**Fixing payroll alone closes the gap.** Fixing supplier invoices too would create a commanding lead.
