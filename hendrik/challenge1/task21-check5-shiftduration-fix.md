# Task 21 — Check 5 Root Cause: shiftDurationHours must NOT be set

**Date:** 2026-03-22
**Impact:** Task 21 scores 12/14 (2.57) instead of 14/14 (up to 6.0). Check 5 fails 100%.
**Status:** ROOT CAUSE FOUND via UI vs API comparison in sandbox

---

## Root Cause

The agent sets `shiftDurationHours: 7.5` in the `POST /employee/employment` body. The evaluator expects this field to be **not set** (defaults to 0.0).

## Evidence

### UI vs API comparison in sandbox

Created an employee via the Tripletex UI ("Ny ansatt" → fill in Arbeidsforhold fields) and compared with our API-created employee:

**UI-created employment detail:**
```
employmentType: ORDINARY
employmentForm: PERMANENT
remunerationType: MONTHLY_WAGE
workingHoursScheme: NOT_SHIFT
percentageOfFullTimeEquivalent: 100.0
annualSalary: 600000.0
shiftDurationHours: 0.0          ← NOT SET (default)
hourlyWage: 308.0
```

**API-created employment detail (current agent):**
```
employmentType: ORDINARY
employmentForm: PERMANENT
remunerationType: MONTHLY_WAGE
workingHoursScheme: NOT_SHIFT
percentageOfFullTimeEquivalent: 100.0
annualSalary: 600000.0
shiftDurationHours: 7.5          ← HARDCODED (wrong!)
hourlyWage: 308.0
```

The **only** difference is `shiftDurationHours`. Every other field is identical.

### Verification

- Created employee WITHOUT `shiftDurationHours` in API → `shiftDurationHours: 0.0` (matches UI)
- All other fields (annualSalary, monthlySalary, hourlyWage, percentage) calculated correctly
- hourlyWage uses company default normaltid (7.5) regardless of shiftDurationHours value

### Check 5 fails on ALL variants

| Run | Percentage | PDF hours | shiftDuration sent | Check 5 |
|-----|-----------|-----------|-------------------|---------|
| 19:14 | 80% | 6.0h | 7.5 | FAILED |
| 19:31 | 100% | 7.5h | 7.5 | FAILED |
| 19:41 | 80% | 6.0h | 7.5 | FAILED |
| 21:23 | 100% | 7.5h | 7.5 | FAILED |
| 07:28 | 80% | 6.0h | 7.5 | FAILED |
| 07:32 | 80% | 6.0h | 7.5 | FAILED |
| 09:25 | 100% | 7.5h | 7.5 | FAILED |

All 7 PDF runs fail Check 5. All send `shiftDurationHours: 7.5`.

## Fix

Remove `shiftDurationHours` from the `employmentDetails` array in the `POST /employee/employment` body.

In `system-prompt.ts`, Task 21 workflow step 4, change from:
```
employmentDetails:[{date:<startDate>, employmentType:"ORDINARY", employmentForm:"PERMANENT",
  remunerationType:"MONTHLY_WAGE", workingHoursScheme:"NOT_SHIFT",
  percentageOfFullTimeEquivalent:<pct>, shiftDurationHours:7.5,
  occupationCode:{id:<from_step1>}, annualSalary:<salary>}]
```

To:
```
employmentDetails:[{date:<startDate>, employmentType:"ORDINARY", employmentForm:"PERMANENT",
  remunerationType:"MONTHLY_WAGE", workingHoursScheme:"NOT_SHIFT",
  percentageOfFullTimeEquivalent:<pct>,
  occupationCode:{id:<from_step1>}, annualSalary:<salary>}]
```

Also apply to Task 19 workflow (same issue — Check 10 likely same root cause).

## Score Impact

| Metric | Before | After |
|--------|--------|-------|
| Checks | 9/10 (12/14 raw) | 10/10 (14/14 raw) |
| Normalized | 2.5714 | up to 6.0 (Tier 3 × efficiency) |
| Points gained | — | +3.43 potential |

## Theories tested and ruled out

1. occupationCode not saved → WRONG (it IS saved in POST)
2. Email generation → correct for all names
3. Department name → matches PDF
4. Employment fields (type, form, scheme) → all correct
5. StandardTime → created correctly
6. Division municipality → works despite inactive municipality
7. latestSalary null → same for UI and API created
8. Inline vs separate employee+employment creation → identical results
9. Address/phone/bankAccount → not in PDF, not checked
10. employeeNumber → not required
