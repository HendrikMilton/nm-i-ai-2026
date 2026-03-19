# Tripletex AI Agent

AI agent that completes accounting tasks in Tripletex via Gemini 2.5 Pro + Tripletex API.

## First time setup

### 1. Install gcloud CLI (if you don't have it)

```bash
curl https://sdk.cloud.google.com | bash
exec -l $SHELL
gcloud init
# When prompted: select project ai-nm26osl-1713
```

### 2. Ask Hendrik to run `setup-vm.sh` (or run it yourself)

This creates the VM and cloudflared tunnel. It will print:
- An SSH command
- An HTTPS tunnel URL (submit this to competition)

### 3. SSH into the VM

```bash
gcloud compute ssh tripletex-agent --zone=europe-west4-a --project=ai-nm26osl-1713
```

### 4. Clone the repo and install deps

```bash
# On the VM:
cd /opt/repo/gabriel/tripletex_challenge_task  # if setup-vm.sh already cloned it

# OR clone manually:
cd ~
git clone https://github.com/<org>/<repo>.git
cd <repo>/gabriel/tripletex_challenge_task

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# Install deps
uv sync
```

### 5. Start the server

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Start the HTTPS tunnel (if not already running)

In a second SSH session (or use tmux):
```bash
cloudflared tunnel --url http://localhost:8000
```

This prints a URL like `https://something-random.trycloudflare.com`.
Submit `https://something-random.trycloudflare.com/solve` to the competition at https://app.ainm.no/submit/tripletex_challenge_task

## Development loop

```
1. Edit solve.py        ← all your logic goes here
2. Server auto-reloads  ← uvicorn --reload handles this
3. Test locally:        curl -X POST http://localhost:8000/solve -H "Content-Type: application/json" -d '{"prompt": "test", "files": [], "tripletex_credentials": {"base_url": "https://tx-proxy.ainm.no/v2", "session_token": "fake"}}'
4. Submit on competition platform → see score
5. Repeat
```

No redeploy, no Docker, no CI. Just edit and save.

## Using Claude Code on the VM

Install Claude Code:
```bash
# On the VM:
curl -fsSL https://claude.ai/install.sh | sh
```

Then just run it in the tripletex folder:
```bash
cd /opt/repo/gabriel/tripletex_challenge_task   # or wherever you cloned
claude
```

Claude Code can edit solve.py, run the server, test endpoints, and read the competition docs for you.

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
| `requirements.txt` | Python deps |
| `setup-vm.sh` | Creates the GCP VM (Hendrik runs this) |
| `teardown-vm.sh` | Deletes the VM |

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

- Competition submit: https://app.ainm.no/submit/tripletex_challenge_task
- Tripletex API docs: https://kkpqfuj-amager.tripletex.dev/v2-docs/
