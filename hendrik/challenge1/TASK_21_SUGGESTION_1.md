# Task 21 — Occupation Code Search Fix

## Problem

Agent spent 4 GET calls searching for occupation code ("konsulent", "IKT-konsulent", "IKT", "IT-konsulent") and ran out of time before creating the employee. All 10 checks failed because the employee was never created.

## Suggested Changes to system-prompt.ts

### 1. Add missing STYRK codes to mapping (line ~141)

Add these to the Common STYRK codes list:
- `1235→"Logistikksjef"`
- `2130→"IT-konsulent"`
- `3323→"Innkjøpsassistent"`

### 2. Strengthen the 2-call limit (line ~148)

Replace:
```
If no match, try shorter/broader terms. Do NOT spend more than 2 GET calls on this.
If still no match, use a generic one like "KONTORMEDARBEIDER" (id varies per sandbox).
```

With:
```
HARD LIMIT: Maximum 2 GET calls for occupation code. After 2 failed searches, immediately use "KONTORMEDARBEIDER" as fallback.
Do NOT spend more time searching — creating the employee is more important than finding the perfect code.
```

### 3. Same fix applies to Task 21 workflow (line ~156)

The Task 21 workflow also searches occupation codes. Add the same STYRK mapping and hard limit there too, or reference the Task 19 mapping.

## Evidence

From log `2026-03-22T09-29-40-463Z.log`:
- Search 1: "konsulent" → generic results, no exact match
- Search 2: "IKT-konsulent" → 0 results
- Search 3: "IKT" → 0 results
- Search 4: "IT-konsulent" → found (id 2610)
- By this point, 73 seconds elapsed, scoring deadline passed, employee never created → 0/10
