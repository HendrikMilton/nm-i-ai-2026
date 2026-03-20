Read /home/hendrik/Documents/agentic-avengers-nm-ai/hendrik/challenge1/program.md for full context.

You are running the autoresearch loop for Challenge 1 (Tripletex AI agent).

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

## CRITICAL RULES
- Server is already running with hot reload (bun --watch). SSH tunnel is up. Endpoint is https://tripletex.hycapital.io/solve
- NEVER restart cloudflared or the SSH tunnel
- After EVERY run, check apiLog for wasted calls. Even 1 unnecessary call must be fixed.
- Validators are auto-generated: edit scripts/generate-validators.ts then run `bun run scripts/generate-validators.ts`
- VAT type IDs are hardcoded in system prompt — never let the agent call GET /ledger/vatType
- If a new task type fails, research the Tripletex API (sandbox creds in .env: TRIPLETEX_SANDBOX_URL and TRIPLETEX_SANDBOX_TOKEN) then fix the prompt
- Commit after every change. Never push. Never force push.
- Check leaderboard every ~10 submissions: `bash scripts/check-score.sh` (uses ACCESS_TOKEN from .env)
