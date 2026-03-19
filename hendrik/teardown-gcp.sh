#!/bin/bash
# Tears down GCP VM and firewall rule.
# Usage: ./teardown-gcp.sh [--stop]     — stop VM (keeps disk, no GPU cost)
#        ./teardown-gcp.sh [--delete]   — delete VM entirely
#        ./teardown-gcp.sh              — lists VM and asks

set -euo pipefail

export PATH="/home/hendrik/Documents/agentic-avengers-nm-ai/google-cloud-sdk/bin:$PATH"

PROJECT="ai-nm26osl-1713"
VM_NAME="nm-ai-2026"
ZONE="europe-west1-b"

ACTION="${1:-}"

echo "=== Current VM ==="
gcloud compute instances list --project="$PROJECT" --filter="name=$VM_NAME" 2>&1
echo ""

if [ "$ACTION" = "--stop" ]; then
    echo "Stopping VM $VM_NAME (keeps disk, saves money)..."
    gcloud compute instances stop "$VM_NAME" --zone="$ZONE" --project="$PROJECT"
    echo "Done. Restart with: gcloud compute instances start $VM_NAME --zone=$ZONE --project=$PROJECT"
    exit 0
fi

if [ "$ACTION" = "--delete" ]; then
    read -p "Delete VM $VM_NAME and all data? (y/N) " CONFIRM
    if [ "$CONFIRM" != "y" ]; then
        echo "Aborted."
        exit 0
    fi
    echo "Deleting VM $VM_NAME..."
    gcloud compute instances delete "$VM_NAME" --zone="$ZONE" --project="$PROJECT" --quiet
    echo "Deleting firewall rule..."
    gcloud compute firewall-rules delete nm-ai-allow-challenges --project="$PROJECT" --quiet 2>/dev/null || true
    echo "Done."
    exit 0
fi

echo "Usage:"
echo "  ./teardown-gcp.sh --stop    — stop VM (keeps disk, no GPU cost)"
echo "  ./teardown-gcp.sh --delete  — delete VM and all data"
