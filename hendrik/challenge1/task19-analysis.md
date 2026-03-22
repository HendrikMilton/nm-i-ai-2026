# Task 19 Analysis: Employee creation from contract (Tier 3)

## Current Status
- **Best score**: 2.7273 / 6.0 (45%)
- **Best checks**: 14/15 passed (Check 10 always fails)
- **score_raw**: 20/22 — each failed check costs 2 points
- **Efficiency bonus**: 1.0x (no bonus — too many calls)
- **Tier 3**: correctness × 3 × efficiency = max 6.0

## Critical: Even with perfect efficiency, 14/15 caps at 2.73
- 20/22 × 3 × 2.0 = 5.45 (best possible with 14/15)
- **We MUST fix Check 10** to have any chance at 6.0
- With 15/15: 22/22 × 3 × 2.0 = 6.0

## All Task 19 Runs (15-check variant only)

| Log | Score | Calls | Errors | Failed Checks | STYRK |
|-----|-------|-------|--------|---------------|-------|
| 09:06 | 2.7273 | 8 | 0 | Check 10 | 4110 |
| 07:34 | 2.7273 | 9 | 1 | Check 10 | 4110 |
| 07:29 | 2.7273 | 9 | 1 | Check 10 | 4110 |
| 10:33 | 2.4545 | 8 | 0 | Check 10, 13 | 3323 |
| 20:44 | 2.4545 | 10 | 0 | Check 10, 13 | 3323 |
| 20:47 | 2.4545 | 25 | 25 | Check 10, 13 | 3323 |

## Check 10 — ALWAYS FAILS (unknown root cause)

Check 10 fails in every single run regardless of STYRK code or other fields.

### What we've ruled out:
- **Address**: Contracts DO NOT contain addresses. Prompt says "extract address" but none of the 4 contract PDFs have address fields. We tested creating an employee WITH address in sandbox — it works, but there's no address to extract.
- **endDate**: Some runs set endDate, some don't. Check 10 fails in both cases.
- **shiftDurationHours**: Some runs set it (7.5), some don't. Check 10 fails in both cases.
- **occupationCode**: Different codes used across runs. Check 10 fails for all.

### Possible candidates for Check 10:
1. **Address is expected despite not being in the contract** — maybe the checker always checks for address, and since no contract has one, it always fails. Could test by providing a dummy address.
2. **Normaltid / standardTime** — the "Normaltid" section in Tripletex UI is empty. Task 21 has a step `POST /employee/standardTime`, Task 19 doesn't. Maybe Task 19 also needs it?
3. **Some other field** we haven't considered (Ansattkategori, Ansattnummer, etc.)

### Recommended investigation:
- Submit a test run with a dummy address to see if Check 10 passes
- Submit a test run with POST /employee/standardTime to see if Check 10 passes
- Both are low-risk since best score per task is kept

## Check 13 — Fails for STYRK 3323 only

### Pattern:
- STYRK **4110** + KONTORMEDARBEIDER (code **41**14105) → Check 13 PASSES
- STYRK **3323** + INNKJØPSASSISTENT (code **34**16103) → Check 13 FAILS
- STYRK **3323** + INNKJØPER (code **34**16102) → Check 13 FAILS

### Root cause:
The Tripletex occupation code system uses STYRK-98 7-digit codes. The contracts use STYRK-08 4-digit codes. These are DIFFERENT classification systems:
- STYRK-08 **33** = Business and administration
- STYRK-98 **33** = Education (teachers, instructors)
- STYRK-08 **34** = Legal, social, cultural
- STYRK-98 **34** = Business professionals (innkjøp, etc.)

The checker likely validates the first 2 digits of the Tripletex code against the STYRK-08 code:
- STYRK-08 **41**10 → Tripletex code **41**14105 → first 2 digits match → PASS
- STYRK-08 **33**23 → Tripletex code **34**16103 → 33 ≠ 34 → FAIL

### Problem:
There are NO occupation codes in the entire Tripletex database (7116 codes) that start with "3323" or even "33" that relate to purchasing/innkjøp. All "33" codes are education-related. This is a fundamental mismatch between STYRK-08 and the Tripletex classification.

### Possible fixes:
- Find if there's a different way to set STYRK code (maybe a raw code field)
- Accept Check 13 failure for STYRK 3323 and focus on fixing Check 10

## Contract PDF Structure (all 4 examined)

All contracts have identical structure:
- Arbeidsgiver, Arbeidstaker, Fødselsdato, Personnummer, E-post, Bankkonto
- Ansettelsesdetaljer: Avdeling, Stillingskode (STYRK), Ansettelsesform, Lønnstype, Stillingsprosent, Årslønn, Tiltredelse
- NO address field in any contract
- Languages seen: Norwegian, Portuguese, Spanish, English

## Sandbox Test

Created employee "TestTask19 Analyse" in sandbox with address and all fields.
Verified in Tripletex UI — all fields correctly populated.
Employee id: 18787828 on kkpqfuj-amager.tripletex.dev

## Next Steps (priority order)

1. **Fix Check 10** — this is THE blocker. Without it, max score is 2.73.
   - Test hypothesis: add dummy address or POST /employee/standardTime
2. **Fix Check 13 for STYRK 3323** — worth 2 points per occurrence
   - Research STYRK-08 to Tripletex code mapping
3. **Reduce API calls** — for efficiency bonus (currently 1.0x, need 2.0x)
