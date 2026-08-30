"""Constants for the Camera AI integration."""

DOMAIN = "camera_ai"

CONF_MODEL = "model"
CONF_CONFIDENCE = "confidence"
CONF_USE_LLM = "use_llm"
CONF_CAMERA = "camera_entity"

PLATFORMS = ["sensor", "binary_sensor", "camera"]

DEFAULT_MODELS = [
    "yolo11n.pt",
    "yolo11s.pt",
    "yolo11m.pt",
    "yolo11l.pt",
    "yolo11x.pt",
]
DEFAULT_MODEL = "yolo11s.pt"
DEFAULT_CONFIDENCE = 0.35
DEFAULT_USE_LLM = False

EVENT_RESULT = "camera_ai_result"
