#!/bin/bash
# Camera AI LXC Update Script — run inside the container, or from the host:
#   pct exec <CTID> -- bash /root/camera-ai/lxc/update.sh
#
# Re-downloads the latest code from GitHub, keeps .env / media / uploads,
# and rebuilds the Docker stack. Requires network access.
set -euo pipefail

GITHUB_OWNER="${GITHUB_OWNER:-nikeng-forenade}"
GITHUB_REPO="${GITHUB_REPO:-camera_ai}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
APP_DIR="${APP_DIR:-/root/camera-ai}"

echo "=== Camera AI Update ==="
echo "Source: ${GITHUB_OWNER}/${GITHUB_REPO}@${GITHUB_BRANCH}"
[ -d "$APP_DIR" ] || { echo "ERROR: $APP_DIR not found — is the app installed?"; exit 1; }

# DNS self-heal
if ! getent hosts codeload.github.com >/dev/null 2>&1; then
  echo "DNS failing — injecting public nameservers..."
  cp /etc/resolv.conf /etc/resolv.conf.bak 2>/dev/null || true
  printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > /etc/resolv.conf
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading latest code..."
curl -fsSL -o "$TMP/tarball.tgz" \
  "https://codeload.github.com/${GITHUB_OWNER}/${GITHUB_REPO}/tar.gz/refs/heads/${GITHUB_BRANCH}"
tar xzf "$TMP/tarball.tgz" --strip-components=1 -C "$TMP"

# Back up .env, then sync code while keeping local state
[ -f "$APP_DIR/.env" ] && cp "$APP_DIR/.env" "$APP_DIR/.env.bak" && echo ".env backed up to .env.bak"

# rsync is used to sync the new code while keeping .env / media / uploads
if ! command -v rsync >/dev/null 2>&1; then
  echo "Installing rsync..."
  apt-get update && apt-get install -y rsync
fi

rsync -a --delete \
  --exclude '.env' --exclude '.env.bak' \
  --exclude 'media' --exclude 'uploads' \
  "$TMP/" "$APP_DIR/"

echo "Rebuilding stack..."
cd "$APP_DIR"
docker compose up -d --build --force-recreate

echo ""
echo "=== Updated! GUI: http://<this-container-ip>:${PORT:-8000} ==="
