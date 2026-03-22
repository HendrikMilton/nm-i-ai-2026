# Task 24 — Deep Analysis & Confirmed Fix

**Date:** 2026-03-22
**Analysts:** Gabriel + Claude
**Current score:** 3.75/6.0 (best: 4/4 checks pass, but Check 3 fails ~70% of the time)
**Task:** Correct 4 ledger errors (wrong account, duplicate, missing VAT, wrong amount)

---

## The problem

Check 3 (missing VAT correction) fails in most attempts. When it passes, the score is 3.75 (limited by efficiency). When it fails, score drops to 2.25.

## Root cause — confirmed in sandbox + Tripletex UI

The system prompt tells the agent to correct missing VAT by posting through the **expense account with vatType:{id:1}**. This causes Tripletex to double-apply VAT — it treats the VAT correction amount as a gross amount and splits it into net (80%) + VAT (20%).

### System prompt (WRONG):
```
Row 1: expense_account, amountGross=+<missing_gross>, vatType:{id:1}
Row 2: 2400, amountGross=-<missing_gross>, vatType:{id:0}
```

### What this produces (WRONG):
For missing VAT of 1337.50 (= 5350 × 0.25):
```
6300 Leie lokale:     +1,070.00  (80% — should NOT be here)
2710 Inngående MVA:     +267.50  (20% — should be 1,337.50!)
2400 Leverandørgjeld: -1,337.50  (correct)
```

### Correct approach (post directly to 2710):
```
2710 Inngående MVA:   +1,337.50  (full missing VAT)
2400 Leverandørgjeld: -1,337.50
```

## Evidence

### Sandbox test (Bilag #82 vs #83)
Created both approaches side by side in sandbox and verified in Tripletex UI:
- **#82 (WRONG):** 6300 +1,070 / 2710 +267.50 / 2400 -1,337.50
- **#83 (CORRECT):** 2710 +1,337.50 / 2400 -1,337.50

### Account balance comparison
| Account | After WRONG fix | After CORRECT fix | Expected |
|---------|----------------|-------------------|----------|
| 6300 (expense) | 6,420 (inflated!) | 5,350 | 5,350 |
| 2710 (input VAT) | 267.50 (only 20%!) | 1,337.50 | 1,337.50 |
| 2400 (supplier) | -6,687.50 | -6,687.50 | -6,687.50 |

### Competition log analysis (ALL 10 attempts)
| Attempt | Check 3 | MVA approach | Expense added | 2710 added |
|---------|---------|-------------|---------------|------------|
| 18-37 | PASS | Direct to 2710, vatType 0 | 0 | 3,487.50 (100%) |
| 19-55 | FAIL | Split via expense | +4,270 (80%) | +1,067.50 (20%) |
| 21-02 | FAIL | Split via expense | +1,070 (80%) | +267.50 (20%) |
| 21-05 | FAIL | Split via expense | same pattern | same pattern |
| 21-31 | FAIL | Split via expense | +3,350 (80%) | +837.50 (20%) |
| 07-41 | FAIL | Split via expense | +3,980 (80%) | +995 (20%) |
| 09-21 | FAIL | Split via expense | +4,870 (80%) | +1,217.50 (20%) |

100% correlation: direct-to-2710 = pass, split-via-expense = fail.

## Fix

Change the missing VAT instruction in system-prompt.ts from:
```
Row 1: expense_account, amountGross=+<missing_gross>, vatType:{id:1}
Row 2: 2400, amountGross=-<missing_gross>, vatType:{id:0}, supplier:{id}
```

To:
```
Row 1: 2710 (inngående MVA), amountGross=+<missing_vat>, vatType:{id:0}
Row 2: 2400 (leverandørgjeld), amountGross=-<missing_vat>, vatType:{id:0}, supplier:{id}
```

The expense account already has the correct ex-VAT amount. Only the VAT posting on 2710 and the supplier credit adjustment on 2400 are missing.

## Important correction

vatType 1 = "Fradrag inngående avgift" = INPUT VAT (correct for purchases).
vatType 3 = "Utgående avgift" = OUTPUT VAT (for sales).
The old research doc had these backwards. Do NOT change vatType on supplier invoices.
