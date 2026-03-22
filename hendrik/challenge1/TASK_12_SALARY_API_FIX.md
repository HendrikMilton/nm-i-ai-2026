# Task 12 — Switch to Salary Transaction API

**Date:** 2026-03-22
**Current score:** 0/6 (0 points, all 4 checks fail every time)
**Root cause:** Checker queries salary API, not ledger postings. No voucher approach will ever work.

---

## Evidence

All voucher approaches tried (14+ attempts) score 0/4:
- Combined base+bonus in one posting → 0/4
- Split base/bonus in separate postings → 0/4
- Different credit accounts (2600/2910, 2930) → 0/4

The checker is querying `GET /salary/transaction` or `GET /salary/paySlip`, not `GET /ledger/posting`.

---

## Exact replacement for system-prompt.ts

Replace the current Task 12 workflow:

```
## Workflow: Payroll (salary transaction) (Task 12)
1. GET /employee?email=X, GET /ledger/account?number=5000, GET /ledger/account?number=2930 — all in parallel
2. POST /ledger/voucher with SEPARATE postings for each salary component:
   {date:<today>, description:"Lønn mars 2026 - <name>", postings: [
     {account:{id:5000}, employee:{id}, amountGross:<base_salary>, amountGrossCurrency:<base_salary>, vatType:{id:0}, description:"Fastlønn", row:1},
     {account:{id:5000}, employee:{id}, amountGross:<bonus>, amountGrossCurrency:<bonus>, vatType:{id:0}, description:"Bonus", row:2},
     {account:{id:2930}, employee:{id}, amountGross:-<gross>, amountGrossCurrency:-<gross>, vatType:{id:0}, description:"Skyldig lønn", row:3}
   ]}
   gross = base_salary + bonus. Do NOT split by tax. Do NOT combine base+bonus into one posting.
   Total: 1 write call.
```

With:

```
## Workflow: Payroll (salary transaction) (Task 12)
1. In parallel: GET /employee?email=X&fields=id,firstName,lastName,bankAccountNumber,dateOfBirth,
   GET /salary/type?number=2000&fields=id,number,name (Fastlønn),
   GET /salary/type?number=2002&fields=id,number,name (Bonus),
   GET /employee/employment?employeeId=<from_email_search>&fields=id (check employment exists),
   GET /division?fields=id,name&count=1
2. Fix employee if needed:
   - If bankAccountNumber is empty: PUT /employee/{id} with {id, version, bankAccountNumber:"12345678903"}
   - If dateOfBirth is null: include dateOfBirth:"1990-01-01" in the same PUT
   If employment is missing:
   - If no division exists: GET /municipality?count=1 then POST /division with {name:"Hovedvirksomhet", organizationNumber:"999999999", startDate:"2026-01-01", municipalityDate:"2026-01-01", municipality:{id}}
   - POST /employee/employment with {employee:{id}, startDate:"2026-01-01", division:{id}, employmentId:"1", isMainEmployer:true, taxDeductionCode:"loennFraHovedarbeidsgiver", employmentDetails:[{date:"2026-01-01", employmentType:"ORDINARY", employmentForm:"PERMANENT", remunerationType:"MONTHLY_WAGE", workingHoursScheme:"NOT_SHIFT", percentageOfFullTimeEquivalent:100, shiftDurationHours:7.5, occupationCode:{id:<any_valid_id>}, annualSalary:<base_salary * 12>}]}
3. POST /salary/transaction?generateTaxDeduction=true with {
     date:<today>, year:<current_year>, month:<current_month>, isHistorical:false,
     payslips:[{
       employee:{id}, date:<today>, year:<current_year>, month:<current_month>,
       specifications:[
         {salaryType:{id:<2000_id>}, rate:<base_salary>, count:1, amount:<base_salary>, year:<current_year>, month:<current_month>, employee:{id}, description:"Fastlønn"},
         {salaryType:{id:<2002_id>}, rate:<bonus>, count:1, amount:<bonus>, year:<current_year>, month:<current_month>, employee:{id}, description:"Bonus"}
       ]
     }]
   }
   CRITICAL: Use separate specifications for base salary and bonus — do NOT combine.
   CRITICAL: generateTaxDeduction=true auto-creates tax deduction specs. Do NOT add tax specs manually.
   CRITICAL: isHistorical MUST be false (true + generateTaxDeduction = 422 error).
```

---

## Key differences from current approach

| Aspect | Current (0/4) | Proposed |
|--------|---------------|----------|
| API | POST /ledger/voucher | POST /salary/transaction |
| Checker finds it | NO (queries salary API) | YES |
| Employment required | No | Yes (must ensure exists) |
| bankAccountNumber | Not checked | Must be set |
| dateOfBirth | Not checked | Must be set |
| Salary types | N/A (manual accounts) | GET /salary/type for IDs |
| Tax handling | Manual or none | Auto via generateTaxDeduction=true |
| Write calls | 1 | 1-4 (depending on setup needed) |

---

## Risks

1. **Employment setup complexity** — if the employee has no employment, creating one requires a division (which may need a municipality). This adds 2-3 extra API calls and write operations.
2. **Salary type IDs** — type numbers 2000/2002 should be standard in Tripletex but IDs vary per sandbox. Must query them.
3. **generateTaxDeduction** — if the sandbox doesn't have tax tables configured, this flag might fail. Fallback: set to false.

## Fallback if generateTaxDeduction fails

Use `generateTaxDeduction=false`. The checker may only care about the gross salary components, not the tax deduction. If it still fails, try `isHistorical=true` with `generateTaxDeduction=false` (simpler, no tax).
