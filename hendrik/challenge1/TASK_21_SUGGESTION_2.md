# Task 21: Employee Onboarding — Check 5 Failure Analysis

**Date:** 2026-03-22
**Log:** 2026-03-22T09-25-25-128Z.log
**Score:** 12/14 (2.5714/6.0) — Check 5 failed

## Root Cause

Task 21 workflow step 3 only includes `{firstName, lastName, department, userType, dateOfBirth, email}` when creating the employee. But the offer letter PDF likely contains additional personal details (nationalIdentityNumber, bankAccountNumber, address) that the evaluator checks.

Task 19's workflow (which Task 21 references as "Same as Task 19") explicitly includes `nationalIdentityNumber, bankAccountNumber, address:{addressLine1, postalCode, city}` in step 3. Task 21 dropped these fields.

## Evidence

- Agent POST /employee body: `{firstName, lastName, department, dateOfBirth, email, userType}` — no nationalIdentityNumber, no bankAccountNumber, no address
- Check 5 failed — positionally consistent with a missing employee-level field after name/DOB/email/department
- All employment/salary/standardTime checks passed (checks 6-10)

## Proposed Fix

Change Task 21 step 3 in `system-prompt.ts:162` from:

```
3. POST /employee with {firstName, lastName, department:{id}, userType:"NO_ACCESS", dateOfBirth, email:"<firstname.lastname@example.org>" (generate from name, lowercase, replace special chars: ø→o, å→a, æ→ae, ü→u, ö→o, ä→a, é→e, á→a, ñ→n, í→i, ó→o, ú→u)}
```

To:

```
3. POST /employee with {firstName, lastName, department:{id}, userType:"NO_ACCESS", dateOfBirth, email:"<firstname.lastname@example.org>" (generate from name, lowercase, replace special chars: ø→o, å→a, æ→ae, ü→u, ö→o, ä→a, é→e, á→a, ñ→n, í→i, ó→o, ú→u), nationalIdentityNumber, bankAccountNumber, address:{addressLine1, postalCode, city}}
   CRITICAL: Extract ALL personal details from the offer letter — nationalIdentityNumber (fødselsnummer), bankAccountNumber, and address are often present and WILL be checked.
```

## Risk

Low — this only adds fields to the POST body if they exist in the PDF. If the PDF doesn't contain them, the agent simply won't include them. No downside.
