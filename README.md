# Camera AI — Test GUI (YOLO + small vision LLM)

Local web app that tests the "Reolink motion → AI → result" pipeline **without the camera**:
upload pictures, YOLO detects objects, and a small local vision LLM describes the scene.

```
camera → snapshot (motion) → YOLO detection → small LLM description → result
```

## Quick start

```powershell
# 1. (optional) install the small vision LLM runtime
#    https://ollama.com — then pull a small vision model:
ollama pull moondream        # ~1.9B, runs on CPU

# 2. install deps
pip install -r requirements.txt

# 3. run
python app.py                # then open http://127.0.0.1:8000
```

The first YOLO run downloads the model (yolo11n.pt, ~6 MB) — needs internet once.

## Settings

| Setting | Where | Default |
|---|---|---|
| YOLO model | GUI dropdown / env `YOLO_MODEL` | `yolo11n.pt` |
| Confidence | GUI slider / env `YOLO_CONF` | `0.35` |
| Vision LLM | GUI checkbox / env `LLM_BACKEND` (`ollama` / `none`) | `ollama` |
| LLM model | env `OLLAMA_MODEL` | `moondream` |
| LLM server | env `OLLAMA_URL` | `http://localhost:11434` |

Small vision LLM options in Ollama: `moondream` (~1.9B, CPU-friendly) or `llava` (~7B).
If Ollama isn't running, YOLO detection still works — the description just shows an error.

## API

- `GET  /api/health` — model + LLM status
- `POST /api/analyze` — multipart `file` (+ optional `model`, `conf`, `use_llm`, `prompt`) → detections, annotated image URL, description

## Deploy in an LXC (Docker)

The whole stack (app **+ Ollama**) is containerised so it runs in an LXC
(e.g. on Proxmox) without running Ollama on the host machine.

1. Create an LXC (Ubuntu 22.04/24.04, 2–4 GB RAM, ~20 GB disk) and install Docker:
   ```
   apt update && apt install -y docker.io docker-compose-v2
   ```
2. Copy this project into the LXC (`git clone …` or scp).
3. Create `.env` next to `docker-compose.yml` (copy from `example.env`) and set
   `HA_ENABLED=1`, `HA_MQTT_HOST=<your HA IP>` — point it at Home Assistant on your LAN.
4. Start and pull the small vision model:
   ```
   docker compose up -d
   docker exec ollama ollama pull moondream
   ```
5. Open `http://<lxc-ip>:8000`.

Notes:
- **No GPU needed** for yolo11n/yolo11s + moondream on a few cameras (CPU is fine).
- If the LXC host has an NVIDIA GPU you *can* pass it through, but that's fiddly in LXC
  — a small VM is easier for GPU passthrough. For 1–3 cameras, CPU is usually enough.
- Reolink: run `docker exec camera-ai python reolink_motion.py` (with `REOLINK_*` in `.env`)
  to test the motion → snapshot → AI → HA flow, or wire it to Frigate/HA triggers.

## Talk to Home Assistant

The app can push every analysis result to HA. Two transports — **no custom add-on needed**.

### MQTT + auto-discovery (recommended)
Entities appear in HA automatically — no YAML, no restart. This is the same mechanism Frigate uses.
1. In HA: **Settings → Devices & Services → MQTT** and install the **Mosquitto broker** add-on.
2. Create a `.env` file in this folder (see `example.env`) or export the env vars, then restart `python app.py`:
   ```
   HA_ENABLED=1
   HA_TRANSPORT=mqtt
   HA_MQTT_HOST=<home-assistant-ip-or-host>
   HA_MQTT_PORT=1883
   HA_MQTT_USER=<mqtt-user>
   HA_MQTT_PASS=<mqtt-pass>
   ```
3. Entities that appear in HA:
   - `binary_sensor.camera_ai_motion` — ON when objects detected
   - `sensor.camera_ai_last_detection` — classes + confidence (JSON)
   - `sensor.camera_ai_scene_description` — the LLM description
   - `image.camera_ai_snapshot` — the annotated picture

### REST API (alternative)
1. In HA: click your user → **Security → Long-lived access tokens** → create one.
2. `.env`:
   ```
   HA_ENABLED=1
   HA_TRANSPORT=rest
   HA_REST_URL=http://<home-assistant-ip>:8123
   HA_REST_TOKEN=<long-lived-token>
   ```
3. HA gets a `sensor.camera_ai_detection` state and fires a `camera_ai_result` event
   (automations can listen: `event_type: camera_ai_result`).

In the GUI tick **“Send results to Home Assistant”** to push each uploaded picture.
When wired to the camera, `reolink_motion.py` publishes the same results automatically on motion.

## Next step: wire up the Reolink camera

The `analyzer.py` pipeline is the same one used by `reolink_motion.py`, which:
1. Pulls a snapshot from the Reolink HTTP API when motion is detected,
2. Runs YOLO + the LLM on it,
3. Pushes the result somewhere (MQTT → Home Assistant, or a webhook/notification).

Configure the camera via env vars: `REOLINK_HOST`, `REOLINK_USER`, `REOLINK_PASS`.

> Running it in an LXC (e.g. on Proxmox) later is a drop-in: same code, no GPU needed for
> yolo11n + moondream on a handful of cameras.
