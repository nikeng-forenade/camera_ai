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
VERSION = "0.3.5"


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

# Optional Reolink integration (used by reolink_motion.py)
REOLINK_HOST = os.getenv("REOLINK_HOST", "")
REOLINK_USER = os.getenv("REOLINK_USER", "")
REOLINK_PASS = os.getenv("REOLINK_PASS", "")

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
