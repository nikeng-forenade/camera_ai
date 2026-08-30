#!/bin/bash
# Camera AI LXC Install Script — run inside an LXC container (Debian 12+).
#
# Usage:
#   bash install.sh
#   bash install.sh --port 8000 --ha-host 192.168.1.10 --yolo-device openvino:GPU
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────
PORT="8000"
MODEL="yolo11s.pt"
YOLO_DEVICE="cpu"
LLM_MODEL="moondream"
HA_ENABLED="0"
HA_MQTT_HOST=""
HA_MQTT_PORT="1883"
HA_MQTT_USER=""
HA_MQTT_PASS=""
REOLINK_HOST=""
REOLINK_USER=""
REOLINK_PASS=""

show_help() {
  cat <<'EOF'
Usage: bash install.sh [OPTIONS]

Options:
  --port PORT            GUI port (default: 8000)
  --model MODEL          YOLO model (default: yolo11s.pt)
  --yolo-device DEV      cpu | openvino:GPU (default: cpu)
  --igpu                 Shorthand for --yolo-device openvino:GPU
  --llm-model MODEL      Ollama vision model (default: moondream)
  --ha-host HOST         Home Assistant host (enables HA + MQTT discovery)
  --ha-port PORT         HA MQTT port (default: 1883)
  --ha-user USER         HA MQTT user
  --ha-pass PASS         HA MQTT password
  --reolink-host HOST    Reolink camera host
  --reolink-user USER    Reolink camera user
  --reolink-pass PASS    Reolink camera password
  --help                 Show this help
EOF
  exit 0
}

# ── Parse CLI options ─────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)          PORT="$2"; shift 2 ;;
    --model)         MODEL="$2"; shift 2 ;;
    --yolo-device)   YOLO_DEVICE="$2"; shift 2 ;;
    --igpu)          YOLO_DEVICE="openvino:GPU"; shift ;;
    --llm-model)     LLM_MODEL="$2"; shift 2 ;;
    --ha-host)       HA_ENABLED="1"; HA_MQTT_HOST="$2"; shift 2 ;;
    --ha-port)       HA_MQTT_PORT="$2"; shift 2 ;;
    --ha-user)       HA_MQTT_USER="$2"; shift 2 ;;
    --ha-pass)       HA_MQTT_PASS="$2"; shift 2 ;;
    --reolink-host)  REOLINK_HOST="$2"; shift 2 ;;
    --reolink-user)  REOLINK_USER="$2"; shift 2 ;;
    --reolink-pass)  REOLINK_PASS="$2"; shift 2 ;;
    --help)          show_help ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── cd to project root (this script lives at <project>/lxc/install.sh) ──
cd "$(cd "$(dirname "$0")" && pwd)/.."

echo "=== Camera AI LXC Install ==="
echo "GUI:      :${PORT}"
echo "YOLO:     ${MODEL} on ${YOLO_DEVICE}"
echo "LLM:      ${LLM_MODEL}"
echo "HA:       $([ "$HA_ENABLED" = "1" ] && echo "enabled ($HA_MQTT_HOST:$HA_MQTT_PORT)" || echo "disabled")"
[[ -n "$REOLINK_HOST" ]] && echo "Reolink:  $REOLINK_HOST"
echo ""

[ "$(id -u)" -eq 0 ] || { echo "ERROR: run as root"; exit 1; }

# ── Ensure DNS works (fixes 'Temporary failure resolving' in LXC) ──
if ! getent hosts deb.debian.org >/dev/null 2>&1; then
  echo "DNS resolution failing — injecting public nameservers..."
  cp /etc/resolv.conf /etc/resolv.conf.bak 2>/dev/null || true
  printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > /etc/resolv.conf
fi

# ── Install Docker ────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y docker.io docker-compose-v2 curl
else
  echo "Docker already installed: $(docker --version)"
fi
systemctl enable --now docker 2>/dev/null || true

# ── Write .env ────────────────────────────────────────────
echo "Writing .env ..."
cat > .env <<EOF
YOLO_MODEL=$MODEL
YOLO_DEVICE=$YOLO_DEVICE
LLM_BACKEND=ollama
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=$LLM_MODEL
HA_ENABLED=$HA_ENABLED
HA_TRANSPORT=mqtt
HA_MQTT_HOST=$HA_MQTT_HOST
HA_MQTT_PORT=$HA_MQTT_PORT
HA_MQTT_USER=$HA_MQTT_USER
HA_MQTT_PASS=$HA_MQTT_PASS
REOLINK_HOST=$REOLINK_HOST
REOLINK_USER=$REOLINK_USER
REOLINK_PASS=$REOLINK_PASS
PORT=$PORT
EOF

# ── Start the stack ───────────────────────────────────────
echo "Starting Camera AI stack (first build downloads ~5 GB, this takes a while)..."
docker compose up -d --build

# ── Pull vision model ─────────────────────────────────────
echo "Pulling vision model ${LLM_MODEL} into Ollama..."
docker exec ollama ollama pull "$LLM_MODEL" || echo "  (model pull failed — run: docker exec ollama ollama pull $LLM_MODEL)"

# ── Intel iGPU ────────────────────────────────────────────
if [[ "$YOLO_DEVICE" == "openvino:GPU" ]]; then
  echo "Enabling Intel iGPU (OpenVINO)..."
  bash install_igpu.sh || echo "  (iGPU setup incomplete — see install_igpu.sh output)"
  docker compose up -d --force-recreate camera-ai
fi

# ── Summary ───────────────────────────────────────────────
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
IP="${IP:-<container-ip>}"
echo ""
cat <<EOF
✅ Camera AI installed.
  GUI     : http://${IP}:${PORT}
  Config  : $(pwd)/.env
  Check   : docker compose -f $(pwd)/docker-compose.yml ps
  HA      : $([ "$HA_ENABLED" = "1" ] && echo "entities auto-created via MQTT discovery (binary_sensor.camera_ai_*, image.camera_ai_snapshot)" || echo "disabled — re-run with --ha-host <HA-IP> to enable")
EOF
