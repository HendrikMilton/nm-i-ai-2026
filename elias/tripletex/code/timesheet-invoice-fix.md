# Timesheet → Project Invoice — Analysis & Findings

**Date:** 2026-03-21
**Impact:** ~2 pts per task (currently 4/8 on some runs, 8/8 on others)
**Status:** ROOT CAUSE PARTIALLY UNDERSTOOD — no clean REST API solution found

---

## Problem

Timesheet + project invoice tasks sometimes score 4/8 (Check 3+4 fail) and sometimes 8/8. Same approach used in all runs.

### Scored runs

| Run | Employee | Score | Approach |
|---|---|---|---|
| 18:50 Thea Ødegård | 19h Design | **8/8** | Manual order+orderline |
| 19:05 Leonor Almeida | 30h Utvikling | **8/8** | Manual order+orderline |
| 19:35 Miguel Torres | 15h Design | **4/8** (Check 3+4 fail) | Manual order+orderline |

All three used identical approach — the failure is inconsistent.

## What the Agent Does (Current)

1. Register timesheet entry: `POST /timesheet/entry`
2. Create order linked to project: `POST /order` with `project: {id}`
3. Add manual order line: `POST /order/orderline` with hours × rate
4. Create invoice: `POST /invoice`

The timesheet hours and the invoice are **not linked** — the invoice is based on a manually created order line, not on the actual registered hours.

## What the UI Shows (Correct Flow)

The Tripletex UI has a dedicated project invoicing flow:

### Project Dashboard
- Shows **TIMER Til godkjenning** (hours awaiting approval) and **TIMER Til fakturering** (hours ready to invoice)
- Has a **"Fakturering"** button with options:
  - "Godkjenn og fakturer" — Approve and invoice
  - "Forhåndsvisning av faktura" — Invoice preview
  - "Gå til godkjenning/fakturering" — Go to approval page

### Approval Page (Godkjenning og fakturering av prosjekter)
- Shows projects with unapproved hours
- Columns: Fakturering (Godkjent), A konto, Honorar (Inkluder, Fastpris-beløp, Honorar å fakturere, Påslag), Ordrelinjer
- Workflow: Select project → Check "Inkluder" → Click "Godkjenn" → Click "Fakturering"

### The Flow
1. Hours registered → status "Til godkjenning"
2. Hours approved → status "Til fakturering"
3. Invoice generated from approved hours through project invoicing

## API Investigation Results

### Timesheet Entry
- `chargeable: true` can be set on creation — marks hours as billable
- `chargeableHours` auto-populated from `hours` when `chargeable: true`
- `hourlyRate` is **read-only** — derived from project hourly rate settings, NOT settable on the entry
- `invoice: null` — no invoice linked until invoiced through project flow

### Project Hourly Rates
- `PUT /project/hourlyRates/{id}` with `fixedRate: 1500` works
- `hourlyRateModel: "TYPE_FIXED_HOURLY_RATE"` sets a fixed rate for all activities

### Approval Endpoints Found
```
PUT /timesheet/month/:approve    — approve month (params: employeeIds, monthYear)
PUT /timesheet/week/:approve     — approve week
PUT /timesheet/month/:unapprove  — unapprove month
PUT /timesheet/week/:unapprove   — unapprove week
```

### What's Missing
- **No `POST /invoice/projectInvoice` endpoint** — doesn't exist in the REST API
- **No `PUT /timesheet/entry/:approve` endpoint** — approval is at month/week level only
- The UI's "Godkjenn og fakturer" uses an internal Java/JSON-RPC flow (`/execute/updateInvoices`), not the REST API
- `PUT /timesheet/month/:approve` returned validation error: "En måned kan ikke være både åpen og godkjent"

## Possible Improvements (Uncertain)

Since there's no direct REST API for project invoicing, potential approaches:

1. **Set `chargeable: true` on timesheet entry** — the agent currently doesn't set this. It might help Check 3.

2. **Set project hourly rate** via `PUT /project/hourlyRates/{id}` with the task's hourly rate — currently `hourlyRate: 0` on entries because project rate isn't configured.

3. **Keep the manual order+orderline approach** but ensure the order is linked to the project with `invoiceOnAccountVatHigh: true`.

4. **After creating the invoice, check if timesheet entries can be linked** — the `invoice` field on timesheet entries might be updatable.

## Risk Assessment

- **2/3 scored runs passed** with the current manual approach
- The one failure might be sandbox-specific, not systematic
- No clean REST API path exists for the full project invoicing flow
- Changes here could break the 67% that already passes

## Recommendation

Low-confidence fix. The safest improvements to try:
1. Set `chargeable: true` when creating timesheet entries (currently not set)
2. Set project hourly rate before creating the invoice
3. Keep the manual order+orderline approach as fallback

These are additive changes that shouldn't break existing passing runs.
