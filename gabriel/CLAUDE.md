# Gabriel — Tripletex Challenge

## Context

You are working on the Tripletex challenge for NM i AI 2026 (Norwegian AI Championship).
The task: build an AI agent that completes accounting tasks in Tripletex using an LLM + API calls.

## Working on the VM

You're on a GCP VM. The code is at `~/agentic-avengers-nm-ai/gabriel/tripletex_challenge_task/`.

```bash
# Start the server (if not running)
cd ~/agentic-avengers-nm-ai/gabriel/tripletex_challenge_task
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# The cloudflared tunnel should be running — check with:
pgrep -f cloudflared || cloudflared tunnel --url http://localhost:8000
```

## Rules

- **Never modify `main.py`** — it's the FastAPI wrapper.
- **All logic goes in `solve.py`** — edit only this file.
- The server auto-reloads when you save solve.py.
- Commit frequently with descriptive messages.
- After testing a change, note the score in your commit message.

## Architecture

1. POST `/solve` receives: `{prompt, files[], tripletex_credentials}`
2. `solve.py` sends prompt → Gemini 2.5 Pro (Vertex AI)
3. Gemini returns a plan of Tripletex API calls
4. Code executes the calls via authenticated proxy
5. Returns `{"status": "completed"}`

## LLM

Using Gemini 2.5 Pro via Vertex AI. Project: `ai-nm26osl-1713`, region: `europe-west4`.
Already configured on this VM via default service account.

## Tripletex API

- Base URL: provided in each request (`tripletex_credentials.base_url`)
- Auth: Basic Auth, username `"0"`, password = session_token
- Common endpoints: /employee, /customer, /product, /invoice, /order, /travelExpense, /project, /department, /ledger/account, /ledger/voucher
- API docs: https://kkpqfuj-amager.tripletex.dev/v2-docs/

## Scoring

- 30 task types, best score per task kept
- Field-by-field correctness × tier multiplier (1/2/3)
- Efficiency bonus (up to 2×) for perfect scores with minimal API calls and zero 4xx errors
- Max 6.0 per task
- Rate limit: 5 per task per day — don't waste submissions

## Key improvement areas

- Multi-turn: send API results back to Gemini for follow-up reasoning
- Better system prompt with Tripletex API field requirements
- Handle PDF/image attachments properly
- Error recovery loop
- Minimize total API calls
