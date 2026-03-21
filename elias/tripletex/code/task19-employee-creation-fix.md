# Task 19 — Employee Creation from Contract — Fix Report

**Date:** 2026-03-21
**Current score:** 2.45 (best: raw 18/22, 13/15 checks passed)
**Potential score:** ~3.50
**Impact:** +1.05 points
**Tier:** 2 (x2 multiplier)

---

## Task Description

"You received an employment contract (see attached PDF). Create the employee in Tripletex with all details from the contract: national identity number, date of birth, department, occupation code, salary, employment percentage, and start date."

## Scoring History

| Submission | Checks | Failed | Score |
|-----------|--------|--------|-------|
| 15-check variant | 13/15 | Check 10, Check 13 | 2.4545 (best) |
| 10-check variant | 9/10 | Check 5 | 2.5714 |
| 10-check variant | 8/10 | Check 5, Check 10 | 2.3571 |

Check 5 (10-check) and checks 10/13 (15-check) consistently fail across runs.

---

## Root Cause 1: Wrong occupationCode (CONFIRMED)

### What the agent does

```json
POST /employee/employment with occupationCode: {"id": "3512"}
```

The agent passes the 4-digit STYRK code as the API ID.

### What actually happens

Verified on sandbox:
```
GET /employee/employment/occupationCode/3512
→ id=3512, nameNO="LØNNINGSSJEF", code="1232114"
```

API ID 3512 maps to **"LØNNINGSSJEF" (Payroll Manager)** — NOT to STYRK 3512 which is "IKT-brukerstotte" (IT User Support). The employee gets the wrong occupation.

### What the system prompt says (lines 74-75)

```
CRITICAL: occupationCode STYRK numbers (e.g. 3512) are NOT API IDs.
You MUST look up the correct ID:
GET /employee/employment/occupationCode?nameNO=<occupation_title_from_contract>
The API uses 7-digit codes internally — never pass a 4-digit STYRK code as the id.
```

The agent completely ignores this instruction and never calls the lookup endpoint.

### Fix

Make the instruction impossible to skip:

```
- BEFORE creating employment, you MUST call:
  GET /employee/employment/occupationCode?nameNO=<title_from_contract>&count=1
  Use the returned {id} value. NEVER use the STYRK number as the id.
  Example: STYRK 3512 is NOT id 3512. The lookup returns the real id.
```

---

## Root Cause 2: Missing address (LIKELY)

The employee was created with `address: null`. Norwegian employment contracts typically include the employee's home address. The 15-check variant has more checks than the 10-check variant, suggesting the contract had more fields to extract.

The system prompt (line 72) says:
```
POST /employee with {..., address:{...}} — extract ALL fields from the contract
```

The agent likely skipped the address from the PDF. This could explain one of the other failed checks.

### Fix

Emphasize address extraction:
```
Extract ALL personal details from the contract including address.
POST /employee with address: {addressLine1, postalCode, city}
```

---

## What Works Correctly

- Employee basic fields: firstName, lastName, dateOfBirth, nationalIdentityNumber, email, bankAccountNumber
- Department: creates if not exists
- Division: creates if not exists
- Employment: startDate, percentageOfFullTimeEquivalent, annualSalary, employmentForm, remunerationType
- workingHoursScheme: correctly uses "NOT_SHIFT" (older runs used "NON_SHIFT" which caused 422)
- 8 API calls, 0 errors — good efficiency

---

## API Call Sequence (Current)

```
1. GET /department?name=Innkjop                  — check if department exists
2. GET /department?count=100                      — list all departments
3. POST /department (create Innkjop)              — parallel with:
   GET /division?count=1                          — check if division exists
4. GET /municipality?count=1                      — for division creation
5. POST /division                                 — parallel with:
   POST /employee                                 — create employee
6. POST /employee/employment                      — create employment
```

### Missing call

```
   GET /employee/employment/occupationCode?nameNO=<title>&count=1   — MUST ADD before step 6
```

This adds 1 API call but fixes the occupationCode check.

---

## System Prompt Changes Needed

### 1. Enforce occupationCode lookup

Add before the employment creation step:
```
BEFORE creating employment: GET /employee/employment/occupationCode?nameNO=<job_title_from_contract>&count=1
Use the {id} from the response. NEVER pass STYRK numbers as IDs — they map to wrong occupations.
```

### 2. Enforce address extraction

```
Extract the employee's home address from the contract.
POST /employee with address: {addressLine1:"<street>", postalCode:"<code>", city:"<city>"}
```
