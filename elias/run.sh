docker build -t claude-sandbox .

docker run -it --rm \
  -v "$(pwd):/workspace" \
  -v "$HOME/.claude:/home/claude/.claude" \
  -p 5173:5173 \
  claude-sandbox
