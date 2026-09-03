# Camera AI

AI-baserad kameraanalys som kör lokalt på Windows (Intel Arc) med **YOLO**-detektering
och ett litet lokalt **vision-LLM** (Ollama) som beskriver scenen — med inbyggd
Home Assistant-integration (MQTT + REST) och **larmstyrd LLM-laddning**.

```
kamera → snapshot (rörelse) → YOLO-detektering → LLM-beskrivning → resultat
```

Sedan v0.5 finns dessutom ett **live-flöde**: en Reolink RTSP-subström läses av
en enda kameraworker, YOLO analyserar den senaste bilden kontinuerligt (AI FPS)
och resultatet (bounding boxes + status) visas i ett Dashboard-first webb-GUI.

```
Reolink → RTSP sub → Camera worker → YOLO (AI FPS) → MJPEG → Dashboard
```

## Funktioner

- **Windows-app med GUI** — eget fönster + taskbar/tray-ikon (pywebview), eller headless som tjänst (NSSM).
- **Live-Dashboard (v0.5)** — en RTSP-session per kamera, auto-återanslut, schemalagd YOLO (AI FPS), annoterad MJPEG-ström och runtime-status (faktisk enhet, inferens, FPS) direkt i webbläsaren.
- **YOLO på Intel Arc** via OpenVINO (`openvino:GPU` → `intel:gpu`) med tydlig GPU-fallback till CPU (visas i Dashboard).
- **GUI-first-inställningar** — kamera, AI FPS, bildstorlek, enhet, display-FPS, JPEG-kvalitet och överlagring (boxar/etiketter/konfidens) ändras från webb-GUI:t och sparas till `.env` utan omstart där det går. Lösenord skickas aldrig tillbaka till webbläsaren.
- **Vision-LLM (Ollama) på Arc** via Vulkan (`OLLAMA_VULKAN=1`).
- **Home Assistant** — MQTT auto-discovery (binary_sensor, sensor, image) + REST.
- **Larmstyrd LLM-laddning** — LLM laddas när HA-larmet är skarpt, laddas ur när det är av (frigör VRAM).
- **HACS-integration** — välj modell/konfidens direkt från HA:s UI.

## Installation (Windows)

Krav: Windows 10/11 eller Server 2025, **Intel Arc B50 Pro** med drivrutin,
Python 3.12 (x64), Git och [Ollama](https://ollama.com).

> **Enklaste vägen (server, headless):** `windows\install.ps1` installerar allt
> i ett — hämtar senaste koden, Python 3.12 (via winget), Ollama + `moondream`
> (via winget), beroenden, `.env` och den schemalagda aktiviteten `CameraAI`.
> Kör du det igen fungerar det som **uppdatering**.
> ```powershell
> powershell -ExecutionPolicy Bypass -File windows\install.ps1
> ```

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

Valfritt — kör headless dygnet runt (ingen GUI, bara webb-API på `0.0.0.0:8000`):

- **Schemalagd aktivitet** (inga extra beroenden, rekommenderas):
  ```powershell
  powershell -ExecutionPolicy Bypass -File windows\install-task.ps1
  ```
  Startar vid datorstart som SYSTEM, startar om automatiskt vid fel och
  loggar till `windows\camera_ai.log`. Fler alternativ (status, start/stopp,
  avinstallera, köra som användare eller med byggd exe): se toppen av scriptet.
- **Windows-tjänst via NSSM** (kräver `nssm.exe`, se `windows\install-service.ps1`):
  ```powershell
  powershell -ExecutionPolicy Bypass -File windows\install-service.ps1
  ```

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

**Server-koden** (laddar ner senaste från GitHub som ZIP — **ingen git krävs** —
installerar ev. nya beroenden och startar om aktiviteten/tjänsten automatiskt):

```powershell
powershell -ExecutionPolicy Bypass -File windows\update.ps1
```

Lokala filer (`.env`, `uploads/`, `media/`, `.venv`, loggar och exporterade
OpenVINO-modeller) skrivs inte över.

**HA-komponenten** (HACS): **HACS → Camera AI → ⋮ → Re-download** (välj
"Redownload" för att hämta senaste) → **Inställningar → Enheter & tjänster →
Camera AI → ⋮ → Ladda om**. Om nya entiteter inte dyker upp, starta om Home
Assistant.

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
| `CAMERA_ENABLED` | Aktivera live-kamera (RTSP → Dashboard) | `false` |
| `CAMERA_NAME` | Kamera-namn (visas i GUI) | `Kamera1` |
| `CAMERA_HOST` | Kamera-IP. Faller tillbaka på `REOLINK_HOST` | (tom) |
| `CAMERA_USER` / `CAMERA_PASS` | RTSP-inloggning (fallback `REOLINK_USER/PASS`) | (tom) |
| `CAMERA_PATH` | RTSP-sökväg — sub-ström rekommenderas för YOLO | `/Preview_01_sub` |
| `CAMERA_RTSP_URL` | Full RTSP-URL som override (innehåller lösenord) | (tom) |
| `CAMERA_RECONNECT` / `CAMERA_RECONNECT_DELAY` | Auto-återanslutning (s) | `true` / `5` |
| `CAMERA_AUTOSTART` | Starta kameran vid appstart (osatt = följer `CAMERA_ENABLED`) | (osatt) |
| `YOLO_STREAM_FPS` | AI FPS — hur ofta YOLO analyserar livebilden | `4` |
| `YOLO_IMG_SIZE` | Bildstorlek live (320/480/640/960/1280) | `640` |
| `LIVE_STREAM_ENABLED` | MJPEG-ström aktiverad | `true` |
| `LIVE_STREAM_FPS` | Display-FPS för strömmen | `10` |
| `LIVE_JPEG_QUALITY` | JPEG-kvalitet (20–100) | `80` |
| `LIVE_SHOW_BOXES/LABELS/CONF` | Visa/dölj överlagring | `true` |

De live-relaterade nycklarna är **GUI-first**: de ändras normalt under
**Inställningar → Kamera / Live-detektering / Live-ström** i webb-GUI:t och
sparas till `.env` automatiskt. En gammal `.env` utan nycklarna fungerar —
alla har defaultvärden (kamera är inaktiverad tills den konfigurerats).

Om Ollama inte körs fungerar YOLO-detekteringen ändå — beskrivningen visar bara ett fel.

## Live Dashboard (v0.5+)

Öppna `http://<server>:8000` — Dashboard är huvudvyn:

- **Live-vy** — MJPEG via `GET /api/live/{kamera}` med YOLO-boxar ritade på servern (lägsta latens, ingen videoqueue — alltid senaste bilden).
- **Status** — kamera/YOLO-tillstånd, modell, konfigurerad vs faktisk enhet (`intel:gpu`), inferens (ms), AI/display-FPS, upplösning.
- **GPU-fallbackvarning** — om `openvino:GPU` inte fungerar visas tydligt "GPU FALLBACK" med faktisk enhet i stället för att tyst köra på CPU.
- **Detected now** — senaste detektionerna med konfidens.
- **Kontroller** — start/stopp av strömmen samt boxar/etiketter/konfidens som ändras live.

API i korthet: `GET/PUT /api/settings`, `GET /api/cameras/status`,
`POST /api/cameras/start|stop`, `POST /api/camera/test`,
`GET /api/live/{kamera}` (MJPEG). Befintliga endpoints (`/api/analyze`,
`/api/history`, `/api/stats`, `/api/health`, HA/Ollama) är oförändrade.

### Live-event → Home Assistant (v0.6)

Nya detektioner i live-strömmen kan skickas till HA som händelser. En händelse
skapas bara när en klass blir **närvarande** (eller kommer tillbaka efter att ha
varit borta i "vila"-tiden) – en statisk/parkerad bil ger alltså **bara en
händelse**, inte ett ständigt larm. Inställningar under **Inställningar →
HA-event** (klasser, vila innan återaktivering, ON-tid, min-intervall,
start-grace) eller i `.env` (`LIVE_EVENT_*`).

Så här får du in det i HA:

1. Sätt `HA_ENABLED=1`, `HA_TRANSPORT=mqtt` samt `HA_MQTT_HOST/USER/PASS`
   (eller `rest` + `HA_REST_URL/TOKEN`) i `.env` och starta om.
2. Aktivera live-kameran (RTSP) och slå på **HA-event** i GUI:t.
3. HA skapar då automatiskt (MQTT auto-discovery) entiteterna:
   - `binary_sensor.camera_ai_<id>_motion` – ON vid ny detektion
   - `sensor.camera_ai_<id>_last_detection` – klasser + konfidens
   - `image.camera_ai_<id>_snapshot` – senaste annoterade bilden
4. I HA: skapa t.ex. en automation som triggar på binary_sensorn och skickar
   en notis med bild, eller lägg bilden på en dashboard-kort.

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
Lägg sedan till integrationen med server-URL `http://<server-ip>:8000`.

När integrationen är tillagd kan du under **Integration → Camera AI → Alternativ**
ändra **alla** runtime-inställningar direkt — de skickas till servern och
tillämpas omedelbart (ingen omstart krävs):

- YOLO-modell och konfidens
- Enhet (`cpu` / `openvino:GPU` / `0`)
- Använd LLM-beskrivning + LLM-modell (t.ex. `moondream`)
- **LLM-prompt** (fritext)
- **Håll LLM i minnet** (`keep_alive`): `-1` = behåll laddad (snabbast), `0` =
  ladda ur direkt (sparar VRAM), eller antal sekunder
- Kamera-entitet för `analyze_camera`

Alla värden syns även i sensorn **sensor.camera_ai_runtime_config** (modell,
konfidens, enhet, prompt, keep_alive, ollama-tillgänglighet).

### Ändra inställningar från en automation

Anropa tjänsten `camera_ai.set_config` med valfria fält — t.ex. hålla LLM i
minnet när du är borta:

```yaml
alias: "Camera AI — behåll LLM i minne när larmet är skarpt"
trigger:
  platform: state
  entity_id: alarm_control_panel.house
  to: "armed_away"
action:
  - service: camera_ai.set_config
    data:
      keep_alive: "-1"   # behåll i minne
  - service: camera_ai.set_config
    data:
      prompt: >-
        Du är en säkerhetskamera. Beskriv på svenska vad du ser med färg,
        märke och antal, t.ex. 'En silverfärgad Volvo V70 och 1 person.'
```

### Automation som "LLM Vision" — men skickad till din server

`camera_ai.analyze_camera` returnerar analysen så att du kan bygga exakt
samma flöde som Home Assistants "LLM Vision"-block, fast mot din Camera AI-
server: fotografera → analysera → hoppa av om inget intressant → skicka
foto/meddelande till Telegram.

```yaml
alias: "Camera AI — rörelse → analys → Telegram"
trigger:
  - platform: state
    entity_id: binary_sensor.garden_person
    to: "on"
  - platform: state
    entity_id: binary_sensor.garden_vehicle
    to: "on"
action:
  # 1. Fotografera och analysera via Camera AI-servern
  - service: camera_ai.analyze_camera
    data:
      camera_entity: camera.garden
    response_variable: analysis

  # 2. Hoppa av om inget av intresse hittades (person/bil/djur)
  - if:
      - condition: template
        value_template: "{{ (analysis.counts.people + analysis.counts.vehicles + analysis.counts.animals) == 0 }}"
    then:
      - stop: "Inget intressant"
    else:
      # 3. Skicka foto + meddelande till Telegram
      - service: telegram_bot.send_photo
        data:
          url: "{{ analysis.annotated_url }}"
          caption: >-
            Detektion på garden! {{ analysis.summary }}
      - service: telegram_bot.send_message
        data:
          message: >-
            {{ analysis.summary }}
            ({{ analysis.counts.people }} personer, {{ analysis.counts.vehicles }} bilar)
mode: single
```

Resultatet från `analyze_camera` / `analyze_url` innehåller: `detections`,
`counts` (`people`/`vehicles`/`animals`/`colors`), `summary`, `description`,
`model`, `inference_ms` och `annotated_url` (absolut URL till den annoterade
bilden på servern, användbar direkt i t.ex. Telegram).

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
