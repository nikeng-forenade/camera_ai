# Camera AI

AI-baserad kameraanalys som kör lokalt på Windows (Intel Arc) med **YOLO**-detektering
och ett litet lokalt **vision-LLM** (Ollama) som beskriver scenen — med inbyggd
Home Assistant-integration (MQTT + REST) och **larmstyrd LLM-laddning**.

```
kamera → snapshot (rörelse) → YOLO-detektering → LLM-beskrivning → resultat
```

## Funktioner

- **Windows-app med GUI** — eget fönster + taskbar/tray-ikon (pywebview), eller headless som tjänst (NSSM).
- **YOLO på Intel Arc** via OpenVINO (`openvino:GPU` → `intel:gpu`).
- **Vision-LLM (Ollama) på Arc** via Vulkan (`OLLAMA_VULKAN=1`).
- **Home Assistant** — MQTT auto-discovery (binary_sensor, sensor, image) + REST.
- **Larmstyrd LLM-laddning** — LLM laddas när HA-larmet är skarpt, laddas ur när det är av (frigör VRAM).
- **HACS-integration** — välj modell/konfidens direkt från HA:s UI.

## Installation (Windows)

Krav: Windows 10/11 eller Server 2025, **Intel Arc B50 Pro** med drivrutin,
Python 3.12 (x64), Git och [Ollama](https://ollama.com).

1. Klona och sätt upp:
   ```powershell
   git clone https://github.com/nikeng-forenade/camera_ai.git C:\camera_ai
   cd C:\camera_ai
   powershell -ExecutionPolicy Bypass -File windows\setup.ps1
   ```

2. Aktivera Vulkan för Ollama (Arc B50 Pro) och hämta `moondream`:
   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\setup-ollama.ps1
   ```

3. Starta appen (GUI-fönster + tray-ikon; stäng = minimera till tray, avsluta via ikonen):
   ```powershell
   .\windows\start.bat
   ```
   Utan pywebview öppnas webbläsaren istället: `http://127.0.0.1:8000`.

4. Home Assistant: kopiera `custom_components/camera_ai` till HA:s
   `custom_components/`, lägg till integrationen med `http://<dator-ip>:8000`
   (appen lyssnar på `0.0.0.0`).

Valfritt: kör som tjänst (headless) med `windows\install-service.ps1` (NSSM).

### Fristående EXE (valfritt)

```powershell
powershell -ExecutionPolicy Bypass -File windows\build_exe.ps1          # onedir (snabb start)
powershell -ExecutionPolicy Bypass -File windows\build_exe.ps1 -OneFile # en enda fil
```

Resultat:
- onedir: `dist\CameraAI\CameraAI.exe` — flytta **hela mappen**.
- onefile: `dist\CameraAI.exe` — en enda fil (långsammare start).

`.env`, `uploads/`, `media/` och OpenVINO-modeller skapas automatiskt
**bredvid exe:n**. Bygget ger ~1–2 GB.

### Uppdatera

```powershell
powershell -ExecutionPolicy Bypass -File windows\update.ps1
```

## Konfiguration

`.env` i projektroten (se `example.env`):

| Setting | Beskrivning | Default |
|---|---|---|
| `YOLO_MODEL` | YOLO-modell | `yolo11n.pt` |
| `YOLO_CONF` | Konfidensgräns | `0.30` |
| `YOLO_DEVICE` | `cpu` / `0` (CUDA) / `openvino:GPU` (Intel) | `cpu` |
| `LLM_BACKEND` | `ollama` / `none` | `ollama` |
| `OLLAMA_MODEL` | Vision-LLM (Ollama) | `moondream` |
| `OLLAMA_URL` | Ollama-server | `http://localhost:11434` |
| `HA_ENABLED` | Skicka resultat till HA | `1` |
| `HA_TRANSPORT` | `mqtt` eller `rest` | `mqtt` |
| `HA_ALARM_TOPIC` | MQTT-topic för larmstatus | `homeassistant/alarm_control_panel/+/state` |
| `OLLAMA_KEEP_ALIVE_ARMED` | `keep_alive` när larmet är skarpt (−1 = håll laddad) | `-1` |
| `OLLAMA_KEEP_ALIVE_DISARMED` | `keep_alive` när larmet är av (0 = ladda ur) | `0` |

Om Ollama inte körs fungerar YOLO-detekteringen ändå — beskrivningen visar bara ett fel.

## Home Assistant

### MQTT + auto-discovery (rekommenderat)

Skapa `.env` (se `example.env`) och starta om appen:
```
HA_ENABLED=1
HA_TRANSPORT=mqtt
HA_MQTT_HOST=<ha-ip>
HA_MQTT_PORT=1883
HA_MQTT_USER=<mqtt-user>
HA_MQTT_PASS=<mqtt-pass>
```
Entiteter skapas automatiskt i HA (ingen YAML, ingen omstart):
- `binary_sensor.camera_ai_motion` — ON när objekt detekteras
- `sensor.camera_ai_last_detection` — klasser + konfidens (JSON)
- `sensor.camera_ai_scene_description` — LLM-beskrivningen
- `image.camera_ai_snapshot` — den annoterade bilden

### Larmstyrd LLM-laddning

Appen prenumererar på HA:s larmstatus (`HA_ALARM_TOPIC`). När larmet är **skarpt**
laddas vision-LLM:en och hålls kvar i minnet (`keep_alive=-1`) så beskrivningar blir
snabba. När larmet är **av** laddas den ur (`keep_alive=0`) för att frigöra VRAM.

### REST (alternativ)

```
HA_ENABLED=1
HA_TRANSPORT=rest
HA_REST_URL=http://<ha-ip>:8123
HA_REST_TOKEN=<long-lived-token>
```
HA får `sensor.camera_ai_detection` och eventet `camera_ai_result`
(automationer kan lyssna på `event_type: camera_ai_result`).

## HACS-integration

Installera via HACS: **Settings → Custom repositories** → lägg till
`https://github.com/nikeng-forenade/camera_ai` (kategori **Integration**).
Lägg sedan till integrationen med server-URL `http://<server-ip>:8000` och välj
YOLO-modell, konfidens och om LLM ska användas direkt från HA.

Exempelautomation (rörelse → analys):
```yaml
alias: "Camera AI — analysera på rörelse"
trigger:
  platform: state
  entity_id: binary_sensor.reolink_front_motion
  to: "on"
action:
  - service: camera_ai.analyze_camera
    data:
      camera_entity: camera.reolink_front
      model: yolo11s.pt
```

## API

- `GET  /api/health` — modell + LLM-status
- `POST /api/analyze` — multipart `file` (+ `model`, `conf`, `use_llm`, `prompt`) → detektioner, annoterad bild, beskrivning
- `POST /api/analyze-url` — analysera en bild-URL

## Reolink-kamera

`reolink_motion.py` drar en snapshot från Reolink-HTTP-API:et vid rörelse, kör
YOLO + LLM och publicerar resultatet till HA. Konfigurera via `REOLINK_HOST`,
`REOLINK_USER`, `REOLINK_PASS` i `.env`.

## Lokal utveckling

Kräver Python 3.9+ och [Ollama](https://ollama.com):
```powershell
ollama pull moondream
pip install -r requirements.txt
python app.py
```
Öppna `http://127.0.0.1:8000`. Första YOLO-körningen laddar ner modellen
(`yolo11n.pt`, ~6 MB) — kräver internet en gång.

## Arkiv

Gamla **LXC/Docker-deploymenten** (Proxmox, Docker Compose, Intel iGPU
passthrough) finns arkiverad under [`old/README-lxc.md`](old/README-lxc.md).
