# Supplier Registration Check 5 — Root Cause Found

**Date:** 2026-03-21
**Impact:** 0.3 pts per task (3 scored runs at 6/7)
**Status:** ROOT CAUSE FOUND — verified on sandbox

---

## Problem

All supplier registration tasks score 6/7. Check 5 always fails.

## Root Cause

The agent creates suppliers without setting `accountManager`. The UI automatically sets it to the logged-in user.

### Evidence — field-by-field comparison

Created the same supplier via UI and API, then compared full responses:

| Field | UI-created | API-created |
|---|---|---|
| **accountManager** | `{"id": 18450014}` ← set to logged-in user | **`null`** ← missing |
| All other fields | identical | identical |

This is the **only difference**.

## Fix

Add `accountManager` to the supplier creation body. The agent can get the admin employee ID via `GET /token/session/>whoAmI` (returns `employeeId`), or reuse any employee ID already fetched.

### Option A: Extra API call
```
GET /token/session/>whoAmI → get employeeId
POST /supplier with accountManager: {id: employeeId}
```

### Option B: No extra call
If the agent already has an employee ID from a prior call, reuse it. Or hardcode a heuristic in the system prompt:
```
POST /supplier with accountManager: {id: <any_valid_employee_id>}
```

### What was ruled out

| Hypothesis | Result |
|---|---|
| `isCustomer` flag | Both `/supplier` and `/customer` approaches score 6/7 identically |
| `invoiceEmail` missing | Already set correctly |
| `phoneNumber` missing | Not in prompt, empty in both UI and API |
| `showProducts` field | Fails with and without |
| Endpoint choice (`/supplier` vs `/customer`) | Both score same |
| Address fields | Not in prompt |

## Also discovered

- Entity created via `POST /supplier` is **NOT visible** via `GET /customer` — only via `GET /supplier`
- Entity created via `POST /customer` with `isSupplier: true` is visible via **both** endpoints
- `isCustomer: false` cannot be forced via `/customer` endpoint — Tripletex overrides to `true`
- The test validation file checks via `GET /customer`, but competition scorer likely checks via `GET /supplier` as well (since `/supplier`-created entities score 6/7, not 0/7)
