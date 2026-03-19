#!/bin/bash
# Spins up a GCP GPU VM, sets it up for the competition, and tests endpoints.
# Usage: ./setup-gcp.sh [gpu-type] [zone]
# Example: ./setup-gcp.sh nvidia-l4 europe-west1-b
# Default: nvidia-l4 in europe-west1-b

set -euo pipefail

export PATH="/home/hendrik/Documents/agentic-avengers-nm-ai/google-cloud-sdk/bin:$PATH"

GPU_TYPE="${1:-nvidia-l4}"
ZONE="${2:-europe-west4-a}"
PROJECT="ai-nm26osl-1713"
VM_NAME="nm-ai-2026"
MACHINE_TYPE="g2-standard-8"  # 8 vCPUs, 32GB RAM — good for L4
BOOT_DISK_SIZE="200"
IMAGE_FAMILY="pytorch-2-7-cu128-ubuntu-2204-nvidia-570"
IMAGE_PROJECT="deeplearning-platform-release"

# Adjust machine type based on GPU
case "$GPU_TYPE" in
    nvidia-tesla-a100|nvidia-a100-80gb)
        MACHINE_TYPE="a2-highgpu-1g"  # 12 vCPUs, 85GB RAM, 1x A100
        ;;
    nvidia-l4)
        MACHINE_TYPE="g2-standard-8"  # 8 vCPUs, 32GB RAM, 1x L4
        ;;
    nvidia-tesla-t4)
        MACHINE_TYPE="n1-standard-8"  # 8 vCPUs, 30GB RAM
        ;;
    nvidia-tesla-v100)
        MACHINE_TYPE="n1-standard-8"
        ;;
esac

REPO_URL="$(git -C "$(dirname "$0")/.." remote get-url origin 2>/dev/null | sed 's|git@github.com:|https://github.com/|' || echo "")"
GH_TOKEN="$(gh auth token 2>/dev/null || echo "")"
if [ -n "$GH_TOKEN" ] && [ -n "$REPO_URL" ]; then
    REPO_URL="$(echo "$REPO_URL" | sed "s|https://github.com/|https://${GH_TOKEN}@github.com/|")"
fi

echo "=== NM i AI 2026 — GCP Setup ==="
echo "GPU:     $GPU_TYPE"
echo "Zone:    $ZONE"
echo "Machine: $MACHINE_TYPE"
echo "Project: $PROJECT"
echo ""

# 1. Create VM with GPU
echo "[1/5] Creating VM..."
STARTUP_SCRIPT="#!/bin/bash
set -e

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH=\"/root/.local/bin:\$PATH\"

# Create non-root user for Claude Code
id researcher 2>/dev/null || useradd -m -s /bin/bash researcher
usermod -aG sudo researcher
echo 'researcher ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/researcher

# Install uv + claude for researcher
su - researcher -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' 2>/dev/null || true
su - researcher -c 'curl -fsSL https://claude.ai/install.sh | sh' 2>/dev/null || true

# Clone repo
cd /opt
if [ -d repo ]; then cd repo && git pull; else git clone '$REPO_URL' repo && cd repo; fi
chown -R researcher:researcher /opt/repo

# Install deps and start services
export PATH=\"/root/.local/bin:\$PATH\"
for n in 1 2 3; do
    cd /opt/repo/hendrik/challenge\$n
    uv sync 2>/dev/null || true
    nohup uv run uvicorn main:app --host 0.0.0.0 --port \$((4000 + n)) > /tmp/challenge\${n}.log 2>&1 &
done

# Open firewall ports (in case not done yet)
echo 'Startup complete' > /tmp/setup-done
"

gcloud compute instances create "$VM_NAME" \
    --project="$PROJECT" \
    --zone="$ZONE" \
    --machine-type="$MACHINE_TYPE" \
    --accelerator="type=$GPU_TYPE,count=1" \
    --boot-disk-size="${BOOT_DISK_SIZE}GB" \
    --boot-disk-type=pd-ssd \
    --image-family="$IMAGE_FAMILY" \
    --image-project="$IMAGE_PROJECT" \
    --maintenance-policy=TERMINATE \
    --metadata="startup-script=$STARTUP_SCRIPT" \
    --tags="nm-ai" \
    --scopes="default" \
    2>&1

echo ""

# 2. Create firewall rule for challenge ports
echo "[2/5] Creating firewall rule..."
gcloud compute firewall-rules create nm-ai-allow-challenges \
    --project="$PROJECT" \
    --allow=tcp:4001,tcp:4002,tcp:4003 \
    --target-tags=nm-ai \
    --description="Allow traffic to NM i AI challenge endpoints" \
    2>&1 || echo "Firewall rule already exists"

echo ""

# 3. Wait for VM to be ready
echo "[3/5] Waiting for VM and startup script..."
for i in $(seq 1 60); do
    DONE=$(gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT" \
        --command="cat /tmp/setup-done 2>/dev/null" 2>/dev/null || echo "")
    if [ "$DONE" = "Startup complete" ]; then
        echo "VM setup complete!"
        break
    fi
    echo "  Waiting... ($i/60)"
    sleep 10
done

# 4. Get external IP
echo ""
echo "[4/5] Getting VM info..."
EXTERNAL_IP=$(gcloud compute instances describe "$VM_NAME" \
    --zone="$ZONE" --project="$PROJECT" \
    --format="get(networkInterfaces[0].accessConfigs[0].natIP)" 2>/dev/null)

echo "External IP: $EXTERNAL_IP"

# 5. Test endpoints
echo ""
echo "[5/5] Testing endpoints..."
for n in 1 2 3; do
    port=$((4000 + n))
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "http://${EXTERNAL_IP}:${port}/" 2>/dev/null || echo "FAIL")
    echo "  challenge$n (port $port): $STATUS"
done

# Save endpoints
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cat > "${SCRIPT_DIR}/endpoints.txt" <<ENDPOINTS
=== NM i AI 2026 — Submit these URLs to competition ===
VM: $VM_NAME ($EXTERNAL_IP)

Challenge 1: http://${EXTERNAL_IP}:4001/predict
Challenge 2: http://${EXTERNAL_IP}:4002/predict
Challenge 3: http://${EXTERNAL_IP}:4003/predict

Health checks (GET):
  http://${EXTERNAL_IP}:4001/
  http://${EXTERNAL_IP}:4002/
  http://${EXTERNAL_IP}:4003/

SSH: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT
ENDPOINTS

echo ""
echo "=== READY ==="
echo "VM:      $VM_NAME"
echo "IP:      $EXTERNAL_IP"
echo "SSH:     gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT"
echo "Stop:    gcloud compute instances stop $VM_NAME --zone=$ZONE --project=$PROJECT"
echo "Delete:  gcloud compute instances delete $VM_NAME --zone=$ZONE --project=$PROJECT"
echo ""
echo "Endpoints:"
echo "  Challenge 1: http://${EXTERNAL_IP}:4001/predict"
echo "  Challenge 2: http://${EXTERNAL_IP}:4002/predict"
echo "  Challenge 3: http://${EXTERNAL_IP}:4003/predict"
echo ""
echo "Endpoints saved to ${SCRIPT_DIR}/endpoints.txt"
