#!/bin/bash
# Tears down RunPod pod(s).
# Usage: ./teardown-runpod.sh [pod-id]     — remove specific pod
#        ./teardown-runpod.sh --all         — remove all pods
#        ./teardown-runpod.sh --stop [id]   — stop (not delete) a pod
# If no pod-id given, lists pods and asks.

set -euo pipefail

echo "=== Current pods ==="
runpodctl get pod 2>&1
echo ""

ACTION="remove"
POD_ID="${1:-}"

if [ "$POD_ID" = "--stop" ]; then
    ACTION="stop"
    POD_ID="${2:-}"
fi

if [ "$POD_ID" = "--all" ]; then
    PODS=$(runpodctl get pod 2>&1 | tail -n +2 | awk '{print $1}')
    if [ -z "$PODS" ]; then
        echo "No pods to remove."
        exit 0
    fi
    echo "Will remove ALL pods:"
    echo "$PODS"
    read -p "Are you sure? (y/N) " CONFIRM
    if [ "$CONFIRM" != "y" ]; then
        echo "Aborted."
        exit 0
    fi
    for id in $PODS; do
        echo "Removing $id..."
        runpodctl remove pod "$id" 2>&1 || true
    done
    echo "All pods removed."
    exit 0
fi

if [ -z "$POD_ID" ]; then
    read -p "Enter pod ID to $ACTION: " POD_ID
fi

if [ -z "$POD_ID" ]; then
    echo "No pod ID given, aborting."
    exit 1
fi

read -p "${ACTION^} pod $POD_ID? (y/N) " CONFIRM
if [ "$CONFIRM" != "y" ]; then
    echo "Aborted."
    exit 0
fi

echo "${ACTION^}ing pod $POD_ID..."
runpodctl $ACTION pod "$POD_ID"
echo "Done."
