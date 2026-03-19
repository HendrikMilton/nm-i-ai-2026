# NM i AI 2026 — Agentic Avengers

## Structure
```
hendrik/
├── shared/utils.py          # base64/image helpers
├── shared/replay.py         # offline replay of logged requests
├── challenge1/              # port 4001
├── challenge2/              # port 4002
├── challenge3/              # port 4003
│   ├── main.py              # FastAPI + request logging (don't touch)
│   ├── solve.py             # ALL logic here (autoresearch iterates on this)
│   ├── program.md           # autoresearch instructions (fill after kickoff)
│   ├── Dockerfile
│   └── pyproject.toml
├── docker-compose.yml
├── autoresearch.sh          # overnight iteration launcher
├── setup-gcp.sh             # spin up GCP GPU VM
├── teardown-gcp.sh          # stop/delete GCP VM
├── setup-runpod.sh          # spin up RunPod GPU (backup)
└── teardown-runpod.sh       # stop/delete RunPod pod (backup)
```

## Quick Start (local)
```bash
cd challenge1 && uv sync && uv run python main.py
```

## GCP Deployment (primary)
```bash
./setup-gcp.sh                                    # L4 (default, 24GB)
./setup-gcp.sh nvidia-tesla-a100 europe-west1-b   # A100 40GB (training + inference)
./setup-gcp.sh nvidia-l4 europe-west1-b           # L4 (fast inference, 24GB)

# SSH in
gcloud compute ssh nm-ai-2026 --zone=europe-west1-b --project=ai-nm26osl-1713

# Tear down
./teardown-gcp.sh --stop     # pause (no GPU cost, keeps disk)
./teardown-gcp.sh --delete   # nuke everything
```

## GPU Selection Guide
| GPU | VRAM | Best for | Notes |
|-----|------|----------|-------|
| **A100 40GB** | 40GB | Training + autoresearch overnight | Highest compute, good VRAM |
| **L4** | 24GB | Fast inference, serving predictions | Newer arch, lower latency |
| **T4** | 16GB | Budget inference only | Cheapest, limited VRAM |

Use A100 for autoresearch/training, L4 for serving if you want to split workloads.

## Model Storage
- **HuggingFace Hub**: `model.push_to_hub("your-name/model")` — easiest for sharing between machines
- **GCS bucket**: `gsutil cp model.pt gs://bucket/` — free with GCP credits
- **Git**: small models/configs directly in repo

## RunPod Deployment (backup)
```bash
./setup-runpod.sh                    # A40 secure cloud (default)
./teardown-runpod.sh --all           # remove all pods
```

## Autoresearch (overnight AI iteration)
1. Fill in `challengeN/program.md` with task details + evaluation command
2. Run: `./autoresearch.sh 1` (one terminal per challenge)
3. Sleep. Wake up to git log full of experiments.

## Offline Replay
Every `/predict` request is logged to `requests.jsonl`. Replay offline:
```bash
python shared/replay.py challenge1/requests.jsonl
```

## Team Allocation
| Person | Assignment |
|--------|-----------|
| Hendrik (senior) | Architecture + hardest challenge |
| Junior 1 | CV challenge |
| Junior 2 | Classification/NLP challenge |
| Vibe coder | Infra, deployment, monitoring |

## Claude Code on GPU VM (autonomous mode)
SSH into the VM and run:
```bash
# 1. Switch to non-root user (required for --dangerously-skip-permissions)
su - researcher

# 2. Install Claude Code (first time only)
curl -fsSL https://claude.ai/install.sh | bash
export PATH="$HOME/.claude/bin:$HOME/.local/bin:$PATH"

# 3. Login (opens a URL — paste it in your browser, then paste the code back)
claude login

# 4. Start Claude in autonomous mode
cd /opt/repo/hendrik
claude --dangerously-skip-permissions
```

## Test autoresearch
```bash
# As researcher user on the VM:
cd /opt
git clone https://github.com/karpathy/autoresearch.git
cd autoresearch
uv sync
uv run prepare.py  # downloads data + trains tokenizer (~2 min)

# Start autoresearch loop
claude --dangerously-skip-permissions
# Then tell Claude: "Read program.md and begin the autoresearch loop. Never stop iterating. Assume I am asleep."
```
