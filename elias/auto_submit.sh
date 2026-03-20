#!/bin/bash
# Auto-submit script for NM I AI — runs every hour via cron.
# First run uses query budget; subsequent runs reuse cached queries.
#
# Setup cron (every hour):
#   crontab -e
#   0 * * * * /path/to/nmiai/elias/auto_submit.sh
#
# Or run in a loop:
#   ./auto_submit.sh --loop

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs/auto_submit"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
LOG_FILE="$LOG_DIR/$TIMESTAMP.log"

run_once() {
    echo "=== Auto-submit started at $(date) ===" | tee -a "$LOG_FILE"

    cd "$SCRIPT_DIR/astar" || {
        echo "ERROR: Could not cd to $SCRIPT_DIR/astar" | tee -a "$LOG_FILE"
        return 1
    }

    python3 run.py 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}

    echo "" | tee -a "$LOG_FILE"
    echo "=== Finished at $(date) (exit code: $EXIT_CODE) ===" | tee -a "$LOG_FILE"
    echo "Log saved to: $LOG_FILE"

    # Keep only last 48 log files
    ls -t "$LOG_DIR"/*.log 2>/dev/null | tail -n +49 | xargs rm -f 2>/dev/null

    return $EXIT_CODE
}

if [ "$1" = "--loop" ]; then
    INTERVAL="${2:-3600}"  # default 1 hour
    echo "Running in loop mode (interval: ${INTERVAL}s)"
    while true; do
        TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
        LOG_FILE="$LOG_DIR/$TIMESTAMP.log"
        run_once
        echo "Sleeping ${INTERVAL}s until next run..."
        sleep "$INTERVAL"
    done
else
    run_once
fi
