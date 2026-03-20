#!/bin/bash
# Run test tasks against the server
#
# Usage:
#   bash scripts/run-tests.sh                          # all tasks, localhost
#   bash scripts/run-tests.sh easy                     # just easy tier
#   bash scripts/run-tests.sh easy/01-create-employee  # single task
#   bash scripts/run-tests.sh attachments/1-pdf        # attachment test
#   URL=https://xxx.trycloudflare.com bash scripts/run-tests.sh  # public URL

BASE_URL="${URL:-http://localhost:${PORT:-4001}}"
TRIPLETEX_URL="https://kkpqfuj-amager.tripletex.dev/v2"
TOKEN="REDACTED_TOKEN"
FILTER="${1:-}"

# Generate a short unique suffix for this run
RUN_ID=$(date +%H%M%S)
echo "Run ID: $RUN_ID | Server: $BASE_URL | Filter: ${FILTER:-all}"

# Substitution map
sub_prompt() {
    local prompt="$1"
    prompt="${prompt//Petter Svendsen/Petter Svendsen${RUN_ID}}"
    prompt="${prompt//petter.svendsen77/petter.svendsen${RUN_ID}}"
    prompt="${prompt//Havfront Digital AS/Havfront Digital ${RUN_ID} AS}"
    prompt="${prompt//post@havfrontdigital.no/post${RUN_ID}@havfrontdigital.no}"
    prompt="${prompt//Prosjektledelse Premium/Prosjektledelse Premium ${RUN_ID}}"
    prompt="${prompt//PLP-500/PLP-${RUN_ID}}"
    prompt="${prompt//Forretningsutvikling/Forretningsutvikling${RUN_ID}}"
    prompt="${prompt//Skyløsninger Nord AS/Skyløsninger Nord ${RUN_ID} AS}"
    prompt="${prompt//salg@skylosninger.no/salg${RUN_ID}@skylosninger.no}"
    prompt="${prompt//Arktisk Rådgivning AS/Arktisk Rådgivning ${RUN_ID} AS}"
    prompt="${prompt//Polarlys Industri AS/Polarlys Industri ${RUN_ID} AS}"
    prompt="${prompt//Vestland Energi AS/Vestland Energi ${RUN_ID} AS}"
    prompt="${prompt//post@vestlandenergi.no/post${RUN_ID}@vestlandenergi.no}"
    prompt="${prompt//Energirådgivning/Energirådgivning${RUN_ID}}"
    prompt="${prompt//Konferanse Trondheim 2026/Konferanse Trondheim ${RUN_ID}}"
    prompt="${prompt//Mobilapp Utvikling 2026/Mobilapp Utvikling ${RUN_ID}}"
    prompt="${prompt//faktura@havfrontdigital.no/faktura${RUN_ID}@havfrontdigital.no}"
    prompt="${prompt//Thomas Blake/Thomas Blake${RUN_ID}}"
    prompt="${prompt//thomas.blake42/thomas.blake${RUN_ID}}"
    prompt="${prompt//Cumbre Soluciones SL/Cumbre Soluciones ${RUN_ID} SL}"
    prompt="${prompt//info@cumbresoluciones.es/info${RUN_ID}@cumbresoluciones.es}"
    prompt="${prompt//Systemintegration/Systemintegration${RUN_ID}}"
    prompt="${prompt//Matériel Informatique Lyon SARL/Matériel Informatique ${RUN_ID} SARL}"
    prompt="${prompt//commandes@matinfo-lyon.fr/commandes${RUN_ID}@matinfo-lyon.fr}"
    prompt="${prompt//Análise de Dados Avançada/Análise de Dados ${RUN_ID}}"
    prompt="${prompt//ADA-300/ADA-${RUN_ID}}"
    prompt="${prompt//Innovasjon/Innovasjon${RUN_ID}}"
    prompt="${prompt//Ingrid Moen/Ingrid Moen${RUN_ID}}"
    prompt="${prompt//ingrid.moen55/ingrid.moen${RUN_ID}}"
    echo "$prompt"
}

build_files_json() {
    local dir="$1"
    local files_json="[]"
    local has_files=false

    for attachment in "$dir"/*.pdf "$dir"/*.png "$dir"/*.jpg; do
        [ -f "$attachment" ] || continue
        has_files=true
        fname=$(basename "$attachment")
        b64=$(base64 -w0 "$attachment")
        case "$attachment" in
            *.pdf) mime="application/pdf" ;;
            *.png) mime="image/png" ;;
            *.jpg) mime="image/jpeg" ;;
        esac
        files_json=$(echo "$files_json" | jq --arg fn "$fname" --arg b64 "$b64" --arg mime "$mime" \
            '. + [{"filename": $fn, "content_base64": $b64, "mime_type": $mime}]')
    done

    echo "$files_json"
}

run_task() {
    local dir="$1"
    local prompt_file="$2"
    local name="$3"

    local raw_prompt
    raw_prompt=$(cat "$prompt_file")
    local prompt
    prompt=$(sub_prompt "$raw_prompt")
    local files_json
    files_json=$(build_files_json "$(dirname "$prompt_file")")
    local file_count
    file_count=$(echo "$files_json" | jq 'length')

    echo ""
    echo "--- $name ---"
    echo "$(date +%H:%M:%S) | Prompt: ${prompt:0:100}..."
    [ "$file_count" -gt 0 ] && echo "$(date +%H:%M:%S) | Files: $file_count attachment(s)"

    local start_ts end_ts elapsed result status
    start_ts=$(date +%s%N)
    result=$(curl -s --max-time 300 -X POST "$BASE_URL/solve" \
        -H "Content-Type: application/json" \
        -d "$(jq -n \
            --arg prompt "$prompt" \
            --arg base_url "$TRIPLETEX_URL" \
            --arg token "$TOKEN" \
            --argjson files "$files_json" \
            '{prompt: $prompt, files: $files, tripletex_credentials: {base_url: $base_url, session_token: $token}}'
        )")
    end_ts=$(date +%s%N)
    elapsed=$(( (end_ts - start_ts) / 1000000 ))

    status=$(echo "$result" | jq -r '.status // "error"')
    if [ "$status" = "completed" ]; then
        PASSED=$((PASSED + 1))
        echo "$(date +%H:%M:%S) | ✓ completed (${elapsed}ms)"
    else
        FAILED=$((FAILED + 1))
        echo "$(date +%H:%M:%S) | ✗ FAILED (${elapsed}ms): $result"
    fi
    TOTAL=$((TOTAL + 1))
}

TOTAL=0
PASSED=0
FAILED=0

# Single task mode: "easy/01-create-employee" or "attachments/1-pdf"
if [ -n "$FILTER" ] && [ -f "test-tasks/$FILTER/prompt.md" ]; then
    echo ""
    echo "========== $FILTER =========="
    run_task "$FILTER" "test-tasks/$FILTER/prompt.md" "$FILTER"
elif [ -n "$FILTER" ] && [ -f "test-tasks/$FILTER.md" ]; then
    dir=$(dirname "$FILTER")
    echo ""
    echo "========== $dir =========="
    run_task "$dir" "test-tasks/$FILTER.md" "$FILTER"
else
    # Run dirs matching filter (or all)
    for dir in easy medium hard multilingual attachments; do
        [ -d "test-tasks/$dir" ] || continue
        [ -n "$FILTER" ] && [[ "$dir" != "$FILTER"* ]] && continue

        echo ""
        echo "========== $dir =========="

        # Regular tasks (*.md in dir root)
        for f in test-tasks/$dir/*.md; do
            [ -f "$f" ] || continue
            name="$dir/$(basename "$f" .md)"
            run_task "$dir" "$f" "$name"
        done

        # Subdirectory tasks (attachments/1-pdf/prompt.md etc)
        for subdir in test-tasks/$dir/*/; do
            [ -f "$subdir/prompt.md" ] || continue
            name="$dir/$(basename "$subdir")"
            run_task "$(basename "$subdir")" "$subdir/prompt.md" "$name"
        done
    done
fi

echo ""
echo "=========================================="
echo "RUN_ID: $RUN_ID | TOTAL: $TOTAL | PASSED: $PASSED | FAILED: $FAILED"
echo "=========================================="
