"""YOLO object detection + small vision-LLM description for the Camera AI GUI.

The analyzer is intentionally decoupled from the web layer so the exact same
pipeline can later be called from the Reolink motion script (reolink_motion.py).
"""
from __future__ import annotations

import base64
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

import config


class YoloAnalyzer:
    """Thin wrapper around Ultralytics YOLO with lazy model loading."""

    def __init__(
        self,
        model: str = config.DEFAULT_MODEL,
        conf: float = config.DEFAULT_CONF,
        device: str = config.YOLO_DEVICE,
    ):
        self.model_name = model
        self.conf = conf
        self.device = device or "cpu"
        self._model = None

    def _ensure_model(self, model: str | None, conf: float | None) -> None:
        """Reload the YOLO model if the requested model/conf changed."""
        model = model or self.model_name
        conf = float(conf) if conf is not None else self.conf
        if self._model is None or model != self.model_name or conf != self.conf:
            from ultralytics import YOLO  # imported lazily so the server still boots without torch

            self._model = YOLO(model)
            self.model_name = model
            self.conf = conf

    def configure(self, model: str | None = None, conf: float | None = None, device: str | None = None) -> None:
        """Update runtime settings (used by POST /api/config from HA)."""
        if model:
            self.model_name = model
        if conf is not None:
            self.conf = float(conf)
        if device:
            self.device = device
        self._model = None  # force reload on next analyze

    def analyze(self, image_path: Path, model: str | None = None, conf: float | None = None) -> dict:
        """Run YOLO on an image and return detections + an annotated image.

        Returns:
            {
                "detections": [{"class": str, "confidence": float, "box": [x1, y1, x2, y2]}, ...],
                "annotated": Path or None,   # path to the saved annotated image
                "model": str,
                "inference_ms": float,
                "error": str | None,
            }
        """
        start = time.perf_counter()
        try:
            self._ensure_model(model, conf)
            results = self._model(str(image_path), conf=self.conf, device=self.device, verbose=False)
            result = results[0]

            detections = []
            if result.boxes is not None:
                names = result.names
                for box in result.boxes:
                    detections.append(
                        {
                            "class": names.get(int(box.cls.item()), "unknown"),
                            "confidence": round(float(box.conf.item()), 4),
                            "box": [round(float(v), 1) for v in box.xyxy[0].tolist()],
                        }
                    )

            annotated = None
            plotted = result.plot()  # BGR numpy array with boxes drawn
            if plotted is not None and plotted.size:
                from PIL import Image

                annotated = config.MEDIA_DIR / f"annotated_{int(time.time()*1000)}.jpg"
                Image.fromarray(plotted[..., ::-1]).save(annotated, quality=92)

            return {
                "detections": detections,
                "annotated": str(annotated) if annotated else None,
                "model": self.model_name,
                "inference_ms": round((time.perf_counter() - start) * 1000, 1),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 - surface anything to the UI
            return {
                "detections": [],
                "annotated": None,
                "model": self.model_name,
                "inference_ms": round((time.perf_counter() - start) * 1000, 1),
                "error": str(exc),
            }


# ---------------------------------------------------------------------------
# Small vision LLM via Ollama (moondream / llava / any vision model)
# ---------------------------------------------------------------------------

_MODELS_CACHE: dict = {"ts": 0.0, "models": []}
_MODELS_TTL = 5.0  # seconds; avoids probing Ollama on every health check


def ollama_models() -> list[dict]:
    """List models available in the local Ollama instance (cached briefly)."""
    now = time.time()
    if now - _MODELS_CACHE["ts"] < _MODELS_TTL:
        return _MODELS_CACHE["models"]
    try:
        req = urllib.request.Request(f"{config.OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=1.5) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        _MODELS_CACHE.update(ts=time.time(), models=data.get("models", []))
    except (urllib.error.URLError, OSError):
        _MODELS_CACHE.update(ts=time.time(), models=[])
    return _MODELS_CACHE["models"]


def resolve_ollama_model(preferred: str) -> str:
    """Pick a vision-capable Ollama model.

    Returns the preferred model if installed, otherwise the first installed
    model that supports 'vision' (e.g. qwen3.6, llava, llama3.2-vision).
    """
    for m in ollama_models():
        if m.get("name") == preferred:
            return preferred
    for m in ollama_models():
        if "vision" in (m.get("capabilities") or []):
            return m["name"]
    return preferred


def active_ollama_model() -> str:
    """The vision model that will actually be used for descriptions."""
    return resolve_ollama_model(config.OLLAMA_MODEL)


def describe_with_ollama(image_path: Path, model: str | None = None, prompt: str | None = None) -> str:
    """Ask a local vision LLM to describe the image. Returns text.

    Raises on failure so the caller can decide how to degrade.
    """
    model = resolve_ollama_model(model or config.OLLAMA_MODEL)
    prompt = prompt or config.LLM_DEFAULT_PROMPT

    with open(image_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("utf-8")

    payload = {
        "model": model,
        "prompt": prompt,
        "images": [b64],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    req = urllib.request.Request(
        f"{config.OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310 - local Ollama
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(
                f"No vision model available in Ollama. Pull one with: "
                f"`ollama pull moondream` (small) or `ollama pull llava`"
            ) from exc
        raise
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Ollama is not running — start it (locally: `ollama serve`, "
            "in the LXC: `docker compose up -d ollama`)."
        ) from exc
    return (data.get("response") or "").strip()


def llm_available() -> bool:
    """Quick check that the Ollama server is reachable (uses the cached probe)."""
    if config.LLM_BACKEND != "ollama":
        return False
    return bool(ollama_models())


# ---------------------------------------------------------------------------
# Deterministic Swedish summary built from YOLO detections.
# Reliable and language-stable — no LLM needed for "Jag ser 1 bil och 1 katt."
# ---------------------------------------------------------------------------

# COCO class -> (singular, plural) in Swedish
_SV_LABELS = {
    "person": ("person", "personer"),
    "car": ("bil", "bilar"),
    "truck": ("lastbil", "lastbilar"),
    "bus": ("buss", "bussar"),
    "motorcycle": ("motorcykel", "motorcyklar"),
    "bicycle": ("cykel", "cyklar"),
    "airplane": ("flygplan", "flygplan"),
    "train": ("tåg", "tåg"),
    "boat": ("båt", "båtar"),
    "cat": ("katt", "katter"),
    "dog": ("hund", "hundar"),
    "bird": ("fågel", "fåglar"),
    "horse": ("häst", "hästar"),
    "cow": ("ko", "kor"),
    "sheep": ("får", "får"),
    "elephant": ("elefant", "elefanter"),
    "bear": ("björn", "björnar"),
    "zebra": ("zebra", "zebror"),
    "giraffe": ("giraff", "giraffer"),
}

# Classes we care about: people, vehicles, animals
_INTEREST_CLASSES = set(_SV_LABELS)


def summarize_detections(detections: list) -> str:
    """Build a short Swedish sentence from YOLO detections, e.g.
    'Jag ser 2 personer, 1 bil och 1 katt.' or 'Jag ser inget av intresse.'
    """
    counts: dict = {}
    for d in detections:
        cls = d.get("class", "")
        if cls in _INTEREST_CLASSES:
            counts[cls] = counts.get(cls, 0) + 1

    if not counts:
        return "Jag ser inget av intresse."

    items = []
    for cls, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        singular, plural = _SV_LABELS.get(cls, (cls, cls))
        items.append(f"{n} {plural if n > 1 else singular}")

    if len(items) == 1:
        return "Jag ser " + items[0] + "."
    return "Jag ser " + ", ".join(items[:-1]) + " och " + items[-1] + "."
