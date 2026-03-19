#!/bin/bash
# Creates a lightweight VM for Tripletex challenge + cloudflared HTTPS tunnel.
# Usage: ./setup-vm.sh
set -euo pipefail

PROJECT="ai-nm26osl-1713"
VM_NAME="tripletex-agent"
ZONE="europe-west4-a"
MACHINE_TYPE="e2-medium"

REPO_URL="$(git -C "$(dirname "$0")/../.." remote get-url origin 2>/dev/null | sed 's|git@github.com:|https://github.com/|' || echo "")"
GH_TOKEN="$(gh auth token 2>/dev/null || echo "")"
if [ -n "$GH_TOKEN" ] && [ -n "$REPO_URL" ]; then
    REPO_URL="$(echo "$REPO_URL" | sed "s|https://github.com/|https://${GH_TOKEN}@github.com/|")"
fi

echo "=== Tripletex Agent VM Setup ==="
echo "VM:      $VM_NAME"
echo "Zone:    $ZONE"
echo "Machine: $MACHINE_TYPE (no GPU needed)"
echo ""

STARTUP_SCRIPT='#!/bin/bash
set -e

apt-get update -qq
apt-get install -y -qq python3-pip python3-venv curl

# Install cloudflared
curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
dpkg -i /tmp/cloudflared.deb

# Create dev user
id gabriel 2>/dev/null || useradd -m -s /bin/bash gabriel
usermod -aG sudo gabriel
echo "gabriel ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/gabriel

# Install uv for gabriel
su - gabriel -c "curl -LsSf https://astral.sh/uv/install.sh | sh" 2>/dev/null || true

# Clone repo
cd /opt
if [ -d repo ]; then cd repo && git pull; else git clone "'"$REPO_URL"'" repo && cd repo; fi
chown -R gabriel:gabriel /opt/repo

# Install deps
su - gabriel -c "cd /opt/repo/gabriel/tripletex_challenge_task && /home/gabriel/.local/bin/uv sync"

echo "Startup complete" > /tmp/setup-done
'

# 1. Create VM
echo "[1/4] Creating VM..."
gcloud compute instances create "$VM_NAME" \
    --project="$PROJECT" \
    --zone="$ZONE" \
    --machine-type="$MACHINE_TYPE" \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-balanced \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --scopes=cloud-platform \
    --tags="tripletex" \
    --metadata="startup-script=$STARTUP_SCRIPT" \
    2>&1

# 2. Wait for setup
echo ""
echo "[2/4] Waiting for VM startup script..."
for i in $(seq 1 30); do
    DONE=$(gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT" \
        --command="cat /tmp/setup-done 2>/dev/null" 2>/dev/null || echo "")
    if [ "$DONE" = "Startup complete" ]; then
        echo "VM setup complete!"
        break
    fi
    echo "  Waiting... ($i/30)"
    sleep 10
done

# 3. Start cloudflared tunnel
echo ""
echo "[3/4] Starting cloudflared tunnel..."
gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT" --command="
    nohup cloudflared tunnel --url http://localhost:8000 > /tmp/cloudflared.log 2>&1 &
    sleep 5
    grep -o 'https://[^ ]*\.trycloudflare\.com' /tmp/cloudflared.log | head -1
" 2>/dev/null

TUNNEL_URL=$(gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT" --command="
    grep -o 'https://[^ ]*\.trycloudflare\.com' /tmp/cloudflared.log | head -1
" 2>/dev/null)

# 4. Summary
echo ""
echo "[4/4] Done!"
echo ""
echo "=== READY ==="
echo "VM:       $VM_NAME"
echo "SSH:      gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT"
echo "Tunnel:   $TUNNEL_URL"
echo ""
echo "Submit this URL to competition: ${TUNNEL_URL}/solve"
echo ""
echo "=== Quick start (on the VM) ==="
echo "  cd /opt/repo/gabriel/tripletex_challenge_task"
echo "  uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
echo ""
echo "Edit solve.py, uvicorn auto-reloads. No redeploy needed."
