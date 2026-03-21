# Task 19 — Employee Creation from Contract: Two Fixes

## Status: 2.45 points (13/15 checks). Tier 2 (max 4.0). Top team: 4.0.

## Checks 10 and 13 ALWAYS fail.

## Problem 1: endDate set for permanent position (Check 10)

System prompt (line 146) hardcodes `endDate:"2030-12-31"`.
But the PDF says "Fast stilling" (permanent position) with NO end date.
The checker expects endDate to be null for permanent employment.

### Evidence

Agent POST /employee/employment body includes:
```
"endDate": "2030-12-31"
```
But PDF contract says "Fast stilling" and has no end date field.

### Fix

Remove `endDate:"2030-12-31"` from the system prompt.
For permanent positions ("Fast stilling"), do NOT set endDate.

### Sandbox verified

Employment created without endDate: endDate=None ✓
UI shows Sluttdato field empty ✓

## Problem 2: Wrong occupation code level (Check 13)

Agent searches `nameNO=Innkjøper` and gets id=2503 (INNKJØPER, code 3416102).
But STYRK 3323 = "Innkjøps- og forsyningsassistenter" (ASSISTANT level).
The correct match is id=2507 INNKJØPSASSISTENT (code 3416103).

### Evidence

```
STYRK 3323 → "assistenter" (assistant level)
Agent picked:  id=2503 INNKJØPER (code 3416102) — buyer level ✗
Correct:       id=2507 INNKJØPSASSISTENT (code 3416103) — assistant level ✓
```

The STYRK 4-digit code maps to a GROUP of 7-digit Tripletex codes.
The agent picks the first/generic result instead of matching the level.

### Fix

When looking up occupation code, search for the SPECIFIC level from the STYRK description:
- STYRK ending in "-assistenter" → search "assistent" in the occupation name
- STYRK ending in "-direktører" → search "direktør"
- STYRK ending in "-konsulenter" → search "konsulent"
- STYRK ending in "-ledere" → search "leder"

Or better: search the FULL Norwegian occupation title from STYRK, not just the root word.

### Sandbox verified

Employment with occupationCode id=2507 (INNKJØPSASSISTENT): works ✓
UI shows Yrkeskode: 3416103 INNKJ... ✓

## PDF Contract Structure (verified from 2 PDFs)

All contract PDFs have identical fields:
- Arbeidsgiver, Arbeidstaker, Fodselsdato, Personnummer
- E-post, Bankkonto
- Avdeling, Stillingskode (STYRK), Ansettelsesform
- Lonnstype, Stillingsprosent, Arslonn, Tiltredelse

NO address field in any contract PDF.

## Full End-to-End Sandbox Test

Created employee "CorrectCode Test" with both fixes applied:
```
Employee: firstName, lastName, department, email, dateOfBirth,
          nationalIdentityNumber, bankAccountNumber ✓
Employment:
  startDate: 2026-05-09 ✓
  endDate: None (not set) ✓
  occupationCode: id=2507 INNKJØPSASSISTENT ✓
  annualSalary: 470000 ✓
  percentageOfFullTimeEquivalent: 100 ✓
  employmentForm: PERMANENT ✓
```

UI verified: all fields correct in Ansattoversikt and Arbeidsforhold tab.

## Expected Score

| Metric | Value |
|--------|-------|
| Current | 2.45 (13/15 checks) |
| After fix | 3.5-4.0 (15/15 checks, Tier 2) |
| Top team | 4.0 |
