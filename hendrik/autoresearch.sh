#!/bin/bash
# Usage: ./autoresearch.sh <challenge_number>
# Example: ./autoresearch.sh 1
#
# Starts a Claude Code session that autonomously iterates on solve.py
# for the given challenge. Run one per challenge in separate terminals.

set -e

CHALLENGE=${1:?Usage: ./autoresearch.sh <1|2|3>}
DIR="$(cd "$(dirname "$0")" && pwd)/challenge${CHALLENGE}"

if [ ! -f "$DIR/solve.py" ]; then
    echo "Error: $DIR/solve.py not found"
    exit 1
fi

if [ ! -f "$DIR/program.md" ]; then
    echo "Error: $DIR/program.md not found — fill it in first!"
    exit 1
fi

echo "Starting autoresearch for challenge ${CHALLENGE} in ${DIR}"
echo "Press Ctrl+C to stop."

cd "$DIR"
claude --print "Read program.md and begin the autoresearch loop. Work in $(pwd). Never stop iterating. Assume I am asleep."
