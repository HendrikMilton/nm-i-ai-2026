#!/bin/bash
# Run tests against all 4 models in parallel
# Each model gets its own port and log file

TRIPLETEX_URL="https://kkpqfuj-amager.tripletex.dev/v2"
TOKEN="REDACTED_TOKEN"

MODELS=("gemini-2.5-flash" "gemini-2.5-pro" "claude-sonnet-4-6" "claude-opus-4-6")
PORTS=(4001 4002 4003 4004)

# Clean up old logs and processes
for port in "${PORTS[@]}"; do
    lsof -ti:$port 2>/dev/null | xargs kill -9 2>/dev/null
done
rm -f src/logs-*.log

# Start all 4 servers
for i in "${!MODELS[@]}"; do
    model="${MODELS[$i]}"
    port="${PORTS[$i]}"
    echo "Starting $model on :$port"
    MODEL=$model PORT=$port bun run src/index.ts &
done

sleep 3
echo ""
echo "All servers started. Running tests..."
echo ""

# Run tests for each model
run_tests() {
    local model=$1
    local port=$2
    local outfile="test-results-${model}.txt"

    echo "========== $model (port $port) ==========" > "$outfile"

    local total=0 passed=0 failed=0

    for dir in easy medium hard multilingual; do
        [ -d "test-tasks/$dir" ] || continue
        echo "" >> "$outfile"
        echo "--- $dir ---" >> "$outfile"

        for f in test-tasks/$dir/*.md; do
            [ -f "$f" ] || continue
            name=$(basename "$f" .md)
            prompt=$(cat "$f")
            total=$((total + 1))

            start_ts=$(date +%s%N)
            result=$(curl -s --max-time 300 -X POST "http://localhost:$port/solve" \
                -H "Content-Type: application/json" \
                -d "$(jq -n \
                    --arg prompt "$prompt" \
                    --arg base_url "$TRIPLETEX_URL" \
                    --arg token "$TOKEN" \
                    '{prompt: $prompt, files: [], tripletex_credentials: {base_url: $base_url, session_token: $token}}'
                )")
            end_ts=$(date +%s%N)
            elapsed=$(( (end_ts - start_ts) / 1000000 ))

            status=$(echo "$result" | jq -r '.status // "error"')
            if [ "$status" = "completed" ]; then
                passed=$((passed + 1))
                echo "  ✓ $dir/$name (${elapsed}ms)" >> "$outfile"
            else
                failed=$((failed + 1))
                echo "  ✗ $dir/$name FAILED (${elapsed}ms)" >> "$outfile"
            fi
        done
    done

    echo "" >> "$outfile"
    echo "TOTAL: $total | PASSED: $passed | FAILED: $failed" >> "$outfile"
    echo "[$model] Done: $passed/$total passed"
}

# Run all 4 test suites in parallel
for i in "${!MODELS[@]}"; do
    run_tests "${MODELS[$i]}" "${PORTS[$i]}" &
done

# Wait for all tests to finish
wait

echo ""
echo "=========================================="
echo "RESULTS SUMMARY"
echo "=========================================="
for model in "${MODELS[@]}"; do
    echo ""
    cat "test-results-${model}.txt"
done

# Kill servers
for port in "${PORTS[@]}"; do
    lsof -ti:$port 2>/dev/null | xargs kill -9 2>/dev/null
done
echo ""
echo "All servers stopped."
