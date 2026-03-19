#!/bin/bash
# Tears down the Tripletex VM.
set -euo pipefail

PROJECT="ai-nm26osl-1713"
VM_NAME="tripletex-agent"
ZONE="europe-west4-a"

echo "Deleting VM $VM_NAME..."
gcloud compute instances delete "$VM_NAME" \
    --zone="$ZONE" \
    --project="$PROJECT" \
    --quiet

echo "Done."
