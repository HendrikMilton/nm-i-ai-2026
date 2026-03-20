@Gabriel Diesen Tripletex task setup:

1. Install gcloud CLI: `curl https://sdk.cloud.google.com | bash`
2. Login with the shared GCP account (get creds at https://app.ainm.no/gcp): `gcloud auth login && gcloud config set project ai-nm26osl-1713`
3. SSH into the VM: `gcloud compute ssh tripletex-agent --zone=europe-west4-a --project=ai-nm26osl-1713`
4. Switch user: `sudo su - gabriel`
5. Pull latest code: `cd ~/agentic-avengers-nm-ai && git pull`
6. Login to Claude Code: `claude login`
7. Go to `~/agentic-avengers-nm-ai/gabriel/tripletex_challenge_task` — read the README there for the full dev workflow
8. Start the server: `uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
9. Run Claude Code in autonomous mode (in another tmux pane): `claude --dangerously-skip-permissions`
10. The scaffolded code is in `solve.py` — that's where all your logic goes. Server auto-reloads on save.
11. To switch LLM, change the `MODEL` variable in solve.py. Available: `gemini-2.5-pro`, `claude-sonnet-4-6`, `claude-opus-4-6`
12. Submit this URL to competition: `https://discuss-involves-medicare-gtk.trycloudflare.com/solve`
13. Verify the tunnel is working: `curl https://discuss-involves-medicare-gtk.trycloudflare.com/` — should return `{"status":"ok"}`
