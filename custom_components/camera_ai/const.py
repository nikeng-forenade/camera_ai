"""Constants for the Camera AI integration."""

DOMAIN = "camera_ai"

CONF_MODEL = "model"
CONF_CONFIDENCE = "confidence"
CONF_USE_LLM = "use_llm"
CONF_CAMERA = "camera_entity"
CONF_DEVICE = "device"
CONF_LLM_MODEL = "llm_model"
CONF_PROMPT = "prompt"
CONF_KEEP_ALIVE = "keep_alive"

PLATFORMS = ["sensor", "binary_sensor", "camera"]

DEFAULT_MODELS = [
    "yolo11n.pt",
    "yolo11s.pt",
    "yolo11m.pt",
    "yolo11l.pt",
    "yolo11x.pt",
]
DEFAULT_MODEL = "yolo11s.pt"
DEFAULT_CONFIDENCE = 0.30
DEFAULT_USE_LLM = False
DEFAULT_DEVICE = "cpu"
DEFAULT_LLM_MODEL = "moondream"
DEFAULT_PROMPT = (
    "Beskriv på svenska vad som syns på bilden. Räkna personer, fordon och "
    "djur, nämn deras färger och andra tydliga detaljer. Svara med 1-2 korta "
    "meningar."
)
DEVICE_OPTIONS = ["cpu", "openvino:GPU", "0"]
DEVICE_LABELS = {
    "cpu": "CPU",
    "openvino:GPU": "Intel iGPU (OpenVINO)",
    "0": "NVIDIA CUDA (device 0)",
}

# Hur länge vision-LLM:en ska ligga kvar i minnet (keep_alive till Ollama)
DEFAULT_KEEP_ALIVE = "-1"  # behåll i minne (snabbast)
KEEP_ALIVE_OPTIONS = ["-1", "0", "300", "600", "1800", "3600"]
KEEP_ALIVE_LABELS = {
    "-1": "Behåll i minne (snabbast, kräver VRAM)",
    "0": "Ladda ur direkt (spara VRAM)",
    "300": "5 min",
    "600": "10 min",
    "1800": "30 min",
    "3600": "60 min",
}

EVENT_RESULT = "camera_ai_result"
