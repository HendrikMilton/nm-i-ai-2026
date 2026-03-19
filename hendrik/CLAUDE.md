# NM i AI 2026 — Agentic Avengers

Competition: Norwegian AI Championship, 69-hour event (Mar 19–22, 2026).
Team: 4 people. Prize pool: 1M NOK.

## Structure

```
hendrik/
├── shared/utils.py          # base64/image helpers
├── challenge1/              # port 4001
├── challenge2/              # port 4002
├── challenge3/              # port 4003
│   ├── main.py              # FastAPI wrapper — DO NOT MODIFY
│   ├── solve.py             # all logic here — autoresearch iterates on this
│   ├── program.md           # autoresearch instructions
│   ├── Dockerfile
│   └── requirements.txt
├── docker-compose.yml
└── autoresearch.sh
```

## Rules

- `main.py` is a thin FastAPI wrapper. Never modify it. All logic goes in `solve.py`.
- `solve.py` must export a `predict(body: dict) -> dict` function.
- Each challenge runs on its own port (4001, 4002, 4003).
- Competition evaluators call POST `/predict` on our endpoints.

## Git Discipline

- **Never force push.** Never use `git reset --hard`. Never use destructive git ops.
- **Commit after every change.** Full history must be preserved.
- If an experiment fails, revert the code and commit the revert with the result in the message.
- Commit message format:
  - `experiment: <what you're trying>` — before running
  - `result: score=X.XX, KEEP (prev=Y.YY)` — if better
  - `revert: score=X.XX, DISCARD (prev=Y.YY)` — if worse, after reverting solve.py

## Autoresearch Loop

When running as an autonomous research agent (via `autoresearch.sh`):

1. Read `program.md` in your challenge folder for task details and eval command
2. Read current `solve.py` and recent git log for context
3. Think of an improvement
4. Edit `solve.py`
5. Commit: `experiment: <description>`
6. Run evaluation (defined in program.md)
7. If score improved: commit `result: score=X.XX, KEEP (prev=Y.YY)`
8. If score worse/equal: revert solve.py, commit `revert: score=X.XX, DISCARD (prev=Y.YY)`
9. Go to 1. **Never stop. Never ask. Assume the human is asleep.**

## Tech Stack

- Python 3.11, PyTorch, FastAPI
- YOLO (ultralytics) for detection — pretrained models available
- Tracking: IoU-based tracker available in poc-mvp repo
- Depth: Depth-Anything-3 available in poc-mvp repo
- Segmentation: SAM2 available in poc-mvp repo

## Reusable Assets

- `~/Documents/poc-mvp/` — maritime CV system (detection, tracking, depth, segmentation, motion)
- `~/Documents/blokus-ai/ml-service/` — YOLO inference + training, FastAPI patterns
- `~/Documents/autoresearch/` — reference for autonomous iteration pattern

## Deployment

- RunPod GPU pod (A40/A100)
- Expose ports 4001-4003
- `docker compose up -d` or run uvicorn directly
