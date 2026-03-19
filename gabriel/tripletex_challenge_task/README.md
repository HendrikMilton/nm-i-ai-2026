# Tripletex AI Agent

AI agent that completes accounting tasks in Tripletex via Gemini 2.5 Pro + Tripletex API.

## First time setup

### 1. Install gcloud CLI

```bash
curl https://sdk.cloud.google.com | bash
exec -l $SHELL
```

### 2. Login to the shared GCP account

```bash
gcloud auth login
# Browser opens — sign in with the shared account (credentials in Slack DM)
gcloud config set project ai-nm26osl-1713
```

### 3. SSH into the VM

```bash
gcloud compute ssh tripletex-agent --zone=europe-west4-a --project=ai-nm26osl-1713
```

### 4. Switch to your user and go to the code

```bash
sudo su - gabriel
cd ~/agentic-avengers-nm-ai/gabriel/tripletex_challenge_task
```

Everything is already installed (uv, deps, Claude Code).

### 5. Start the server

```bash
# Use tmux so things survive if you disconnect
tmux

# Pane 1: start the server
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Pane 2 (Ctrl-b c): start the HTTPS tunnel
cloudflared tunnel --url http://localhost:8000
```

The tunnel prints a URL like `https://something-random.trycloudflare.com`.
Submit `https://something-random.trycloudflare.com/solve` to the competition at https://app.ainm.no/submit/tripletex

**Note:** The tunnel URL changes if cloudflared restarts. Re-submit the new URL if that happens.

## Development loop

```
1. Edit solve.py        ← all your logic goes here
2. Server auto-reloads  ← uvicorn --reload handles this
3. Test locally:        curl -X POST http://localhost:8000/solve \
                          -H "Content-Type: application/json" \
                          -d '{"prompt": "test", "files": [], "tripletex_credentials": {"base_url": "https://tx-proxy.ainm.no/v2", "session_token": "fake"}}'
4. Submit on competition platform → see score
5. Repeat
```

No redeploy, no Docker, no CI. Just edit and save.

## Using Claude Code on the VM

Claude Code is already installed. Just run:

```bash
sudo su - gabriel
cd ~/agentic-avengers-nm-ai/gabriel/tripletex_challenge_task
claude
```

Claude Code can edit solve.py, run the server, test endpoints, and iterate for you.

## How the agent works

1. Competition POSTs to `/solve` with an accounting task prompt (Norwegian/English/etc)
2. `solve.py` sends the prompt + any file attachments to **Gemini 2.5 Pro** via Vertex AI
3. Gemini returns a JSON plan of Tripletex API calls to make
4. The code executes those API calls against the Tripletex sandbox
5. Returns `{"status": "completed"}`

## Files

| File | What it does |
|------|-------------|
| `main.py` | FastAPI wrapper — **don't modify** |
| `solve.py` | **All agent logic here** — this is what you iterate on |
| `pyproject.toml` | Python deps |

## What to improve in solve.py

The starting code does single-turn: ask Gemini once, execute the plan. To score higher:

1. **Multi-turn reasoning** — send API responses back to Gemini so it can adjust
2. **Better system prompt** — include more Tripletex API details, field names, required params
3. **File handling** — some tasks include PDFs/images, make sure Gemini sees them
4. **Error recovery** — if a 4xx happens, ask Gemini to fix the call
5. **Minimize API calls** — efficiency bonus rewards fewer calls + zero errors

## Scoring quick reference

- 30 task types, scored independently (best score per task kept)
- Correctness: field-by-field check, normalized to 0–1
- Tier multiplier: Tier 1 (×1), Tier 2 (×2), Tier 3 (×3)
- Efficiency bonus: up to 2× on perfect scores (fewer calls + no errors = higher bonus)
- Max score per task: 6.0 (perfect Tier 3 + best efficiency)
- Rate limit: 5 submissions per task per day

## Useful links

- Competition submit: https://app.ainm.no/submit/tripletex
- Tripletex API docs: https://kkpqfuj-amager.tripletex.dev/v2-docs/
