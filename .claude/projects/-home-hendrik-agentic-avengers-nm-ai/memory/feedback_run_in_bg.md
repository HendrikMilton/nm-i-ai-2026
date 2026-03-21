---
name: Always run long commands in background
description: User strongly prefers long-running commands (training, etc) to be run with run_in_background=true, never blocking
type: feedback
---

Always use `run_in_background: true` for long-running commands like model training. Never block the conversation.

**Why:** User got frustrated multiple times when training was run in foreground or when polling with sleep. They want to keep the conversation responsive.

**How to apply:** Any command expected to take more than ~30 seconds should use `run_in_background`. Don't poll with `sleep` — just wait for the task notification. When user asks for CLI commands (like tmux), give them the commands as text instead of running them.
