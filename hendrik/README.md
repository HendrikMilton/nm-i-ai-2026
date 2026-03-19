# NM i AI 2026 — Agentic Avengers

## Structure
```
hendrik/
├── shared/utils.py          # base64/image helpers
├── challenge1/              # port 4001
├── challenge2/              # port 4002
├── challenge3/              # port 4003
│   ├── main.py              # FastAPI (don't touch)
│   ├── solve.py             # ALL logic here (autoresearch iterates on this)
│   ├── program.md           # autoresearch instructions (fill after kickoff)
│   ├── Dockerfile
│   └── pyproject.toml
├── docker-compose.yml
└── autoresearch.sh          # overnight iteration launcher
```

## Quick Start (local)
```bash
cd challenge1 && uv sync && uv run python main.py
```

## RunPod Deployment
1. Create a GPU pod (A40 48GB or A100 80GB recommended)
2. SSH in: `runpodctl ssh <pod-id>`
3. Clone repo, cd into hendrik/
4. `docker compose up -d`
5. Your endpoints: `http://<pod-ip>:4001/predict`, `:4002`, `:4003`

Alternatively without Docker:
```bash
# Terminal 1
cd challenge1 && uv sync && uv run uvicorn main:app --host 0.0.0.0 --port 4001
# Terminal 2
cd challenge2 && uv sync && uv run uvicorn main:app --host 0.0.0.0 --port 4002
# Terminal 3
cd challenge3 && uv sync && uv run uvicorn main:app --host 0.0.0.0 --port 4003
```

## Autoresearch (overnight AI iteration)
1. Fill in `challengeN/program.md` with task details + evaluation command
2. Run: `./autoresearch.sh 1` (one terminal per challenge)
3. Sleep. Wake up to git log full of experiments.

## Team Allocation
| Person | Assignment |
|--------|-----------|
| Hendrik (senior) | Architecture + hardest challenge |
| Junior 1 | CV challenge |
| Junior 2 | Classification/NLP challenge |
| Vibe coder | Infra, deployment, monitoring |
