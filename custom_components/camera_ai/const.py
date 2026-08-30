"""Constants for the Camera AI integration."""

DOMAIN = "camera_ai"

CONF_MODEL = "model"
CONF_CONFIDENCE = "confidence"
CONF_USE_LLM = "use_llm"
CONF_CAMERA = "camera_entity"
CONF_DEVICE = "device"
CONF_LLM_MODEL = "llm_model"
CONF_PROMPT = "prompt"

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
    "Svara på svenska med EN kort mening om vad du ser: bara personer, bilar "
    "och djur, med antal. Exempel: 'Jag ser 2 personer, 1 bil och 1 katt.' "
    "Ser du inget av detta, svara 'Jag ser inget av intresse.' Nämn inget annat."
)
DEVICE_OPTIONS = ["cpu", "openvino:GPU", "0"]
DEVICE_LABELS = {
    "cpu": "CPU",
    "openvino:GPU": "Intel iGPU (OpenVINO)",
    "0": "NVIDIA CUDA (device 0)",
}

EVENT_RESULT = "camera_ai_result"
