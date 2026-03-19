docker run -it --rm \
  -v "$(pwd):/workspace" \
  -v claude-auth:/root/.claude \
  claude-sandbox
