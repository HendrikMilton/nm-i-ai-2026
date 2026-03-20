# Autoresearch — Tripletex AI Agent

## Context

You are an autonomous agent improving an AI accounting agent for the NM i AI 2026 competition.
The agent receives accounting tasks in natural language and calls the Tripletex API to complete them.

## Setup

The server should already be running. If not:

```bash
cd ~/agentic-avengers-nm-ai/hendrik/challenge1
MODEL=claude-opus-4-6 PORT=4001 bun run src/index.ts &
```

Verify it's up: `curl -s http://localhost:4001/ | jq .`

## How submission works

Submit a task to the competition:

```bash
curl -s 'https://api.ainm.no/tasks/cccccccc-cccc-cccc-cccc-cccccccccccc/submissions' \
  -H 'content-type: application/json' \
  -b 'access_token=ACCESS_TOKEN_HERE' \
  --data-raw '{"endpoint_url":"ENDPOINT_URL_HERE","endpoint_api_key":null}'
```

The platform sends ONE random task to our /solve endpoint. Each submission = 1 task.
There are 30 task types. Best score per task is kept. Leaderboard = sum of all best scores.

Rate limit: 3 concurrent, ~10 per task per day (~300 total/day).

## Files you can modify

- `src/system-prompt.ts` — the system prompt with API reference and instructions. This is the main thing to iterate on.
- `src/config.ts` — model selection, GCP settings

Do NOT modify: `src/index.ts`, `src/agent.ts`, `src/tripletex.ts`, `src/tools.ts`

## Logs

Each submission creates a log file in `logs/` with timestamp name (e.g. `logs/2026-03-20T11-05-32-108Z.log`).

Log files contain:
- The prompt received
- Every tool call and result (full JSON)
- Step-by-step agent reasoning
- Final summary: elapsed time, API calls count, errors count

## Scoring

- **Correctness**: field-by-field checks, normalized 0-1
- **Tier multiplier**: Tier 1 (×1), Tier 2 (×2), Tier 3 (×3)
- **Efficiency bonus**: up to 2× on perfect scores — fewer API calls + zero 4xx errors = higher bonus
- **Max per task**: 6.0 (perfect Tier 3 + best efficiency)
- Every 4xx error REDUCES the score. Zero errors is critical for max score.

## The loop

LOOP FOREVER:

1. **Check** — run `bash scripts/submit.sh` which first checks for in-progress submissions. If it exits with code 2, wait 30 seconds and retry.
2. **Submit** — if no submissions in progress, it submits automatically.
3. **Wait** — watch `logs/` for a new file to appear (the platform takes a few seconds to send the task, then our agent processes it). Wait until the log file contains "DONE".
3. **Analyze** — read the log file. Extract:
   - Task type / prompt (what was asked)
   - API calls made and their status codes
   - Number of errors (4xx responses)
   - Whether the task was completed correctly
   - Time taken
4. **Decide** — based on the analysis:
   - If **0 errors** and task completed: PERFECT. Just submit again.
   - If **errors occurred**: identify the root cause. Common patterns:
     - Missing required field → add to system prompt
     - Wrong endpoint used → fix in system prompt
     - Unnecessary GET before POST → optimize in system prompt
     - Parallel calls causing 409 → add "do sequentially" rule
   - If you see a NEW task type we haven't handled → add pattern to system prompt
5. **Fix** (if needed) — edit `src/system-prompt.ts` with the fix. Be surgical — only add what's needed. Don't remove working instructions.
6. **Restart server** — `lsof -ti:4001 | xargs kill -9; sleep 1; MODEL=claude-opus-4-6 PORT=4001 bun run src/index.ts &; sleep 2`
7. **Commit** — `git add src/system-prompt.ts && git commit -m "prompt: <what you fixed>"`
8. Go to step 1.

## Results tracking

Maintain `results.tsv` (tab-separated) in the challenge1 directory:

```
timestamp	task_type	elapsed	api_calls	errors	status	notes
2026-03-20T11:05	payment_reversal	23.4s	4	0	perfect
2026-03-20T11:06	create_invoice	82.6s	23	8	completed	product numbers already existed
```

- task_type: your best guess from the prompt (create_employee, create_invoice, payment_reversal, etc.)
- status: `perfect` (0 errors), `completed` (has errors but succeeded), `failed` (didn't complete)
- Append after each submission. Do NOT commit this file.

## Score checking

Every ~10 submissions, check our leaderboard position:

```bash
bash scripts/check-score.sh
```

This returns our rank, total score, tasks touched, and per-tier scores. Log it in results.tsv as a special row:

```
2026-03-20T12:00	LEADERBOARD	-	-	-	rank=43	score=11.77 t1=5.77 t2=6.0 t3=0 touched=18
```

## Rate limiting

- **Wait at least 2 minutes between submissions.** We have 180/day — burning them too fast wastes the daily quota.
- Aim for ~20-30 submissions per hour max.
- The submit script already checks for in-progress submissions and won't double-send.

## Rules

- **NEVER STOP**. The human is asleep. Keep submitting and improving.
- **Be conservative with prompt changes** — only fix what's broken. Don't rewrite working instructions.
- **Commit after every prompt change** with a descriptive message.
- **Never force push or use destructive git ops.**
- If the submission fails (network error, platform down), wait 60 seconds and retry.
- If you see the same error pattern 3+ times, it's a systemic issue worth fixing in the prompt.
- If you run out of ideas, just keep submitting — more task coverage = higher leaderboard score.
