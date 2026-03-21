# New Tier 3 Tasks — March 21 Analysis

**Date:** 2026-03-21
**Logs analyzed:** 8 submissions from today (11:18 – 12:15)

---

## Task 21 — Employee Onboarding from PDF (TOTAL FAIL)

**Prompt:** "Has recibido una carta de oferta (ver PDF adjunto) para un nuevo empleado. Completa la incorporación: crea el empleado, asigna el departamento correcto, configura los detalles de empleo con porcentaje y salario anual, y configura las horas de trabajo estándar."

**Score:** 0 — complete failure

**What happened:** Zero steps, zero API calls. The log only has the prompt line — the agent produced no output at all.

**Root cause:** The log has NO `[AGENT] saved attachment:` or `[AGENT] files:` lines, meaning the PDF was either not received or the agent crashed before processing. The supplier invoice PDF task (11:48, Task 20) DID process its PDF successfully the same day, so the code works for PDFs in general.

**Possible causes:**
1. The PDF content was too large or in a format the model couldn't process
2. The agent timed out trying to extract data from the offer letter
3. The offer letter format was not recognized by the model

**Action needed:** Check server-side logs for errors during this task. This is an infrastructure/model issue, not an API problem. No UI investigation will help.

---

## Task 20 — Supplier Invoice from PDF (Score 0.60, potential 5.4)

**Prompt:** "Voce recebeu uma fatura de fornecedor (ver PDF anexo). Registe a fatura no Tripletex. Crie o fornecedor se nao existir."

**Score:** 0.60 (Hendrik: "could be 5.4")

**What the agent did:**
- Successfully read PDF and extracted: supplier name (Rio Azul Lda), org nr (849825054), invoice number (INV-2026-8795), date (2026-03-06), amounts (84125 incl VAT), expense account (6300), address
- Created supplier via `POST /supplier` (with 1 retry due to bankAccounts field error)
- Created voucher via `POST /ledger/voucher`
- 6 API calls, 1 error

**Why it scored low:**
1. Used `POST /ledger/voucher` instead of `POST /supplierInvoice` — creates wrong entity type
2. Our supplier invoice fix (`amountGrossCurrency` on postings via `POST /supplierInvoice`) would fix this
3. Used `POST /supplier` without `accountManager` (Check 5 issue from supplier registration)

**Fix:** Apply the existing `supplier-invoice-fix.md` — use `POST /supplierInvoice` with `amountGrossCurrency`. The PDF reading and data extraction works correctly.

---

## Task 26 — Monthly Closing (Score 4/6)

See `monthly-closing-fix.md` for full analysis.

---

## Task 27 — Foreign Currency Payment (Score 6 — seems max)

**Prompt:** Invoice of 8676 EUR at rate 11.62 NOK/EUR. Customer paid at rate 10.89 NOK/EUR. Register payment and post exchange difference (disagio).

**Score:** 6 (Hendrik: "seems max? ok?")
**Status:** Working correctly, no fix needed.

---

## Task 10 — Order→Invoice→Payment (Score 2.4, max 2.67)

**Prompt:** Standard order with 2 products, convert to invoice, register payment.

**Score:** 2.4 vs max 2.67
**Issue:** Efficiency — too many API calls. Already a known task type.
**Fix:** Reduce unnecessary lookups. Pre-fetch payment type in parallel with step 1.

---

## Task 15 — Fixed-price Project + 75% Milestone (Score 2.8, max 3.0)

**Prompt:** Set fixed price 261700 NOK, invoice 75%.

**Score:** 2.8 vs max 3.0
**Issue:** Small efficiency gap.
**Fix:** Already known — reduce API calls.

---

## Task (12:10) — Cost Analysis + Create Projects (Score unknown)

**Prompt:** "Les coûts totaux ont augmenté de manière significative de janvier à février 2026. Analysez le grand livre et identifiez les trois comptes de charges avec la plus forte augmentation. Créez un projet interne pour chacun."

**What the agent did:** 15 API calls, 3 errors. Analyzed ledger postings, tried to find expense increases, created internal projects.
**Hendrik note:** "BUT WE COULD DO 2"
**Status:** New Tier 3 task — needs further analysis if logs show specific check failures.

---

## Task 12 — Payroll (Score 0)

See `payroll-finalization-fix.md` — hidden `/tsk/salaryv2/transaction/:run` endpoint found.

---

## Priority Summary

| Task | Current | Potential | Fix status |
|---|---|---|---|
| Task 12 (Payroll) | 0 | +6.0 | Fix found — `:run` endpoint |
| Task 20 (Supplier invoice PDF) | 0.60 | 5.4 | Apply existing `supplier-invoice-fix.md` |
| Task 21 (Employee onboarding PDF) | 0 | ? | Infrastructure issue — check server logs |
| Task 26 (Monthly closing) | 4 | 6 | Prompt engineering — see `monthly-closing-fix.md` |
| Task 10 (Order→Invoice→Payment) | 2.4 | 2.67 | Efficiency — reduce API calls |
| Task 15 (Fixed-price + milestone) | 2.8 | 3.0 | Efficiency — reduce API calls |
| Task 27 (Foreign currency) | 6 | 6 | Already at max |
