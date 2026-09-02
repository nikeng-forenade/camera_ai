"""YOLO object detection + small vision-LLM description for the Camera AI GUI.

The analyzer is intentionally decoupled from the web layer so the exact same
pipeline can later be called from the Reolink motion script (reolink_motion.py).
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

import config


# ---------------------------------------------------------------------------
# YOLO-viktnedladdning med synlig status.
#
# När man väljer en modell vars .pt-vikt inte finns lokalt laddar Ultralytics
# ner den automatiskt vid första YOLO()-anropet - men utan att visa något i
# GUI:t. Här laddar vi ner vikten själva (med procent) till config.BASE_DIR så
# att förloppet kan visas i webb-GUI:t. state: idle|running|completed|failed.
# ---------------------------------------------------------------------------
YOLO_DL: dict = {
    "state": "idle",
    "model": None,
    "percent": 0,
    "status": "",
    "error": None,
}
_yolo_dl_lock = threading.Lock()


def yolo_model_installed(model: str) -> bool:
    """True om viktfilen redan finns lokalt (behöver inte laddas ner)."""
    return bool(model) and Path(config.model_path(model)).exists()


def start_yolo_model_download(model: str) -> bool:
    """Starta nedladdning av en saknad YOLO-vikt i bakgrunden (icke-blockerande).

    Returnerar True om en nedladdning startades, annars False (finns redan,
    pågår redan eller ogiltig modell).
    """
    model = (model or "").strip()
    if not model or yolo_model_installed(model):
        return False
    with _yolo_dl_lock:
        if YOLO_DL["state"] == "running":
            return YOLO_DL["model"] == model
        YOLO_DL.update(
            state="running",
            model=model,
            percent=0,
            status=f"Laddar ner {Path(model).name} …",
            error=None,
        )
    threading.Thread(target=_yolo_download_worker, args=(model,), daemon=True).start()
    return True


def ensure_yolo_model(model: str) -> str:
    """Se till att viktfilen finns lokalt; laddar ner och väntar vid behov.

    Returnerar sökvägen som YOLO ska ladda. Höjer RuntimeError om nedladdningen
    misslyckas.
    """
    model = (model or "").strip()
    if yolo_model_installed(model):
        return config.model_path(model)
    if YOLO_DL["state"] == "running" and YOLO_DL["model"] != model:
        raise RuntimeError(
            f"'{YOLO_DL['model']}' laddas ner just nu - försök igen om en stund."
        )
    start_yolo_model_download(model)
    while not yolo_model_installed(model):
        with _yolo_dl_lock:
            state = dict(YOLO_DL)
        if state["state"] == "failed":
            raise RuntimeError(state.get("error") or f"Kunde inte ladda ner {model}.")
        time.sleep(0.1)
    return config.model_path(model)


def _yolo_download_worker(model: str) -> None:
    """Ladda ner modellvikten (med procent) till config.BASE_DIR/<filnamn>."""
    import requests  # requirements.txt

    name = Path(model).name
    dest = config.BASE_DIR / name
    tmp = dest.with_name(f".{name}.part")
    try:
        # Samma release-upplösning som ultralytics använder själv: fråga GitHub
        # efter "latest"-releasen (innehåller både yolo11- och yolo26-vikter).
        from ultralytics.utils.downloads import get_github_assets

        tag, assets = get_github_assets("ultralytics/assets", "latest")
        if name not in assets:
            raise RuntimeError(f"'{name}' finns inte bland Ultralytics assets.")
        url = f"https://github.com/ultralytics/assets/releases/download/{tag}/{name}"
        YOLO_DL["status"] = f"Laddar ner {name} ({tag}) …"
        with requests.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    got += len(chunk)
                    if total:
                        YOLO_DL["percent"] = min(99, round(got * 100 / total))
        if total and got < total:
            raise RuntimeError(f"Ofullständig nedladdning ({got}/{total} bytes).")
        tmp.replace(dest)
        YOLO_DL.update(state="completed", percent=100, status=f"{name} klar", error=None)
    except Exception as exc:  # noqa: BLE001 - status visas i GUI:t
        YOLO_DL.update(state="failed", error=str(exc), status=f"Fel vid nedladdning av {name}")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


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
        self.device = self._normalize_device(device or "cpu")
        self._model = None
        self._lock = threading.Lock()  # guards model (re)load under concurrency

    @staticmethod
    def _normalize_device(device: str) -> str:
        """Map loose device names to something ultralytics accepts.

        A bare ``gpu``/``cuda``/``0`` means NVIDIA CUDA to ultralytics. On
        machines without a usable CUDA GPU this used to fail with an "Invalid
        CUDA device" error, so we translate it to the Intel iGPU via OpenVINO
        instead — the user gets GPU acceleration rather than a crash.
        """
        d = (device or "cpu").strip().lower()
        if d in ("gpu", "cuda", "cuda:0", "0"):
            try:
                import torch

                if torch.cuda.is_available():
                    return "0"
            except ImportError:
                pass
            return "openvino:GPU"  # no NVIDIA GPU → Intel iGPU via OpenVINO
        return device

    def _resolve_model(self, model: str) -> str:
        """Return the path to load, exporting to OpenVINO format if needed.

        OpenVINO needs the model exported once to a ``<name>_openvino_model``
        folder — a plain ``.pt`` file doesn't accept an OpenVINO device string
        in ultralytics (it errors with "Invalid CUDA device"). The exported
        folder is cached on disk, so the export only runs once per model.
        """
        if not self.device.startswith("openvino:"):
            return model
        path = Path(model)
        if path.suffix.lower() != ".pt":
            return model  # already a non-.pt artifact (e.g. an exported folder)
        from ultralytics import YOLO  # lazy import, mirrors _ensure_model

        ov_dir = path.with_name(path.stem + "_openvino_model")
        if not ov_dir.exists():
            print(f"[analyzer] exporting {model} to OpenVINO (one-time)…")
            YOLO(model).export(format="openvino", device="cpu", verbose=False)
        return str(ov_dir)

    def _infer_device(self) -> str:
        """Map the config device to the string ultralytics understands.

        For OpenVINO models ultralytics expects an ``intel:<device>`` string
        (e.g. ``intel:gpu``). Passing a bare ``GPU``/``gpu`` falls into the
        NVIDIA CUDA check and fails on machines without CUDA.
        """
        if self.device.startswith("openvino:"):
            dev = (self.device.split(":", 1)[1] or "CPU").lower()
            return f"intel:{dev}"  # ultralytics OpenVINO device, e.g. 'intel:gpu'
        return self.device

    def _ensure_model(self, model: str | None, conf: float | None) -> None:
        """Reload the YOLO model if the requested model/conf changed."""
        with self._lock:
            model = model or self.model_name
            conf = float(conf) if conf is not None else self.conf
            if self._model is None or model != self.model_name or conf != self.conf:
                from ultralytics import YOLO  # imported lazily so the server still boots without torch

                # Saknas viktfilen laddas den ner först (med synlig status i
                # GUI:t) istället för att Ultralytics gör det tyst i bakgrunden.
                pt_path = ensure_yolo_model(model)
                self._model = YOLO(self._resolve_model(pt_path))
                self.model_name = model
                self.conf = conf

    def configure(self, model: str | None = None, conf: float | None = None, device: str | None = None) -> None:
        """Update runtime settings (used by POST /api/config from HA)."""
        with self._lock:
            if model:
                self.model_name = model
            if conf is not None:
                self.conf = float(conf)
            if device:
                self.device = self._normalize_device(device)
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
            yolo = self._model  # local ref — safe even if configure() clears _model

            # Device candidates: preferred first, then graceful fallbacks.
            # OpenVINO models in ultralytics use 'intel:<device>' (e.g. intel:gpu);
            # a bare 'GPU'/'gpu' hits the NVIDIA CUDA check and fails on machines
            # without CUDA, so we never pass that.
            candidates = [self._infer_device()]
            if self.device.startswith("openvino:"):
                candidates += ["intel:cpu", "cpu"]  # OpenVINO CPU, then torch CPU

            last_exc = None
            used_device = candidates[0]
            for used_device in candidates:
                try:
                    results = yolo(str(image_path), conf=self.conf, device=used_device, verbose=False)
                    last_exc = None
                    break
                except Exception as exc:  # noqa: BLE001 - try the next candidate
                    last_exc = exc
                    print(f"[analyzer] device '{used_device}' failed: {exc}")
            if last_exc is not None:
                raise last_exc
            result = results[0]
            # Log which device actually ran inference (visible in `docker logs camera-ai`)
            print(
                f"[analyzer] {self.model_name} on {used_device} "
                f"— {round((time.perf_counter() - start) * 1000, 1)} ms"
            )

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

            # Dominant colour for vehicles (sampled from the image pixels)
            if detections:
                from PIL import Image as _PILImage

                with _PILImage.open(image_path) as img:
                    for d in detections:
                        if d["class"] in VEHICLE_CLASSES:
                            d["color"] = vehicle_color(img, d["box"])

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

_MODELS_CACHE: dict = {"ts": 0.0, "models": [], "error": None}
_MODELS_TTL = 5.0  # seconds; avoids probing Ollama on every health check


def ollama_models() -> list[dict]:
    """List models available in the local Ollama instance (cached briefly)."""
    now = time.time()
    if now - _MODELS_CACHE["ts"] < _MODELS_TTL:
        return _MODELS_CACHE["models"]
    try:
        req = urllib.request.Request(f"{config.OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5.0) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        _MODELS_CACHE.update(ts=time.time(), models=data.get("models", []), error=None)
    except (urllib.error.URLError, OSError) as exc:
        _MODELS_CACHE.update(ts=time.time(), models=[], error=str(exc))
    return _MODELS_CACHE["models"]


def ollama_models_error() -> str | None:
    """Senaste fel vid modellista (None = OK)."""
    return _MODELS_CACHE.get("error")


def resolve_ollama_model(preferred: str) -> str:
    """Pick a vision-capable Ollama model.

    Returnerar det INSTALLERADE modellnamnet (t.ex. 'moondream:latest') som
    matchar 'preferred' OCH är vision-kapabel — så Ollama aldrig får en tag som
    inte finns eller en textmodell. Är den valda modellen inte vision-kapabel
    (t.ex. korrupt 'llama3.2-vision') väljs den första vision-kapabla istället.
    """
    base = (preferred or "").split(":")[0]
    models = ollama_models()
    # 1) Föredragen modell, men bara om den är vision-kapabel
    for m in models:
        name = m.get("name", "")
        if (name == preferred or name.split(":")[0] == base) and "vision" in (m.get("capabilities") or []):
            return name
    # 2) Annars: första vision-kapabla modellen (hoppa över textmodeller)
    for m in models:
        if "vision" in (m.get("capabilities") or []):
            return m["name"]
    # 3) Inga vision-modeller alls: använd föredragen ändå (best effort)
    for m in models:
        name = m.get("name", "")
        if name == preferred or name.split(":")[0] == base:
            return name
    return preferred


def active_ollama_model(preferred: str | None = None) -> str:
    """The vision model that will actually be used for descriptions."""
    return resolve_ollama_model(preferred or config.OLLAMA_MODEL)


_LLM_KEEP_ALIVE: str | int | None = None  # None = använd Ollamas default (5m)


def _ollama_keep_alive(value) -> str | int | None:
    """Konvertera vår keep_alive till format Ollama accepterar.

    Ollama tolkar:
      - sträng som Go-duration (måste ha enhet, t.ex. "300s", "5m")
      - nummer som nanosekunder (negativt = behåll laddad oändligt)
    Därför: "-1" -> -1 (nummer), "0" -> 0 (nummer), "300" -> "300s".
    """
    if value is None:
        return None
    s = str(value).strip()
    if s in ("-1", "-1.0"):
        return -1
    if s in ("0", "0.0"):
        return 0
    try:
        n = int(float(s))
        return f"{n}s"
    except ValueError:
        return s  # redan en Go-duration, t.ex. "5m"


def set_llm_keep_alive(keep_alive: str | None, model: str | None = None) -> None:
    """Satt keep_alive for LLM-anrop och applicera direkt (ladda/plocka ut).

    keep_alive="-1" laddar modellen och haller den kvar; "0" plockar ut den.
    """
    global _LLM_KEEP_ALIVE
    _LLM_KEEP_ALIVE = _ollama_keep_alive(keep_alive)
    if _LLM_KEEP_ALIVE is None:
        return
    model = resolve_ollama_model(model or config.OLLAMA_MODEL)
    try:
        payload = {"model": model, "prompt": "ok", "stream": False, "keep_alive": _LLM_KEEP_ALIVE}
        req = urllib.request.Request(
            f"{config.OLLAMA_URL}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30):  # noqa: S310 - lokal Ollama
            pass
    except Exception as exc:  # noqa: BLE001 - ej kritiskt
        print(f"[ollama] keep_alive '{keep_alive}' apply failed: {exc}")


def _small_vision_model(exclude: str | None = None) -> str | None:
    """Return a small vision-capable model (prefer moondream) for fallback."""
    excluded = (exclude or "").split(":")[0]
    prefer = ("moondream",)
    for m in ollama_models():
        name = m.get("name", "")
        base = name.split(":")[0]
        if base != excluded and base in prefer and "vision" in (m.get("capabilities") or []):
            return name
    for m in ollama_models():
        name = m.get("name", "")
        base = name.split(":")[0]
        if base != excluded and "vision" in (m.get("capabilities") or []):
            return name
    return None


def describe_with_ollama(image_path: Path, model: str | None = None, prompt: str | None = None) -> str:
    """Ask a local vision LLM to describe the image. Returns text.

    Raises on failure so the caller can decide how to degrade.
    """
    model = resolve_ollama_model(model or config.OLLAMA_MODEL)
    prompt = prompt or config.LLM_DEFAULT_PROMPT

    with open(image_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("utf-8")

    def _generate(m: str) -> str:
        payload = {
            "model": m,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0.2},
        }
        if _LLM_KEEP_ALIVE is not None:
            payload["keep_alive"] = _LLM_KEEP_ALIVE
        req = urllib.request.Request(
            f"{config.OLLAMA_URL}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310 - local Ollama
            data = json.loads(resp.read().decode("utf-8"))
        return (data.get("response") or "").strip()

    try:
        return _generate(model)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = exc.read().decode("utf-8", "replace")
            detail = body[:200].strip()
        except Exception:  # noqa: BLE001 - bästa möjliga
            pass
        if exc.code == 500:
            # Modellen kunde inte laddas/generera (vanligen för lite GPU-minne).
            # Självläkande fallback: testa en liten känd vision-modell först.
            fallback = _small_vision_model(exclude=model)
            if fallback:
                try:
                    print(f"[llm] '{model}' gav HTTP 500 — försöker med '{fallback}'")
                    return _generate(fallback)
                except Exception:  # noqa: BLE001 - fallback misslyckades också
                    pass
            raise RuntimeError(
                f"Vision LLM error (500): modellen '{model}' på Ollama "
                f"({config.OLLAMA_URL}) kunde inte generera svar. Vanligaste "
                f"orsak: för lite GPU-minne för en stor modell. Detalj från "
                f"Ollama: {detail or 'Internal Server Error'}. Prova en mindre "
                f"modell (t.ex. moondream)."
            ) from exc
        if exc.code in (400, 404):
            raise RuntimeError(
                f"Vision LLM error ({exc.code}): modellen '{model}' på Ollama "
                f"({config.OLLAMA_URL}) svarade: {detail or 'Bad Request'}. "
                "Kontrollera att modellen är nedladdad i DEN Ollama-instansen "
                "(ollama list) och att den stödjer bilder (vision)."
            ) from exc
        raise
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Ollama is not running — start it (locally: `ollama serve`, "
            "in the LXC: `docker compose up -d ollama`)."
        ) from exc


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
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle"}
ANIMAL_CLASSES = {
    "cat", "dog", "bird", "horse", "cow", "sheep",
    "elephant", "bear", "zebra", "giraffe",
}


def categorize_detections(detections: list) -> dict:
    """Count people/animals/vehicles and list vehicle colours."""
    people = sum(1 for d in detections if d.get("class") == "person")
    vehicles = sum(1 for d in detections if d.get("class") in VEHICLE_CLASSES)
    animals = sum(1 for d in detections if d.get("class") in ANIMAL_CLASSES)
    colors = [
        d["color"]
        for d in detections
        if d.get("class") in VEHICLE_CLASSES and d.get("color") and d["color"] != "okänd"
    ]
    return {"people": people, "vehicles": vehicles, "animals": animals, "colors": colors}

# Swedish colour name -> plural (adjective agreement: "röd bil" / "röda bilar")
_COLOR_SV_PLURAL = {
    "röd": "röda", "orange": "orange", "gul": "gula", "grön": "gröna",
    "cyan": "cyan", "blå": "blå", "lila": "lila", "rosa": "rosa",
    "vit": "vita", "grå": "grå", "svart": "svarta",
}


def _sv_color_name(h: int, s: int, v: int) -> str:
    """Map one HSV pixel (PIL, 0-255) to a Swedish colour name."""
    if s < 40:  # achromatic: white / black / grey
        if v > 235:
            return "vit"
        if v < 45:
            return "svart"
        return "grå"
    hue = h * 360 / 255
    if hue < 15 or hue >= 345:
        return "röd"
    if hue < 40:
        return "orange"
    if hue < 65:
        return "gul"
    if hue < 170:
        return "grön"
    if hue < 200:
        return "cyan"
    if hue < 265:
        return "blå"
    if hue < 300:
        return "lila"
    if hue < 345:
        return "rosa"
    return "röd"


def vehicle_color(img, box) -> str:
    """Dominant colour of a detected vehicle, sampled from the body band.

    Robust to colour cast / low-light security feeds: a colour is only reported
    when clearly saturated (S > 100) pixels make up the majority of the body;
    otherwise the vehicle is white / black / grey by brightness.
    """
    try:
        x1, y1, x2, y2 = (int(round(v)) for v in box)
        w = max(1, x2 - x1)
        h = max(1, y2 - y1)
        top = int(y1 + h * 0.3)   # skip roof / sky
        bottom = int(y1 + h * 0.75)  # skip wheels / shadow
        crop = img.crop((x1, top, x2, bottom)).convert("RGB").resize((48, 20))
        hsv = crop.convert("HSV")
        px = hsv.load()
        pixels = [px[x, y] for y in range(hsv.height) for x in range(hsv.width)]
        if not pixels:
            return "okänd"

        chroma = [(hh, ss, vv) for hh, ss, vv in pixels if ss > 100]
        v_avg = sum(p[2] for p in pixels) / len(pixels)

        if len(chroma) / len(pixels) < 0.5:
            # Mostly neutral (white with a colour cast included) -> brightness
            if v_avg > 180:
                return "vit"
            if v_avg < 55:
                return "svart"
            return "grå"

        counts: dict = {}
        for hh, ss, vv in chroma:
            name = _sv_color_name(hh, ss, vv)
            counts[name] = counts.get(name, 0) + 1
        if not counts:
            return "grå"
        return max(counts, key=counts.get)
    except Exception:  # noqa: BLE001 - colour is best-effort
        return "okänd"


def summarize_detections(detections: list) -> str:
    """Build a short Swedish sentence from YOLO detections, e.g.
    'Jag ser 2 personer, 1 röd bil och 1 katt.' or 'Jag ser inget av intresse.'
    """
    counts: dict = {}
    for d in detections:
        cls = d.get("class", "")
        if cls not in _INTEREST_CLASSES:
            continue
        color = d.get("color") if cls in VEHICLE_CLASSES else None
        key = (cls, color)
        counts[key] = counts.get(key, 0) + 1

    if not counts:
        return "Jag ser inget av intresse."

    items = []
    for (cls, color), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        singular, plural = _SV_LABELS.get(cls, (cls, cls))
        noun = plural if n > 1 else singular
        if color and color != "okänd":
            c = _COLOR_SV_PLURAL.get(color, color) if n > 1 else color
            items.append(f"{n} {c} {noun}")
        else:
            items.append(f"{n} {noun}")

    if len(items) == 1:
        return "Jag ser " + items[0] + "."
    return "Jag ser " + ", ".join(items[:-1]) + " och " + items[-1] + "."
