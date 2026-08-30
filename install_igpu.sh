#!/usr/bin/env bash
# Intel iGPU setup inside the LXC.
#
# Modeled on the community-scripts Frigate LXC helper
# (https://github.com/community-scripts/ProxmoxVE ct/frigate.sh
#  + core lib/hwaccel.func).
#
# Run INSIDE the LXC, AFTER /dev/dri has been passed through from the host.
# Then enable OpenVINO in the app (YOLO_DEVICE=openvino:GPU).
set -euo pipefail

echo "==> 1. Checking /dev/dri passthrough..."
if [[ ! -d /dev/dri ]]; then
  echo "ERROR: /dev/dri not found in this container."
  echo
  echo "On the Proxmox HOST, add these lines to /etc/pve/lxc/<CTID>.conf and"
  echo "restart the container:"
  echo '  lxc.cgroup2.devices.allow: c 226:0 rwm'
  echo '  lxc.cgroup2.devices.allow: c 226:128 rwm'
  echo '  lxc.mount.entry: /dev/dri/renderD128 dev/dri/renderD128 none bind,optional,create=file'
  echo '  lxc.mount.entry: /dev/dri/card0 dev/dri/card0 none bind,optional,create=file'
  exit 1
fi
echo "    /dev/dri present: $(ls /dev/dri 2>/dev/null | tr '\n' ' ')"

echo "==> 2. Installing Intel GPU userspace packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# Gen 9+ (UHD/Iris) — same set as the community-scripts hwaccel helper
apt-get install -y --no-install-recommends \
  va-driver-all intel-media-va-driver intel-media-va-driver-non-free \
  ocl-icd-libopencl1 intel-opencl-icd mesa-vulkan-drivers \
  libmfx-gen1.2 vainfo intel-gpu-tools pciutils || {
  echo "    (some Intel packages unavailable on this release — continuing)"
  apt-get install -y --no-install-recommends ocl-icd-libopencl1 intel-opencl-icd \
    intel-media-va-driver vainfo intel-gpu-tools || true
}

echo "==> 3. Fixing device permissions (sync video/render GID with host)..."
chgrp video /dev/dri 2>/dev/null || true
chmod 755 /dev/dri 2>/dev/null || true
chmod 660 /dev/dri/* 2>/dev/null || true
for g in video render; do
  host_gid=$(getent group "$g" | cut -d: -f3)
  if [[ -n "$host_gid" ]]; then
    sed -i "s/^$g:x:[0-9]*:/$g:x:$host_gid:/" /etc/group 2>/dev/null || true
    echo "    group $g -> GID $host_gid"
  fi
done

echo "==> 4. Verifying..."
if command -v vainfo >/dev/null 2>&1; then
  if vainfo 2>/dev/null | grep -qi "Driver version"; then
    echo "    VA-API OK"
  else
    echo "    vainfo ran but found no driver — check passthrough"
  fi
fi
ls -la /dev/dri

echo
echo "==> 5. Enable OpenVINO in the stack:"
echo "    docker exec camera-ai pip install openvino   (if not already in image)"
echo "    # .env:  YOLO_DEVICE=openvino:GPU"
echo "    docker compose up -d --force-recreate camera-ai"
