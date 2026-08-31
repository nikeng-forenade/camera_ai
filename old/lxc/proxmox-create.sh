#!/usr/bin/env bash
# Camera AI LXC Creator for Proxmox VE
# Paste this in your Proxmox shell:
#   bash -c "$(wget -qLO - https://raw.githubusercontent.com/nikeng-forenade/camera_ai/main/old/lxc/proxmox-create.sh)"
#
# Non-interactive with options:
#   bash -c "$(wget -qLO - https://raw.githubusercontent.com/nikeng-forenade/camera_ai/main/old/lxc/proxmox-create.sh)" -- \
#       200 local-lvm vmbr0 192.168.1.50/24 192.168.1.1 --cores 4 --ram 8192 --igpu --ha-host 192.168.1.10
#
# Set GITHUB_OWNER / GITHUB_REPO / GITHUB_BRANCH if you host this elsewhere.
set -e

GITHUB_OWNER="${GITHUB_OWNER:-nikeng-forenade}"
GITHUB_REPO="${GITHUB_REPO:-camera_ai}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
GITHUB_RAW="https://raw.githubusercontent.com/${GITHUB_OWNER}/${GITHUB_REPO}/${GITHUB_BRANCH}"
GITHUB_TARBALL="https://codeload.github.com/${GITHUB_OWNER}/${GITHUB_REPO}/tar.gz/refs/heads/${GITHUB_BRANCH}"

# ── Detect local clone vs remote ──────────────────────────
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR=""
if [[ -f "$LOCAL_DIR/install.sh" && -f "$LOCAL_DIR/../app.py" ]]; then
  echo "Running from local clone: $LOCAL_DIR"
  PROJECT_DIR="$LOCAL_DIR/.."
  INSTALL_SCRIPT="$LOCAL_DIR/install.sh"
else
  echo "Downloading install.sh from $GITHUB_RAW ..."
  mkdir -p /tmp/camera-ai-lxc
  INSTALL_SCRIPT="/tmp/camera-ai-lxc/install.sh"
  curl -fsSL -o "$INSTALL_SCRIPT" "$GITHUB_RAW/old/lxc/install.sh"
fi

# ── Defaults ──────────────────────────────────────────────
CT_ID="200"; STORAGE="local-lvm"; BRIDGE="vmbr0"; IP="dhcp"; GATEWAY=""
DISK_SIZE="40"; CORES="2"; RAM="4096"; IGPU="0"; INSTALL_OPTS=""

show_help() {
  cat <<'EOF'
Usage: bash proxmox-create.sh [OPTIONS] [<CT_ID> [STORAGE] [BRIDGE] [IP/CIDR] [GATEWAY]]

Positional (optional):
  <CT_ID> [STORAGE] [BRIDGE] [IP/CIDR] [GATEWAY]

Container options:
  --disk GB       Root disk size (default: 40)
  --cores N       vCPU cores (default: 2)
  --ram MB        Memory in MB (default: 4096)
  --igpu          Pass through Intel iGPU (/dev/dri) to the container
  --help          Show this help

Options (forwarded to install.sh):
  --port PORT          GUI port (default: 8000)
  --model MODEL        YOLO model (default: yolo11s.pt)
  --yolo-device DEV    cpu | openvino:GPU (default: cpu)
  --llm-model MODEL    Ollama vision model (default: moondream)
  --ha-host HOST       Home Assistant host (enables HA, MQTT discovery)
  --ha-port PORT       HA MQTT port (default: 1883)
  --ha-user USER       HA MQTT user
  --ha-pass PASS       HA MQTT password
  --reolink-host HOST  Reolink camera host
  --reolink-user USER  Reolink camera user
  --reolink-pass PASS  Reolink camera password
EOF
}

# ── Parse args ────────────────────────────────────────────
POS_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help) show_help; exit 0 ;;
    --disk) DISK_SIZE="$2"; shift 2 ;;
    --cores) CORES="$2"; shift 2 ;;
    --ram) RAM="$2"; shift 2 ;;
    --igpu) IGPU="1"; shift ;;
    --port|--model|--yolo-device|--llm-model|--ha-host|--ha-port|--ha-user|--ha-pass|--reolink-host|--reolink-user|--reolink-pass)
      INSTALL_OPTS="$INSTALL_OPTS $1 $2"; shift 2 ;;
    --*) echo "Unknown option: $1"; exit 1 ;;
    *) POS_ARGS+=("$1"); shift ;;
  esac
done

CT_ID="${POS_ARGS[0]:-200}"
STORAGE="${POS_ARGS[1]:-local-lvm}"
BRIDGE="${POS_ARGS[2]:-vmbr0}"
IP="${POS_ARGS[3]:-dhcp}"
GATEWAY="${POS_ARGS[4]:-}"

# ── Interactive setup (no args) ───────────────────────────
if [[ ${#POS_ARGS[@]} -eq 0 ]] && [[ -z "$INSTALL_OPTS" ]]; then
  echo ""
  echo "  ┌──────────────────────────────────────────┐"
  echo "  │           📷 Camera AI LXC               │"
  echo "  └──────────────────────────────────────────┘"
  echo ""
  echo "  Default:  DHCP, 2 cores, 4 GB RAM, 40 GB disk, no iGPU"
  echo "  Advanced: Custom IP, CPU/RAM, Intel iGPU, HA/Reolink"
  echo ""
  read -r -p "  Default [d] or Advanced [a]? (d/a): " MODE
  echo ""
  if [[ "$MODE" =~ ^[Aa]$ ]]; then
    read -r -p "  Container ID [200]: " input; CT_ID="${input:-200}"
    read -r -p "  Storage pool [local-lvm]: " input; STORAGE="${input:-local-lvm}"
    read -r -p "  Network bridge [vmbr0]: " input; BRIDGE="${input:-vmbr0}"
    read -r -p "  IP/CIDR [dhcp]: " input; IP="${input:-dhcp}"
    if [[ "$IP" != "dhcp" ]]; then
      read -r -p "  Gateway IP: " input; GATEWAY="${input:-}"
    fi
    read -r -p "  Cores [2]: " input; CORES="${input:-2}"
    read -r -p "  RAM MB [4096]: " input; RAM="${input:-4096}"
    read -r -p "  Disk GB [40]: " input; DISK_SIZE="${input:-40}"
    read -r -p "  Intel iGPU passthrough? (y/N): " input
    [[ "$input" =~ ^[Yy]$ ]] && IGPU="1"
    read -r -p "  Home Assistant host (empty to skip): " input
    if [[ -n "$input" ]]; then
      INSTALL_OPTS="--ha-host $input"
      read -r -p "  MQTT port [1883]: " p; INSTALL_OPTS="$INSTALL_OPTS --ha-port ${p:-1883}"
    fi
  fi
fi

# ── Sanitize + auto CIDR ──────────────────────────────────
sanitize() { echo "$1" | tr -d '\r\n'; }
CT_ID=$(sanitize "$CT_ID"); STORAGE=$(sanitize "$STORAGE"); BRIDGE=$(sanitize "$BRIDGE")
IP=$(sanitize "$IP"); GATEWAY=$(sanitize "$GATEWAY")
DISK_SIZE=$(sanitize "$DISK_SIZE"); CORES=$(sanitize "$CORES"); RAM=$(sanitize "$RAM")
if [[ "$IP" != "dhcp" && "$IP" != */* ]]; then
  IP="${IP}/24"; echo "Auto-added /24 CIDR → $IP"
fi

# ── Summary ───────────────────────────────────────────────
echo ""
echo "=== Camera AI LXC Setup ==="
echo "CT ID:    $CT_ID"
echo "Storage:  $STORAGE    Disk: ${DISK_SIZE} GB"
echo "Bridge:   $BRIDGE     IP: $IP    Gateway: ${GATEWAY:--}"
echo "CPU/RAM:  ${CORES} cores / ${RAM} MB"
echo "iGPU:     $([ "$IGPU" = "1" ] && echo yes || echo no)"
[[ -n "$INSTALL_OPTS" ]] && echo "Options:  $INSTALL_OPTS"
echo ""

# ── Host DNS pre-check (template download + container apt need DNS) ──
if ! getent hosts deb.debian.org >/dev/null 2>&1; then
  echo "⚠️  DNS resolution is failing on this Proxmox host (deb.debian.org not resolving)."
  echo "    Quick fix:"
  echo "      cp /etc/resolv.conf /etc/resolv.conf.bak"
  echo "      echo 'nameserver 1.1.1.1' > /etc/resolv.conf"
  echo "      echo 'nameserver 8.8.8.8' >> /etc/resolv.conf"
  read -r -p "    Fix DNS now and continue? (y/N): " FIX_DNS
  if [[ "$FIX_DNS" =~ ^[Yy]$ ]]; then
    cp /etc/resolv.conf /etc/resolv.conf.bak 2>/dev/null || true
    printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > /etc/resolv.conf
    getent hosts deb.debian.org >/dev/null 2>&1 && echo "✅ DNS is working now." || echo "⚠️  DNS still failing — check your network."
  else
    echo "Aborting (DNS is required for template + package downloads)."
    exit 1
  fi
fi

# ── Find / download Debian 12 template ────────────────────
TEMPLATE_STORAGE="local"
for s in local "$STORAGE"; do
  if pveam list "$s" &>/dev/null; then TEMPLATE_STORAGE="$s"; break; fi
done
TEMPLATE=$(pveam list "$TEMPLATE_STORAGE" 2>/dev/null | awk '{print $1}' | grep -oP 'debian-12-standard_\S+_amd64\.tar\.zst' | sort -V | tail -1 || true)
if [ -z "$TEMPLATE" ]; then
  echo "No local Debian 12 template, checking online catalog..."
  pveam update 2>/dev/null || true
  TEMPLATE=$(pveam available -section system 2>/dev/null | awk '{print $2}' | grep -oP 'debian-12-standard_\S+_amd64\.tar\.zst' | sort -V | tail -1 || true)
fi
[ -n "$TEMPLATE" ] || { echo "ERROR: Debian 12 template not found. Run 'pveam update' and retry."; exit 1; }
if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
  echo "Downloading $TEMPLATE to '$TEMPLATE_STORAGE'..."
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE" || { echo "ERROR: template download failed."; exit 1; }
fi

# ── Build net0 + create ───────────────────────────────────
NET0="name=eth0,bridge=${BRIDGE},ip=${IP}"
if [[ "$IP" != "dhcp" && -n "$GATEWAY" ]]; then NET0="${NET0},gw=${GATEWAY}"; fi
echo "Creating container with: net0=$NET0"

pct create "$CT_ID" "${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}" \
  --hostname "camera-ai" \
  --rootfs "${STORAGE}:${DISK_SIZE}" \
  --memory "$RAM" --cores "$CORES" \
  --net0 "$NET0" \
  --unprivileged 1 \
  --features "nesting=1" \
  --onboot 1 \
  --start 1
echo "Container created. Waiting for boot..."
sleep 12

# ── Intel iGPU passthrough ────────────────────────────────
if [[ "$IGPU" == "1" ]]; then
  echo "Adding Intel iGPU passthrough to LXC config..."
  CONF="/etc/pve/lxc/${CT_ID}.conf"
  cat >> "$CONF" <<'EOF'

# Intel iGPU passthrough (added by camera-ai proxmox-create.sh)
lxc.cgroup2.devices.allow: c 226:0 rwm
lxc.cgroup2.devices.allow: c 226:128 rwm
lxc.mount.entry: /dev/dri/renderD128 dev/dri/renderD128 none bind,optional,create=file
lxc.mount.entry: /dev/dri/card0 dev/dri/card0 none bind,optional,create=file
EOF
  echo "Restarting container to apply iGPU passthrough..."
  pct reboot "$CT_ID" || { pct stop "$CT_ID"; sleep 2; pct start "$CT_ID"; }
  sleep 10
fi

# ── Push project + install script ─────────────────────────
echo "Pushing project files..."
pct exec "$CT_ID" -- mkdir -p /root/camera-ai
TARBALL="/tmp/camera-ai-${CT_ID}.tgz"
if [[ -n "$PROJECT_DIR" ]]; then
  tar czf "$TARBALL" -C "$PROJECT_DIR" \
    --exclude .git --exclude .venv --exclude venv \
    --exclude uploads --exclude media --exclude __pycache__ .
else
  echo "Downloading project tarball from GitHub..."
  curl -fsSL -o "$TARBALL" "$GITHUB_TARBALL"
fi
pct push "$CT_ID" "$TARBALL" /root/camera-ai.tgz
rm -f "$TARBALL"
pct exec "$CT_ID" -- bash -c "cd /root && tar xzf camera-ai.tgz --strip-components=1 -C /root/camera-ai && rm -f camera-ai.tgz"
pct push "$CT_ID" "$INSTALL_SCRIPT" /root/camera-ai/old/lxc/install.sh
pct exec "$CT_ID" -- chmod +x /root/camera-ai/old/lxc/install.sh

# ── Run install ───────────────────────────────────────────
echo "Running install script..."
if [[ -n "$INSTALL_OPTS" ]]; then
  pct exec "$CT_ID" -- bash /root/camera-ai/old/lxc/install.sh $INSTALL_OPTS
else
  pct exec "$CT_ID" -- bash /root/camera-ai/old/lxc/install.sh
fi

# ── Summary ───────────────────────────────────────────────
IP_ADDR=$(pct exec "$CT_ID" -- ip -4 addr show eth0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1)
echo ""
echo "=============================================="
echo "  📷 Camera AI is ready!"
echo "  GUI:   http://${IP_ADDR:-<container-ip>}:8000"
  echo "  Check: pct exec $CT_ID -- docker compose -f /root/camera-ai/old/docker-compose.yml ps"
echo "=============================================="
