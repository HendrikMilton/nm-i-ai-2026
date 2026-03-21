#!/bin/bash
# Auto-submit script for NM I AI — runs continuously.
# Submits predictions, waits, then tries again.
# If no active round, waits and retries.
#
# Usage:
#   ./auto_submit.sh              # default interval: 1 hour
#   ./auto_submit.sh 1800         # custom interval: 30 minutes

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs/auto_submit"
mkdir -p "$LOG_DIR"

INTERVAL="${1:-3600}"
echo "Auto-submit loop started (interval: ${INTERVAL}s)"

while true; do
    TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
    LOG_FILE="$LOG_DIR/$TIMESTAMP.log"

    echo "=== Auto-submit started at $(date) ===" | tee -a "$LOG_FILE"

    cd "$SCRIPT_DIR/astar" || {
        echo "ERROR: Could not cd to $SCRIPT_DIR/astar" | tee -a "$LOG_FILE"
        echo "Sleeping ${INTERVAL}s until next run..."
        sleep "$INTERVAL"
        continue
    }

    python3 run.py 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}

    echo "" | tee -a "$LOG_FILE"
    echo "=== Finished at $(date) (exit code: $EXIT_CODE) ===" | tee -a "$LOG_FILE"
    echo "Log saved to: $LOG_FILE"

    # Keep only last 48 log files
    ls -t "$LOG_DIR"/*.log 2>/dev/null | tail -n +49 | xargs rm -f 2>/dev/null

    echo "Sleeping ${INTERVAL}s until next run..."
    REMAINING="$INTERVAL"
    while [ "$REMAINING" -gt 300 ]; do
        sleep 300
        REMAINING=$((REMAINING - 300))
        echo "  [heartbeat] $(date) — ${REMAINING}s remaining" | tee -a "$LOG_FILE"
    done
    [ "$REMAINING" -gt 0 ] && sleep "$REMAINING"
done
