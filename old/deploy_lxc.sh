#!/usr/bin/env bash
# One-shot LXC setup for Camera AI (Ubuntu LXC on Proxmox).
#
# Usage:
#   1. Create the LXC (see README), copy this project into it
#   2. Set HA_* / REOLINK_* in a .env file (copy example.env)
#   3. Run:  bash deploy_lxc.sh
set -euo pipefail

echo "==> Installing Docker..."
install_docker() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y docker.io curl ca-certificates
  systemctl enable --now docker 2>/dev/null || true
  # Compose v2 is a CLI plugin ("docker compose"), not a Debian package.
  if ! docker compose version >/dev/null 2>&1; then
    echo "Installing Docker Compose v2 plugin..."
    mkdir -p /usr/local/lib/docker/cli-plugins
    case "$(dpkg --print-architecture)" in
      amd64) URL="https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" ;;
      arm64) URL="https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64" ;;
      *) echo "ERROR: unsupported arch for Compose plugin"; return 1 ;;
    esac
    curl -fsSL "$URL" -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  fi
  docker --version
  docker compose version
}
install_docker

echo "==> Starting Camera AI stack..."
docker compose up -d --build

echo "==> Pulling small vision model (moondream) into Ollama..."
docker exec ollama ollama pull moondream

if [[ -d /dev/dri ]]; then
  echo "==> /dev/dri found — setting up Intel iGPU (install_igpu.sh)..."
  bash install_igpu.sh || true
else
  echo "==> /dev/dri not found — skipping iGPU setup."
  echo "    To enable Intel passthrough later, see README or run: bash install_igpu.sh"
fi

echo "==> Done."
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "    GUI:  http://${IP}:8000"
echo "    Ollama (for testing):  curl http://${IP}:11434/api/tags"
