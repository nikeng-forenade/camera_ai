# LXC / Docker-deployment (legacy — flyttad till old/)

> Den här dokumentationen gäller den **gamla** LXC/Docker-deploymenten på
> Proxmox. Vi kör nu Windows-appen (GUI + tray + HA) som huvudversion — se
> huvud-`README.md` i repots rot.

## Option 1 — Proxmox LXC (en kommando)

Everything (app + Ollama) runs in a Debian 12 LXC container.

1. Open the **Proxmox shell** (host, as root) and paste:

   ```bash
   bash -c "$(wget -qLO - https://raw.githubusercontent.com/nikeng-forenade/camera_ai/main/old/lxc/proxmox-create.sh)"
   ```

2. Pick **Default** (DHCP, 2 cores, 4 GB RAM, 40 GB disk) or **Advanced**
   (custom IP/CIDR, CPU/RAM, disk, Intel iGPU, Home Assistant host).

3. Wait — the script creates the container, pushes the project in, installs
   Docker, and starts the stack (first build downloads ~5 GB, give it a few minutes).

4. Open the GUI:

   ```bash
   pct list                                  # find the container IP
   # then browse to  http://<lxc-ip>:8000
   ```

To change settings later, run the interactive installer inside the container:

```bash
pct enter <CT_ID>
cd /root/camera-ai && bash old/lxc/install.sh   # re-prompts, rewrites .env, restarts
```

## Option 2 — Manual install on any Linux box / existing LXC

1. Copy this project into the machine (e.g. `/opt/camera-ai`).
2. As **root**, run the installer — it will **prompt you** for port, YOLO
   model/device, vision LLM, Home Assistant and Reolink settings:

   ```bash
   bash old/lxc/install.sh
   ```

   …or skip the prompts and pass flags:

   ```bash
   bash old/lxc/install.sh --port 8000 --ha-host 192.168.1.10 --yolo-device openvino:GPU
   ```

3. Open `http://<machine-ip>:8000`.

## Deploy in an LXC (Docker)

The whole stack (app **+ Ollama**) is containerised so it runs in an LXC
(e.g. on Proxmox) without running Ollama on the host machine.

### Recommended: paste-and-run on the Proxmox host (syslog_mini style)

Open the **Proxmox shell** and paste:

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/nikeng-forenade/camera_ai/main/old/lxc/proxmox-create.sh)"
```

It prompts for **Default** (DHCP, 2 cores, 4 GB RAM, 40 GB disk) or **Advanced**
(custom IP, CPU/RAM, Intel iGPU, Home Assistant, Reolink).

Non-interactive with options:

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/nikeng-forenade/camera_ai/main/old/lxc/proxmox-create.sh)" -- \
  200 local-lvm vmbr0 192.168.1.50/24 192.168.1.1 \
  --cores 4 --ram 8192 --disk 30 --igpu --ha-host 192.168.1.10
```

Script options:

| Argument | Default | Description |
|---|---|---|
| `<CT_ID> [STORAGE] [BRIDGE] [IP/CIDR] [GATEWAY]` | `200 local-lvm vmbr0 dhcp` | Container / network |
| `--disk GB` | `40` | Root disk |
| `--cores N` | `2` | vCPU cores |
| `--ram MB` | `4096` | Memory |
| `--igpu` | off | Pass through Intel iGPU (`/dev/dri`) |
| `--port`, `--model`, `--yolo-device`, `--llm-model` | `8000 yolo11s.pt cpu moondream` | App settings |
| `--ha-host`, `--ha-port`, `--ha-user`, `--ha-pass` | — | Home Assistant (MQTT discovery) |
| `--reolink-host`, `--reolink-user`, `--reolink-pass` | — | Reolink camera |

It creates the LXC, optionally wires up `/dev/dri`, pushes the project, and runs
`old/lxc/install.sh` (installs Docker, writes `.env`, `docker compose up -d --build`, pulls
moondream, sets up the iGPU).

**Inside the LXC you can run `install.sh` interactively** — with no options it
prompts for the GUI port, YOLO model/device, vision LLM, Home Assistant and
Reolink settings instead of requiring command-line flags:

```bash
# inside the container (as root)
pct enter 200
cd /root/camera-ai && bash old/lxc/install.sh
```

Or clone + run locally (no GitHub needed):

```bash
git clone https://github.com/nikeng-forenade/camera_ai.git /tmp/camera_ai
cd /tmp/camera_ai && bash old/lxc/proxmox-create.sh 200
```

### Manual: copy project into an LXC

1. Create an LXC (Ubuntu 22.04/24.04, 4–8 GB RAM, 40 GB disk) and copy this project in.
2. Create `.env` next to `old/docker-compose.yml` (copy from `example.env`).
3. Start and pull the small vision model:
   ```
   docker compose -f old/docker-compose.yml up -d
   docker exec ollama ollama pull moondream
   ```
4. Open `http://<lxc-ip>:8000`.

Notes:
- **No GPU needed** for yolo11n/yolo11s + moondream on a few cameras (CPU is fine).
- If the LXC host has an NVIDIA GPU you *can* pass it through, but that's fiddly in LXC
  — a small VM is easier for GPU passthrough. For 1–3 cameras, CPU is usually enough.
- Reolink: run `docker exec camera-ai python reolink_motion.py` (with `REOLINK_*` in `.env`)
  to test the motion → snapshot → AI → HA flow, or wire it to Frigate/HA triggers.

### Intel iGPU passthrough (Quick Sync / OpenVINO)

To accelerate YOLO on the host's Intel iGPU from inside the LXC, there's a helper
script (`old/install_igpu.sh`) modeled on the community-scripts Frigate LXC helper.

1. On the Proxmox host, expose `/dev/dri` to the LXC — edit `/etc/pve/lxc/<id>.conf` and add:
   ```
   lxc.cgroup2.devices.allow: c 226:0 rwm
   lxc.cgroup2.devices.allow: c 226:128 rwm
   lxc.mount.entry: /dev/dri/renderD128 dev/dri/renderD128 none bind,optional,create=file
   lxc.mount.entry: /dev/dri/card0 dev/dri/card0 none bind,optional,create=file
   ```
   Restart the container. Then inside the LXC run:
   ```
   bash old/install_igpu.sh
   ```
   It verifies `/dev/dri`, installs the Intel drivers (`intel-opencl-icd`,
   `intel-media-va-driver`, `vainfo`, …), syncs the `video`/`render` GIDs with the
   host and fixes device permissions.

2. The `camera-ai` image already bundles **OpenVINO + Intel OpenCL**. Just enable it:
   ```
   # in .env
   YOLO_DEVICE=openvino:GPU
   ```

3. Restart the stack:
   ```
   docker compose -f old/docker-compose.yml up -d --force-recreate camera-ai
   ```
   and watch the inference time in the GUI drop.

Intel passthrough notes:
- The iGPU must already be enabled/usable on the Proxmox host (BIOS: enable iGPU).
- If `/dev/dri` is not exposed in the LXC, remove the `devices:` block from
  `old/docker-compose.yml` (CPU mode still works).
- Ollama has limited Intel iGPU support; `moondream` runs fine on CPU — the
  passthrough mainly speeds up YOLO via OpenVINO.
