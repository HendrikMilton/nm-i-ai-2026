#!/bin/bash
# Spins up a RunPod GPU pod, sets it up for the competition, and tests endpoints.
# Usage: ./setup-runpod.sh [gpu-type]
# Example: ./setup-runpod.sh "NVIDIA RTX A6000"
# Default: NVIDIA RTX A6000 (48GB VRAM, $0.33/hr)

set -euo pipefail

GPU_TYPE="${1:-NVIDIA A40}"
POD_NAME="nm-ai-2026"
IMAGE="runpod/pytorch:1.0.3-cu1290-torch291-ubuntu2204"
SECURE_CLOUD="--secureCloud"
# Convert SSH git URL to HTTPS with token for cloning on remote (no SSH keys there)
GH_TOKEN="$(gh auth token 2>/dev/null || echo "")"
REPO_HTTPS="$(git -C "$(dirname "$0")/.." remote get-url origin 2>/dev/null | sed 's|git@github.com:|https://github.com/|' || echo "https://github.com/YOUR_ORG/agentic-avengers-nm-ai.git")"
if [ -n "$GH_TOKEN" ]; then
    REPO_URL="$(echo "$REPO_HTTPS" | sed "s|https://github.com/|https://${GH_TOKEN}@github.com/|")"
else
    REPO_URL="$REPO_HTTPS"
fi
RUNPOD_API_KEY=$(grep -oP 'apikey\s*=\s*"\K[^"]+' ~/.runpod/config.toml 2>/dev/null || echo "")
SSH_PUBKEY=$(cat ~/.ssh/id_ed25519.pub 2>/dev/null || echo "")

if [ -z "$RUNPOD_API_KEY" ]; then
    echo "ERROR: Could not read API key from ~/.runpod/config.toml"
    exit 1
fi

echo "=== NM i AI 2026 — RunPod Setup ==="
echo "GPU: $GPU_TYPE"
echo "Image: $IMAGE"
echo "Repo: $REPO_URL"
echo ""

# 1. Create pod (with PUBLIC_KEY for SSH access)
echo "[1/6] Creating pod..."
POD_OUTPUT=$(runpodctl create pod \
    --name "$POD_NAME" \
    --gpuType "$GPU_TYPE" \
    --gpuCount 1 \
    --imageName "$IMAGE" \
    --containerDiskSize 200 \
    --volumeSize 100 \
    $SECURE_CLOUD \
    --ports "4001/http,4002/http,4003/http,22/tcp" \
    --env "PUBLIC_KEY=$SSH_PUBKEY" \
    2>&1)

echo "$POD_OUTPUT"
POD_ID=$(echo "$POD_OUTPUT" | grep -oP 'pod "\K[^"]+' || true)

if [ -z "$POD_ID" ]; then
    echo "ERROR: Could not extract pod ID. Output was:"
    echo "$POD_OUTPUT"
    exit 1
fi

echo "Pod ID: $POD_ID"
echo ""

# 2. Wait for pod to be ready, polling logs for progress/errors
echo "[2/6] Waiting for pod to be ready (polling logs)..."
SEEN_LINES=0
for i in $(seq 1 90); do
    # Check runtime first
    RUNTIME=$(curl -s -H "Content-Type: application/json" \
        -H "Authorization: Bearer $RUNPOD_API_KEY" \
        --data "{\"query\":\"query { pod(input: {podId: \\\"$POD_ID\\\"}) { runtime { uptimeInSeconds ports { ip isIpPublic privatePort publicPort type } } } }\"}" \
        https://api.runpod.io/graphql 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['pod']['runtime'])" 2>/dev/null || echo "None")

    if [ "$RUNTIME" != "None" ] && [ "$RUNTIME" != "null" ]; then
        echo "Pod runtime is up!"
        break
    fi

    # Poll system logs for progress
    LOGS=$(curl -s "https://hapi.runpod.net/v1/pod/${POD_ID}/logs" \
        -H "Authorization: Bearer $RUNPOD_API_KEY" \
        -H "content-type: application/json" 2>/dev/null)

    # Show new log lines
    NEW_LINES=$(echo "$LOGS" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    system=d.get('system') or []
    for line in system[$SEEN_LINES:]:
        print('  ' + line)
    print('__COUNT__' + str(len(system)))
except: pass
" 2>/dev/null || true)

    # Print new lines (excluding the count marker)
    echo "$NEW_LINES" | grep -v "^__COUNT__" | grep -v "^$" || true

    # Update seen count
    COUNT=$(echo "$NEW_LINES" | grep -oP '__COUNT__\K\d+' || echo "$SEEN_LINES")
    SEEN_LINES=$COUNT

    # Check for fatal errors in logs
    if echo "$LOGS" | grep -q "error pulling image\|manifest unknown"; then
        echo ""
        echo "ERROR: Image pull failed! Check image name: $IMAGE"
        echo "Removing broken pod..."
        runpodctl remove pod "$POD_ID" 2>&1 || true
        exit 1
    fi

    sleep 10
done

# 3. Get connection info
echo ""
echo "[3/6] Getting connection info..."
POD_INFO=$(curl -s -H "Content-Type: application/json" \
    -H "Authorization: Bearer $RUNPOD_API_KEY" \
    --data "{\"query\":\"query { pod(input: {podId: \\\"$POD_ID\\\"}) { runtime { ports { ip isIpPublic privatePort publicPort type } } } }\"}" \
    https://api.runpod.io/graphql 2>/dev/null)

SSH_IP=$(echo "$POD_INFO" | python3 -c "
import sys,json
d=json.load(sys.stdin)
ports=d['data']['pod']['runtime']['ports']
for p in ports:
    if p['privatePort']==22:
        print(p['ip'])
        break
" 2>/dev/null || echo "")

SSH_PORT=$(echo "$POD_INFO" | python3 -c "
import sys,json
d=json.load(sys.stdin)
ports=d['data']['pod']['runtime']['ports']
for p in ports:
    if p['privatePort']==22:
        print(p['publicPort'])
        break
" 2>/dev/null || echo "")

# Also extract the pod SSH proxy hostname (works more reliably than direct TCP)
POD_HOST_ID=$(curl -s -H "Content-Type: application/json" \
    -H "Authorization: Bearer $RUNPOD_API_KEY" \
    --data "{\"query\":\"query { pod(input: {podId: \\\"$POD_ID\\\"}) { machine { podHostId } } }\"}" \
    https://api.runpod.io/graphql 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(d['data']['pod']['machine']['podHostId'])
" 2>/dev/null || echo "")

echo "SSH (proxy):  ssh -i ~/.ssh/id_ed25519 ${POD_ID}-${POD_HOST_ID##*-}@ssh.runpod.io"
echo "SSH (direct): ssh -i ~/.ssh/id_ed25519 root@${SSH_IP} -p ${SSH_PORT}"

# 4. Wait for SSH to be ready, then set up
echo ""
echo "[4/6] Waiting for SSH and setting up pod..."
SSH_READY=false
for attempt in $(seq 1 12); do
    if ssh -T -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i ~/.ssh/id_ed25519 root@${SSH_IP} -p ${SSH_PORT} "echo ok" 2>/dev/null | grep -q "ok"; then
        SSH_READY=true
        break
    fi
    echo "  SSH not ready yet... ($attempt/12)"
    sleep 10
done

if [ "$SSH_READY" = false ]; then
    echo "WARNING: Could not connect via direct SSH."
    echo "Try manually: ssh -i ~/.ssh/id_ed25519 root@${SSH_IP} -p ${SSH_PORT}"
    echo "Or proxy:     ssh -i ~/.ssh/id_ed25519 ${POD_ID}-${POD_HOST_ID##*-}@ssh.runpod.io"
    echo ""
    echo "Once connected, run this inside the pod:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo "  cd /workspace && git clone $REPO_URL repo && cd repo/hendrik"
    echo "  for n in 1 2 3; do cd /workspace/repo/hendrik/challenge\$n && uv sync; done"
    echo ""
else
    SSH_CMD="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -i ~/.ssh/id_ed25519 root@${SSH_IP} -p ${SSH_PORT}"

    $SSH_CMD bash -s -- "$REPO_URL" <<'SETUP_EOF'
set -e
REPO_URL="$1"
export PATH="$HOME/.local/bin:$PATH"

echo "--- GPU ---"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo "--- Installing uv ---"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "--- Creating non-root user (for claude --dangerously-skip-permissions) ---"
id researcher 2>/dev/null || useradd -m -s /bin/bash researcher
usermod -aG sudo researcher
chown -R researcher:researcher /workspace

echo "--- Installing Claude Code (as researcher) ---"
su - researcher -c 'curl -fsSL https://claude.ai/install.sh | sh' 2>/dev/null || echo "Claude Code install skipped"

echo "--- Installing uv (as researcher) ---"
su - researcher -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' 2>/dev/null || true

echo "--- Cloning repo ---"
cd /workspace
if [ -d repo ]; then cd repo && git pull; else git clone "$REPO_URL" repo && cd repo; fi

echo "--- Installing deps for all challenges ---"
for n in 1 2 3; do
    echo "  challenge$n..."
    cd /workspace/repo/hendrik/challenge$n
    uv sync 2>/dev/null || true
done

echo "--- Starting all 3 services ---"
for n in 1 2 3; do
    port=$((4000 + n))
    cd /workspace/repo/hendrik/challenge$n
    nohup uv run uvicorn main:app --host 0.0.0.0 --port $port > /tmp/challenge${n}.log 2>&1 &
    echo "  challenge$n on port $port (pid $!)"
done

sleep 3
echo "--- Testing endpoints ---"
for n in 1 2 3; do
    port=$((4000 + n))
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/ 2>/dev/null || echo "FAIL")
    echo "  challenge$n (port $port): $STATUS"
done

echo ""
echo "=== SETUP COMPLETE ==="
SETUP_EOF
fi

# 5. Get public URLs
echo ""
echo "[5/6] Public endpoints:"
echo "$POD_INFO" | python3 -c "
import sys,json
d=json.load(sys.stdin)
ports=d['data']['pod']['runtime']['ports']
for p in ports:
    if p['privatePort'] in [4001,4002,4003]:
        print(f\"  Challenge {p['privatePort']-4000}: https://${POD_ID}-{p['privatePort']}.proxy.runpod.net/predict\")
" 2>/dev/null || echo "  Could not determine public URLs. Check RunPod console."

# 6. Summary
echo ""
echo "[6/6] === READY ==="
echo "Pod ID:  $POD_ID"
echo "SSH (proxy):  ssh -i ~/.ssh/id_ed25519 ${POD_ID}-${POD_HOST_ID##*-}@ssh.runpod.io"
echo "SSH (direct): ssh -i ~/.ssh/id_ed25519 root@${SSH_IP} -p ${SSH_PORT}"
echo "Stop:    runpodctl stop pod $POD_ID"
echo "Remove:  runpodctl remove pod $POD_ID"
echo ""
echo "HTTP endpoints:"
echo "  Challenge 1: https://${POD_ID}-4001.proxy.runpod.net/predict"
echo "  Challenge 2: https://${POD_ID}-4002.proxy.runpod.net/predict"
echo "  Challenge 3: https://${POD_ID}-4003.proxy.runpod.net/predict"

# Save endpoints to file for easy copy-paste during competition submission
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cat > "${SCRIPT_DIR}/endpoints.txt" <<ENDPOINTS
=== NM i AI 2026 — Submit these URLs to competition ===
Pod ID: ${POD_ID}

Challenge 1: https://${POD_ID}-4001.proxy.runpod.net/predict
Challenge 2: https://${POD_ID}-4002.proxy.runpod.net/predict
Challenge 3: https://${POD_ID}-4003.proxy.runpod.net/predict

Health checks (GET):
  https://${POD_ID}-4001.proxy.runpod.net/
  https://${POD_ID}-4002.proxy.runpod.net/
  https://${POD_ID}-4003.proxy.runpod.net/

SSH: ssh -i ~/.ssh/id_ed25519 root@${SSH_IP} -p ${SSH_PORT}
ENDPOINTS
echo ""
echo "Endpoints saved to ${SCRIPT_DIR}/endpoints.txt"
