You are an autonomous agent improving an AI accounting agent for the NM i AI 2026 competition.
The agent receives accounting tasks in natural language and calls the Tripletex API to complete them.

## How it works
- The platform sends ONE random task to our /solve endpoint per submission. Each submission = 1 task.
- There are 30 task types. Best score per task is kept. Leaderboard = sum of all best scores.
- `scripts/autoloop.ts` handles: check queue → submit → wait for log → print score → exit.

## Scoring
- **Correctness**: field-by-field checks, normalized 0-1
- **Tier multiplier**: Tier 1 (×1), Tier 2 (×2), Tier 3 (×3)
- **Efficiency bonus**: up to 2× on perfect scores — fewer API calls + zero 4xx errors = higher bonus
- **Max per task**: 6.0 (perfect Tier 3 + best efficiency)
- Every 4xx error REDUCES the score. Zero errors is critical for max score.

## Files you can modify
- `src/system-prompt.ts` — the system prompt with API reference and instructions. Main thing to iterate on.
- `src/validators.ts` — auto-generated, do NOT edit directly
- `scripts/generate-validators.ts` — edit this to change validators, then run `bun run scripts/generate-validators.ts`
- `src/config.ts` — model selection, GCP settings

## Logs
Each submission creates a log file in `logs/` with the full prompt, every tool call/result, and final summary (elapsed, API calls, errors).

## Your flow
1. Run: `bun run scripts/autoloop.ts` in background (ACCESS_TOKEN is in .env, auto-loaded by bun)
2. When it completes, read the log file it printed
3. CRITICALLY analyze the log:
   - ANY unnecessary API call = FIX IMMEDIATELY (edit system-prompt.ts, commit)
   - ANY error (4xx/5xx) = understand root cause, fix system-prompt.ts or validators
   - ANY failed check = research why and fix before next submission
   - Score < max = DO NOT PROCEED until you understand why and fix it
4. Only after fixing issues (or confirming perfect run), run autoloop.ts again
5. Never stop. Assume I'm asleep.

## IMPORTANT
- Do NOT read or analyze existing logs in the logs/ folder. They are old and from before fixes were applied.
- Only analyze logs from YOUR submissions (the ones autoloop.ts prints).

## CRITICAL RULES
- Server is already running with hot reload (bun --watch). SSH tunnel is up. Endpoint is https://tripletex.hycapital.io/solve
- NEVER restart the server, cloudflared, or the SSH tunnel. Hot reload handles code changes.
- After EVERY run, check apiLog for wasted calls. Even 1 unnecessary call must be fixed.
- VAT type IDs are hardcoded in system prompt — never let the agent call GET /ledger/vatType
- If a new task type fails, research the Tripletex API (sandbox creds in .env: TRIPLETEX_SANDBOX_URL and TRIPLETEX_SANDBOX_TOKEN) then fix the prompt
- Be conservative with prompt changes — only fix what's broken. Don't rewrite working instructions.
- Commit after every change. Never push. Never force push.
- Check leaderboard every ~10 submissions: `bash scripts/check-score.sh`
- If the submission fails (network error, platform down), wait 60 seconds and retry.
- If you see the same error pattern 3+ times, it's a systemic issue worth fixing in the prompt.
- Rate limit: 180 submissions/day, max 3 concurrent. autoloop.ts already handles waiting and rate limiting.
