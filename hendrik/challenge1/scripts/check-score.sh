#!/bin/bash
# Check our team's leaderboard position
# Usage: ACCESS_TOKEN=xxx bash scripts/check-score.sh

if [ -z "$ACCESS_TOKEN" ]; then
    # Try loading from .env
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    ENV_FILE="$SCRIPT_DIR/../.env"
    if [ -f "$ENV_FILE" ]; then
        export $(grep -v '^#' "$ENV_FILE" | xargs)
    fi
fi

if [ -z "$ACCESS_TOKEN" ]; then
    echo "ERROR: ACCESS_TOKEN not found in env or .env"
    exit 1
fi

curl -s "https://api.ainm.no/tripletex/leaderboard" \
  -H 'accept: */*' \
  -b "access_token=${ACCESS_TOKEN}" | jq '.[] | select(.team_slug == "agentic-avengers") | {rank, total_score, tasks_touched, total_submissions, tier1_score, tier2_score, tier3_score}'
