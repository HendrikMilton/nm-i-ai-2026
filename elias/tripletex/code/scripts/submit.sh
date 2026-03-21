#!/bin/bash
# Submit to competition. Requires ACCESS_TOKEN and ENDPOINT_URL env vars.
# Usage: ACCESS_TOKEN=xxx ENDPOINT_URL=https://xxx.trycloudflare.com/solve bash scripts/submit.sh

TASK_ID="cccccccc-cccc-cccc-cccc-cccccccccccc"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

if [ -z "$ACCESS_TOKEN" ]; then
    echo "ERROR: ACCESS_TOKEN not found in env or .env"
    exit 1
fi

if [ -z "$ENDPOINT_URL" ]; then
    echo "ERROR: ENDPOINT_URL not found in env or .env"
    exit 1
fi

# Check for in-progress submissions
evaluating=$(curl -s "https://api.ainm.no/tripletex/my/submissions" \
  -H 'accept: */*' \
  -b "access_token=${ACCESS_TOKEN}" | jq '[.[] | select(.status == "evaluating" or .status == "pending" or .status == "running")] | length')

if [ "$evaluating" -gt 0 ] 2>/dev/null; then
    echo "WAIT: $evaluating submission(s) still in progress"
    exit 2
fi

response=$(curl -s "https://api.ainm.no/tasks/${TASK_ID}/submissions" \
  -H 'content-type: application/json' \
  -b "access_token=${ACCESS_TOKEN}" \
  --data-raw "{\"endpoint_url\":\"${ENDPOINT_URL}\",\"endpoint_api_key\":null}")

echo "$response"
