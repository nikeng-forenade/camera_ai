"""Central configuration for the Camera AI test GUI.

All values can be overridden with environment variables. The GUI can also
override model / confidence / LLM settings per request.
"""
import os
import sys
from pathlib import Path

# In a PyInstaller build (sys.frozen), keep user data (uploads/media/.env/
# models) next to the .exe, while read-only bundled files (static/) come from
# the bundle dir (sys._MEIPASS).
_FROZEN = bool(getattr(sys, "frozen", False))
if _FROZEN:
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = BASE_DIR
STATIC_DIR = BUNDLE_DIR / "static"

# App-version (visas i GUI och HA-integrationen)
VERSION = "0.12.3"


def model_path(name: str) -> str:
    """Resolve a model file name to an absolute path (bundled or next to the app)."""
    for d in (BASE_DIR, BUNDLE_DIR):
        p = d / name
        if p.exists():
            return str(p)
    return name


try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")  # optional .env support (pip install python-dotenv)
except ImportError:
    pass  # dotenv not installed — plain env vars still work

# Folders
UPLOAD_DIR = Path(os.getenv("CAMERA_AI_UPLOAD_DIR", BASE_DIR / "uploads"))
MEDIA_DIR = Path(os.getenv("CAMERA_AI_MEDIA_DIR", BASE_DIR / "media"))
UPLOAD_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)
# Lokal data (flera kameror etc.) - bevaras av install/update (exkluderas i
# robocopy) och är aldrig en del av repot.
DATA_DIR = Path(os.getenv("CAMERA_AI_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(exist_ok=True)
CAMERAS_FILE = DATA_DIR / "cameras.json"


def _env_bool(key: str, default: bool = False) -> bool:
    """Parse a .env boolean (1/true/yes/on = True)."""
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_float(key: str, default: float, lo: float | None = None, hi: float | None = None) -> float:
    """Parse a float env value with optional range clamp."""
    try:
        val = float(os.getenv(key, default))
    except (TypeError, ValueError):
        val = float(default)
    if lo is not None:
        val = max(lo, val)
    if hi is not None:
        val = min(hi, val)
    return val


def _env_int(key: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
    """Parse an int env value with optional range clamp."""
    try:
        val = int(float(os.getenv(key, default)))
    except (TypeError, ValueError):
        val = int(default)
    if lo is not None:
        val = max(lo, val)
    if hi is not None:
        val = min(hi, val)
    return val


def persist_env(values: dict) -> bool:
    """Merge {KEY: value} into BASE_DIR/.env atomically (tmp-fil + replace).

    Kommentarer/ordning i en befintlig .env bevaras; nya nycklar läggs sist.
    Används av API:t så att GUI-ändrade inställningar överlever omstart.
    """
    env_file = BASE_DIR / ".env"
    try:
        lines = (
            env_file.read_text(encoding="utf-8").splitlines()
            if env_file.exists()
            else []
        )
        todo = {str(k): str(v) for k, v in values.items()}
        out: list[str] = []
        for line in lines:
            if "=" in line:
                key = line.split("=", 1)[0].strip()
                if key in todo:
                    out.append(f"{key}={todo.pop(key)}")
                    continue
            out.append(line)
        for key, val in todo.items():
            out.append(f"{key}={val}")
        tmp = env_file.with_name(env_file.name + ".tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        tmp.replace(env_file)
        return True
    except OSError as exc:
        print(f"[config] kunde inte spara .env: {exc}")
        return False

# YOLO defaults
DEFAULT_MODEL = os.getenv("YOLO_MODEL", "yolo11n.pt")
DEFAULT_CONF = float(os.getenv("YOLO_CONF", "0.30"))
# Inference device: "cpu" (default), "0"/"gpu" (NVIDIA CUDA), or
# "openvino"/"openvino:GPU" for Intel iGPU/Arc (needs OpenVINO installed).
YOLO_DEVICE = os.getenv("YOLO_DEVICE", "cpu")

# Small vision LLM (describes the scene).
#   llm_backend = "ollama" | "none"
# Ollama must be installed and running locally (https://ollama.com).
# Small vision models: "moondream" (~1.9B) or "llava" (~7B) — pull with:
#   ollama pull moondream
LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama").strip().lower()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "moondream")
# Hur länge vision-LLM:en ska ligga kvar i minnet (-1 = alltid, 0 = ladda ur,
# annars sekunder). Sätts via GUI/HA och sparas till .env.
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "")
LLM_DEFAULT_PROMPT = os.getenv(
    "LLM_PROMPT",
    "Beskriv på svenska, men BARA detta och inget annat: personer – färg på "
    "kläder; bilar – bilens färg; djur – vilket djur och dess färg. Svara med "
    "en kort mening. Ignorera helt: skyltar, registreringsskyltar, hus, träd, "
    "väder, vägar och allt annat. Om inget av de tre syns, svara 'Inget av "
    "intresse.'",
)

# Optional Reolink integration (used by reolink_motion.py + live camera)
REOLINK_HOST = os.getenv("REOLINK_HOST", "")
REOLINK_USER = os.getenv("REOLINK_USER", "")
REOLINK_PASS = os.getenv("REOLINK_PASS", "")

# ---------------------------------------------------------------------------
# Live-kamera (Reolink RTSP -> YOLO -> Dashboard)
# ---------------------------------------------------------------------------
# Alla nya nycklar har defaultvärden så gamla .env-installationer startar utan
# ändringar. CAMERA_HOST/USER/PASS faller tillbaka på REOLINK_* om de inte är
# satta (migration från äldre .env). GUI skriver de nya nycklarna till .env.
CAMERA_ENABLED = _env_bool("CAMERA_ENABLED", False)
CAMERA_NAME = os.getenv("CAMERA_NAME", "Kamera1").strip() or "Kamera1"
CAMERA_HOST = (os.getenv("CAMERA_HOST", "") or REOLINK_HOST).strip()
CAMERA_USER = (os.getenv("CAMERA_USER", "") or REOLINK_USER).strip()
CAMERA_PASS = os.getenv("CAMERA_PASS", "") or REOLINK_PASS
CAMERA_PATH = (os.getenv("CAMERA_PATH", "/Preview_01_sub") or "/Preview_01_sub").strip()
# Full RTSP-URL som override (t.ex. "rtsp://user:pass@1.2.3.4/Preview_01_sub").
# Sätts den används den i stället för HOST/USER/PASS/PATH.
CAMERA_RTSP_URL = (os.getenv("CAMERA_RTSP_URL", "") or "").strip()
CAMERA_RECONNECT = _env_bool("CAMERA_RECONNECT", True)
CAMERA_RECONNECT_DELAY = _env_int("CAMERA_RECONNECT_DELAY", 5, lo=1, hi=300)
# Autostart: om osatt följer det CAMERA_ENABLED.
CAMERA_AUTOSTART = (
    _env_bool("CAMERA_AUTOSTART", CAMERA_ENABLED)
    if os.getenv("CAMERA_AUTOSTART") is not None
    else CAMERA_ENABLED
)

# Live YOLO-schemaläggning (hur ofta YOLO analyserar den senaste bilden)
YOLO_STREAM_FPS = _env_float("YOLO_STREAM_FPS", 4.0, lo=0.5, hi=30.0)
YOLO_IMG_SIZE = _env_int("YOLO_IMG_SIZE", 640)

# Live-stream (MJPEG till webbläsare)
LIVE_STREAM_ENABLED = _env_bool("LIVE_STREAM_ENABLED", True)
# Starta strömmar (video till GUI) automatiskt vid appstart? Default: av - då
# körs YOLO + HA-event ändå, och man startar strömmen manuellt per kamera.
LIVE_STREAM_AUTOSTART = _env_bool("LIVE_STREAM_AUTOSTART", False)
LIVE_STREAM_FPS = _env_int("LIVE_STREAM_FPS", 10, lo=1, hi=30)
LIVE_JPEG_QUALITY = _env_int("LIVE_JPEG_QUALITY", 80, lo=20, hi=100)
# Visa/dölj detektionsöverlagring (ändras live från GUI)
LIVE_SHOW_BOXES = _env_bool("LIVE_SHOW_BOXES", True)
LIVE_SHOW_LABELS = _env_bool("LIVE_SHOW_LABELS", True)
LIVE_SHOW_CONF = _env_bool("LIVE_SHOW_CONF", True)

# ---------------------------------------------------------------------------
# HA-event vid NYA detektioner i live-strömmen (kräver HA + kamera aktiv).
# Modellen löser "statiska objekt" (t.ex. parkerad bil på uppfarten): en
# händelse skapas bara när en klass blir NÄRVARANDE/kommer tillbaka - inte så
# länge den står stilla. Klasser: komma-separerad lista (YOLO-namn, små bokst).
# ---------------------------------------------------------------------------
LIVE_EVENT_ENABLED = _env_bool("LIVE_EVENT_ENABLED", False)
LIVE_EVENT_CLASSES = (
    os.getenv("LIVE_EVENT_CLASSES", "person,car,cat,dog") or "person"
).strip()
# Hur länge klassen måste vara borta innan den räknas som "lämnad" (re-arms).
LIVE_EVENT_CLEAR_AFTER = _env_float("LIVE_EVENT_CLEAR_AFTER", 5.0, lo=1.0, hi=120.0)
# Hur länge binary_sensorn i HA är ON per händelse.
LIVE_EVENT_HOLD = _env_float("LIVE_EVENT_HOLD", 10.0, lo=1.0, hi=300.0)
# Minsta intervall mellan publiceringar/snapshots (skydd mot spam).
LIVE_EVENT_MIN_INTERVAL = _env_float("LIVE_EVENT_MIN_INTERVAL", 5.0, lo=0.5, hi=300.0)
# Ignorera event de första N sekunderna efter start (låt ev. redan parkerade
# objekt "landa" innan man larmar). 0 = av.
LIVE_EVENT_STARTUP_GRACE = _env_float("LIVE_EVENT_STARTUP_GRACE", 5.0, lo=0.0, hi=120.0)

# ---------------------------------------------------------------------------
# Home Assistant integration
# ---------------------------------------------------------------------------
# Set HA_ENABLED=1 to turn it on. Transport: "mqtt" (recommended, auto-discovery)
# or "rest" (long-lived token).
HA_ENABLED = os.getenv("HA_ENABLED", "").strip().lower() in ("1", "true", "yes")
HA_TRANSPORT = os.getenv("HA_TRANSPORT", "mqtt").strip().lower()
HA_CAMERA_ID = os.getenv("HA_CAMERA_ID", "cam1")

# MQTT broker (Home Assistant's Mosquitto add-on)
HA_MQTT_HOST = os.getenv("HA_MQTT_HOST", "")
HA_MQTT_PORT = int(os.getenv("HA_MQTT_PORT", "1883"))
HA_MQTT_USER = os.getenv("HA_MQTT_USER", "")
HA_MQTT_PASS = os.getenv("HA_MQTT_PASS", "")
HA_DISCOVERY_PREFIX = os.getenv("HA_DISCOVERY_PREFIX", "homeassistant")

# REST API (alternative transport)
HA_REST_URL = os.getenv("HA_REST_URL", "")      # e.g. http://homeassistant.local:8123
HA_REST_TOKEN = os.getenv("HA_REST_TOKEN", "")  # Profile -> long-lived access token

# Larmstyrd LLM-laddning: nar larmet ar skarp (armed) laddas LLM in i minnet
# (keep_alive), nar det ar av (disarmed) plockas den ut for att frigora VRAM.
HA_ALARM_TOPIC = os.getenv("HA_ALARM_TOPIC", "homeassistant/alarm_control_panel/+/state")
OLLAMA_KEEP_ALIVE_ARMED = os.getenv("OLLAMA_KEEP_ALIVE_ARMED", "-1")
OLLAMA_KEEP_ALIVE_DISARMED = os.getenv("OLLAMA_KEEP_ALIVE_DISARMED", "0")
