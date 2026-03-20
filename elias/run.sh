REPO_ROOT=$(git rev-parse --show-toplevel)

docker build -t claude-sandbox .

docker run -it --rm \
  -v "$REPO_ROOT:/workspace" \
  -v "$HOME/.claude:/home/claude/.claude" \
  -w /workspace/elias \
  -p 5173:5173 \
  claude-sandbox
