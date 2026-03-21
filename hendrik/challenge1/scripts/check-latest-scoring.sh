#!/bin/bash
# Show the latest submission scoring
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

if [ -z "$ACCESS_TOKEN" ]; then
    echo "ERROR: ACCESS_TOKEN not found"
    exit 1
fi

curl -s 'https://api.ainm.no/tripletex/my/submissions' \
  -b "access_token=${ACCESS_TOKEN}" | jq '.[0]'
