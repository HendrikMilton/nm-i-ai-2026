#!/bin/sh
set -e

# Link pre-installed node_modules into the mounted frontend directory
if [ -d /workspace/frontend ] && [ ! -d /workspace/frontend/node_modules ]; then
  ln -s /opt/frontend/node_modules /workspace/frontend/node_modules
fi

# Start Vite dev server in the background
cd /workspace/frontend && npx vite --host 0.0.0.0 --port 5173 &

cd /workspace

# Setup MCP
claude mcp add --transport http nmiai https://mcp-docs.ainm.no/mcp 2>/dev/null

exec claude --dangerously-skip-permissions
