"""Camera AI test GUI — upload pictures, run YOLO detection, get a small-LLM description.

Run:  python app.py        (then open http://127.0.0.1:8000)
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import importlib.util
import subprocess
import sys
import json
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from analyzer import (
    YOLO_DL,
    YoloAnalyzer,
    active_ollama_model,
    categorize_detections,
    describe_with_ollama,
    llm_available,
    ollama_models,
    ollama_models_error,
    set_llm_keep_alive,
    start_yolo_model_download,
    summarize_detections,
    yolo_model_installed,
)
from camera_stream import CameraPool, CameraWorker, scan_camera, test_rtsp
from ha_client import HAClient

analyzer = YoloAnalyzer()
ha = HAClient(config)
pool = CameraPool(analyzer)  # flera live-kameror: RTSP -> YOLO -> Dashboard


# Vilka .env-nycklar (globala inställningar) som ska skrivas tillbaka till
# config-modulen så att ny-/kommande kameror får samma runtime-värden.
_BOOL_ENV = {
    "LIVE_STREAM_ENABLED", "LIVE_SHOW_BOXES", "LIVE_SHOW_LABELS",
    "LIVE_SHOW_CONF", "LIVE_EVENT_ENABLED", "MOTION_GATE_ENABLED",
    "CAMERA_AUTH_ENABLED",
}

# .env-nycklar som ska sättas som STRÄNG (inte float) vid runtime-synk.
_STR_ENV = {"CAMERA_FILTER_CLASS_SCORES", "CAMERA_AUTH_USERNAME", "CAMERA_AUTH_PASSWORD_HASH"}
# .env-nyckel -> config-attribut när namnen skiljer sig åt.
_ENV_ATTR_ALIAS = {
    "CAMERA_FILTER_MIN_SCORE": "FILTER_MIN_SCORE",
    "CAMERA_FILTER_MIN_AREA": "FILTER_MIN_AREA",
    "CAMERA_FILTER_MAX_AREA": "FILTER_MAX_AREA",
    "CAMERA_FILTER_CLASS_SCORES": "FILTER_CLASS_SCORES",
}


def _sync_config_attrs(env_write: dict) -> None:
    """Sätt tillbaka sparade globala värden på config-modulen (runtime)."""
    for key, val in env_write.items():
        attr = _ENV_ATTR_ALIAS.get(key, key)
        if not hasattr(config, attr):
            continue
        try:
            if key in _BOOL_ENV:
                setattr(config, attr, str(val).strip().lower() in ("1", "true", "yes", "on"))
            elif key in _STR_ENV or not isinstance(getattr(config, attr), (int, float)):
                setattr(config, attr, str(val))
            elif isinstance(getattr(config, attr), int):
                setattr(config, attr, int(float(val)))
            else:
                setattr(config, attr, float(val))
        except (TypeError, ValueError):
            pass


def _live_event_publish(payload: dict) -> None:
    """Publicera ett live-event (ny detektion) till Home Assistant.

    Anropas från kameraworkerns loop-tråd. Sparar snapshot (om medskickad) till
    MEDIA_DIR och återanvänder den befintliga HA-klienten (MQTT/REST). Aldrig
    krascha - event är icke-kritiskt.
    """
    kind = payload.get("kind")
    detections = payload.get("detections") or []
    summary = payload.get("summary") or ""
    annotated_path = None
    image_error = None
    jpeg = payload.get("jpeg")
    if jpeg:
        try:
            p = config.MEDIA_DIR / f"event_{int(time.time() * 1000)}.jpg"
            p.write_bytes(jpeg)
            annotated_path = str(p)
        except OSError as exc:  # noqa: BLE001 - snapshot är valfri
            image_error = str(exc)
            print(f"[event] kunde inte spara snapshot: {exc}")
    else:
        image_error = "Ingen JPEG mottogs från kameraworkern"
        print(f"[event] snapshot saknas: {image_error}")
    if kind == "event":
        EVENT_LOG.append({
            "id": uuid.uuid4().hex,
            "ts": payload.get("ts", time.time()),
            "camera": payload.get("camera_name") or "Kamera",
            "classes": payload.get("classes") or [],
            "detections": detections,
            "summary": summary,
            "image": annotated_path,
            "image_error": image_error,
        })
        try:
            EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with EVENT_LOG_LOCK:
                tmp_path = EVENT_LOG_PATH.with_suffix(".json.tmp")
                tmp_path.write_text(
                    json.dumps(list(EVENT_LOG), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                tmp_path.replace(EVENT_LOG_PATH)
        except OSError as exc:  # noqa: BLE001 - loggen får inte stoppa eventet
            print(f"[event] kunde inte spara historik: {exc}")
        try:
            _prune_event_media()
        except Exception as exc:  # noqa: BLE001 - städning får aldrig stoppa eventet
            print(f"[event] mediastädning misslyckades: {exc}")
    try:
        ha.publish_result(
            detections=detections,
            description=summary,
            annotated_path=annotated_path,
            camera=payload.get("camera_name"),
        )
        if kind == "event":
            print(f"[ha] live-event: {summary}")
    except Exception as exc:  # noqa: BLE001 - event ska aldrig stoppa workern
        print(f"[ha] live-event misslyckades: {exc}")

# Runtime settings — changeable from the HA integration via POST /api/config
RUNTIME = {
    "model": config.DEFAULT_MODEL,
    "conf": config.DEFAULT_CONF,
    "device": config.YOLO_DEVICE,
    "use_llm": False,
    "llm_model": config.OLLAMA_MODEL,
    "prompt": config.LLM_DEFAULT_PROMPT,
    # LLM i minne: None = Ollamas default (5 min), "-1" = behåll laddad,
    # "0" = ladda ur direkt, annars antal sekunder.
    "keep_alive": config.OLLAMA_KEEP_ALIVE or None,
}

# In-memory analysis history for stats / web GUI (keeps the last N results)
HISTORY: deque = deque(maxlen=50)
EVENT_LOG_PATH = config.BASE_DIR / "data" / "events.json"
EVENT_LOG_LOCK = threading.Lock()
LPR_LOG_PATH = config.BASE_DIR / "data" / "lpr.json"
LPR_LOG_LOCK = threading.Lock()


def _load_event_log() -> deque:
    try:
        items = json.loads(EVENT_LOG_PATH.read_text(encoding="utf-8"))
        if isinstance(items, list):
            return deque(items[-50:], maxlen=50)
    except (OSError, ValueError, TypeError):
        pass
    return deque(maxlen=50)


EVENT_LOG: deque = _load_event_log()


def _load_lpr_log() -> deque:
    try:
        items = json.loads(LPR_LOG_PATH.read_text(encoding="utf-8"))
        if isinstance(items, list):
            return deque(items[-100:], maxlen=100)
    except (OSError, ValueError, TypeError):
        pass
    return deque(maxlen=100)


LPR_LOG: deque = _load_lpr_log()


def _lpr_publish(payload: dict) -> None:
    image = None
    jpeg = payload.get("jpeg")
    if jpeg:
        try:
            path = config.MEDIA_DIR / f"lpr_{int(time.time() * 1000)}.jpg"
            path.write_bytes(jpeg)
            image = str(path)
        except OSError:
            pass
    LPR_LOG.append({
        "id": uuid.uuid4().hex,
        "ts": payload.get("ts", time.time()),
        "camera": payload.get("camera_name") or "Kamera",
        "plate": payload.get("plate") or "",
        "confidence": payload.get("confidence", 0.0),
        "image": image,
    })
    try:
        LPR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LPR_LOG_LOCK:
            tmp = LPR_LOG_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(list(LPR_LOG), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(LPR_LOG_PATH)
    except OSError as exc:
        print(f"[lpr] kunde inte spara historik: {exc}")
START_TIME = time.time()


def _prune_event_media() -> int:
    """Ta bort eventbilder (event_*.jpg) som inte längre refereras av loggen.

    events.json håller max 50 event, så bilder för äldre rader tas bort för att
    media/ inte ska växa oändligt. Körs vid start och efter varje nytt event.
    """
    referenced = set()
    for ev in list(EVENT_LOG):
        img = ev.get("image")
        if img:
            referenced.add(Path(img).name)
    removed = 0
    try:
        for p in config.MEDIA_DIR.glob("event_*.jpg"):
            if p.name not in referenced:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
    except OSError:
        pass
    return removed


class _ConfigIn(BaseModel):
    """Accepted fields for POST /api/config."""

    model: str | None = None
    conf: float | None = None
    device: str | None = None
    use_llm: bool | None = None
    llm_model: str | None = None
    prompt: str | None = None
    keep_alive: str | int | None = None


def _is_prompt_echo(text: str, prompt: str) -> bool:
    """True om vision-LLM:en bara upprepar prompten istället för att beskriva
    bilden. Korta svar som prompten själv instruerar (t.ex. 'Inget av
    intresse.') räknas INTE som eko - bara när en stor del av prompten
    upprepas."""
    import re

    if not text or not prompt:
        return False
    norm = lambda s: re.sub(r"[^a-zåäö0-9 ]", " ", s.lower())
    t, p = norm(text), norm(prompt)
    if not t or not p:
        return False
    if p in t:  # hela prompten upprepad i svaret = tydligt eko
        return True
    if t in p:  # svaret är en del av prompten
        return len(t) >= max(10, len(p) * 0.5)
    return False


_STOPWORDS = frozenset({
    "en", "ett", "och", "att", "med", "på", "i", "för", "av", "som", "är",
    "det", "den", "de", "till", "har", "man", "men", "inte", "eller", "om",
    "vid", "från", "under", "över", "detta", "the", "a", "an", "and", "with",
    "of", "in", "on", "for", "to", "is", "are",
})


def _llm_says_nothing(text: str) -> bool:
    """True om LLM:en säger att det inte finns något av intresse
    (t.ex. den instruerade frasen 'Inget av intresse.')."""
    t = (text or "").lower()
    if "inget av intresse" in t or "nothing of interest" in t:
        return True
    # Kort, nekande svar ("Inget.", "Ingenting.", "Nothing.")
    if len(t.strip()) <= 20 and any(w in t for w in ("inget", "ingenting", "nothing", "none")):
        return True
    return False


def _is_low_quality(text: str) -> bool:
    """True om LLM-svaret är repetitivt/skräp, t.ex. 'Topshop 1. Topshop 2. …'.

    Stoppord (och, en, på, the, …) räknas inte - annars fälls naturliga svar
    felaktigt. Ett innehållsord som dominerar (t.ex. "topshop") = skräp.
    """
    import re

    if not text:
        return True
    words = [w for w in re.findall(r"[a-zåäö0-9]+", text.lower()) if w not in _STOPWORDS]
    if not words:
        return False
    if len(words) < 3:
        return False
    freq: dict = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    top = max(freq.values())
    # Ett innehållsord som dominerar svaret -> repetitivt/skräp
    return top > 4 or top >= len(words) // 2


# .env-nycklar som ska sparas vid POST /api/config (så inställningarna överlever omstart)
_ENV_KEYS = {
    "model": "YOLO_MODEL",
    "conf": "YOLO_CONF",
    "device": "YOLO_DEVICE",
    "llm_model": "OLLAMA_MODEL",
    "prompt": "LLM_PROMPT",
    "keep_alive": "OLLAMA_KEEP_ALIVE",
}


def _persist_env(changes: dict) -> None:
    """Spara ändrade inställningar till .env så de överlever omstart."""
    to_write = {}
    for k, v in changes.items():
        env_key = _ENV_KEYS.get(k)
        if env_key is not None:
            to_write[env_key] = str(v)
    if not to_write:
        return
    if config.persist_env(to_write):
        print(f"[config] sparade till .env: {', '.join(to_write)}")
    else:
        print(f"[config] kunde inte spara .env")


def _on_ha_alarm(state: str) -> None:
    """Larm skarpt -> ladda LLM (klar direkt), larm av -> plocka ut den."""
    armed = state in ("armed_away", "armed_home", "armed_night", "armed_custom_bypass", "arming", "pending")
    keep_alive = config.OLLAMA_KEEP_ALIVE_ARMED if armed else config.OLLAMA_KEEP_ALIVE_DISARMED
    print(f"[ha] alarm state '{state}' -> ollama keep_alive {keep_alive}")
    try:
        set_llm_keep_alive(keep_alive)
    except Exception as exc:  # noqa: BLE001 - aldrig krascha servern
        print(f"[ha] set_llm_keep_alive failed: {exc}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    ha.on_alarm_state(_on_ha_alarm)
    try:
        ha.connect()
    except Exception as exc:  # noqa: BLE001 - never crash the server on HA failure
        print(f"[ha] startup connect failed: {exc}")
    # Applicera ev. sparad keep_alive från .env så GUI/HA-inställningen gäller
    if RUNTIME.get("keep_alive") is not None:
        try:
            set_llm_keep_alive(str(RUNTIME["keep_alive"]))
        except Exception as exc:  # noqa: BLE001
            print(f"[config] startup keep_alive apply failed: {exc}")
    # Ladda kameraregister (data/cameras.json) + starta aktiverade kameror.
    # Live-kamerorna kör kontinuerligt på servern oavsett om en webbläsare är
    # öppen - HA-event och YOLO fortsätter ändå.
    try:
        pool.load()
        pool.on_event(_live_event_publish)
        pool.on_lpr(_lpr_publish)
        pool.start_all()
        # Ström (video till GUI) ska vara AV vid uppstart - men YOLO + HA-event
        # fortsätter. Starta manuellt, eller sätt LIVE_STREAM_AUTOSTART=true.
        if not config.LIVE_STREAM_AUTOSTART:
            for _w in pool.all():
                try:
                    if _w.running:
                        _w.update_live({"enabled": False})
                except Exception:  # noqa: BLE001 - en kamera ska inte stoppa resten
                    pass
            print("[camera] live-strömmar av vid uppstart (detektering körs)")
        print(f"[camera] {pool.count()} kameror i registret - aktiverade startade")
    except Exception as exc:  # noqa: BLE001 - API:t ska starta ändå
        print(f"[camera] worker start misslyckades: {exc}")
    # Rensa gamla eventbilder som inte längre refereras av loggen (retention)
    try:
        removed = _prune_event_media()
        if removed:
            print(f"[media] städade {removed} gamla eventbilder vid start")
    except Exception as exc:  # noqa: BLE001
        print(f"[media] städning vid start misslyckades: {exc}")
    yield
    # Graceful shutdown: stoppa trådar + frigör RTSP
    try:
        pool.stop_all()
        print("[camera] workers stoppade")
    except Exception as exc:  # noqa: BLE001
        print(f"[camera] worker stop misslyckades: {exc}")


app = FastAPI(title="Camera AI", version=config.VERSION, lifespan=lifespan)


def _basic_auth_ok(request: Request) -> bool:
    if not config.AUTH_ENABLED:
        return True
    value = request.headers.get("authorization", "")
    if not value.lower().startswith("basic "):
        return False
    try:
        raw = base64.b64decode(value.split(" ", 1)[1], validate=True).decode("utf-8")
        username, password = raw.split(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return False
    return hmac.compare_digest(username, config.AUTH_USERNAME) and config.verify_auth_password(
        password, config.AUTH_PASSWORD_HASH
    )


@app.middleware("http")
async def require_basic_auth(request: Request, call_next):
    if _basic_auth_ok(request):
        return await call_next(request)
    return Response(
        content="Authentication required",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Camera AI"'},
        media_type="text/plain",
    )

ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@app.get("/api/config")
def get_runtime_config():
    return {**RUNTIME, "ollama_available": llm_available()}


@app.post("/api/config")
def set_runtime_config(payload: _ConfigIn):
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    RUNTIME.update(changes)
    analyzer.configure(
        model=RUNTIME["model"], conf=RUNTIME["conf"], device=RUNTIME["device"]
    )
    # Väljs en ny YOLO-modell vars vikt saknas startas nedladdningen direkt,
    # så att GUI:t kan visa förloppet (annars sker den tyst vid första analysen).
    if changes.get("model"):
        start_yolo_model_download(str(RUNTIME["model"]))
    # Applicera LLM keep_alive direkt (ladda / plocka ut modellen)
    if changes.get("keep_alive") is not None:
        try:
            set_llm_keep_alive(str(changes["keep_alive"]))
        except Exception as exc:  # noqa: BLE001 - icke-kritiskt, returnera ändå
            print(f"[config] keep_alive apply failed: {exc}")
    _persist_env(changes)
    return {**RUNTIME}


# ---------------------------------------------------------------------------
# Ollama-modellnedladdning (pull) med status/progress
# ---------------------------------------------------------------------------
PULL: dict = {
    "state": "idle",  # idle | running | completed | failed
    "model": None,
    "percent": 0,
    "status": "",
    "error": None,
}
_pull_lock = threading.Lock()

OCR_INSTALL: dict = {
    "state": "idle",  # idle | running | completed | failed
    "phase": "idle",   # download | install | complete | error
    "engine": None,
    "package": None,
    "status": "",
    "error": None,
    "error_code": None,
}
_ocr_install_lock = threading.Lock()


def _ocr_engine_installed(engine: str) -> bool:
    return (
        importlib.util.find_spec("easyocr") is not None
        if engine == "easyocr"
        else importlib.util.find_spec("paddleocr") is not None
        and importlib.util.find_spec("paddle") is not None
    )


def _ocr_install_worker(engine: str) -> None:
    if _ocr_engine_installed(engine):
        OCR_INSTALL.update(state="completed", phase="complete", status=f"{engine} redan installerad", error=None, error_code=None)
        return
    packages = ["easyocr"] if engine == "easyocr" else ["paddleocr", "paddlepaddle"]
    try:
        for package in packages:
            OCR_INSTALL.update(phase="download", package=package, status=f"Laddar ner {package} …")
            pip_args = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
            # System-Python kan sakna skrivrättighet till site-packages på
            # Windows. En venv använder vanlig pip; annars används --user.
            if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
                pip_args.append("--user")
            pip_args.append(package)
            result = subprocess.run(pip_args, capture_output=True, text=True, timeout=1800)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or f"pip kunde inte installera {package}")[-1000:]
                if "access is denied" in detail.lower() or "permission denied" in detail.lower():
                    raise PermissionError(
                        f"Ingen behörighet att installera {package}. Kör appen i en venv eller som användare."
                    )
                raise RuntimeError(detail)
            OCR_INSTALL.update(phase="install", status=f"Installerar {package} …")
        OCR_INSTALL.update(state="completed", phase="complete", status=f"{engine} installerad", error=None, error_code=None)
    except Exception as exc:  # noqa: BLE001 - visas i GUI
        OCR_INSTALL.update(state="failed", phase="error", status="Installationen misslyckades", error=str(exc), error_code=type(exc).__name__)


@app.post("/api/lpr/install")
def install_lpr_engine(payload: dict):
    engine = str(payload.get("engine") or "").strip().lower()
    if engine not in ("easyocr", "paddleocr"):
        raise HTTPException(400, "engine måste vara easyocr eller paddleocr")
    if OCR_INSTALL["state"] == "running":
        return {"started": False, **OCR_INSTALL}
    if _ocr_engine_installed(engine):
        OCR_INSTALL.update(state="completed", phase="complete", engine=engine, status=f"{engine} redan installerad", error=None, error_code=None)
        return {"started": False, **OCR_INSTALL}
    with _ocr_install_lock:
        OCR_INSTALL.update(
            state="running", phase="download", engine=engine, package=None,
            status="Förbereder nedladdning …", error=None, error_code=None,
        )
    threading.Thread(target=_ocr_install_worker, args=(engine,), daemon=True).start()
    return {"started": True, **OCR_INSTALL}


@app.get("/api/lpr/install/status")
def lpr_install_status():
    status = dict(OCR_INSTALL)
    status["installed"] = {
        "easyocr": importlib.util.find_spec("easyocr") is not None,
        "paddleocr": importlib.util.find_spec("paddleocr") is not None,
        "paddlepaddle": importlib.util.find_spec("paddle") is not None,
    }
    return status


class _PullIn(BaseModel):
    """Body för POST /api/ollama/pull."""

    model: str


def _ollama_pull_worker(model: str) -> None:
    import json as _json
    import urllib.error
    import urllib.request

    total: dict = {}
    done: dict = {}
    try:
        payload = _json.dumps({"name": model, "stream": True}).encode("utf-8")
        req = urllib.request.Request(
            f"{config.OLLAMA_URL}/api/pull",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=None) as resp:  # noqa: S310 - lokal Ollama
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    evt = _json.loads(line)
                except ValueError:
                    continue
                if evt.get("error"):
                    PULL["error"] = evt["error"]
                    PULL["state"] = "failed"
                    return
                status = evt.get("status", "")
                digest = evt.get("digest")
                if digest:
                    total[digest] = evt.get("total", total.get(digest, 0))
                    done[digest] = evt.get("completed", done.get(digest, 0))
                s = sum(total.values())
                if s:
                    PULL["percent"] = min(100, int(round(sum(done.values()) / s * 100)))
                PULL["status"] = status
                if status == "success":
                    PULL["state"] = "completed"
        if PULL["state"] == "running":
            PULL["state"] = "completed"
    except Exception as exc:  # noqa: BLE001
        PULL["error"] = str(exc)
        PULL["state"] = "failed"
    finally:
        if PULL["state"] == "completed":
            PULL["percent"] = 100


@app.post("/api/ollama/pull")
def start_ollama_pull(payload: _PullIn):
    model = payload.model.strip()
    if not model:
        raise HTTPException(400, "model required")
    if PULL["state"] == "running":
        return {"started": False, "reason": "En nedladdning pågår redan", "state": PULL["state"]}
    with _pull_lock:
        PULL.update(state="running", model=model, percent=0, status="startar …", error=None)
    threading.Thread(target=_ollama_pull_worker, args=(model,), daemon=True).start()
    return {"started": True, "model": model}


@app.get("/api/ollama/pull/status")
def ollama_pull_status():
    return dict(PULL)


# ---------------------------------------------------------------------------
# YOLO-modellvikt: nedladdningsstatus (GUI:t visar när .pt hämtas vid val)
# ---------------------------------------------------------------------------


@app.get("/api/yolo/download/status")
def yolo_download_status():
    """Status för ev. pågående nedladdning av en YOLO-modellvikt."""
    st = dict(YOLO_DL)
    st["installed"] = yolo_model_installed(RUNTIME["model"])
    return st


@app.get("/api/ollama/models")
def ollama_models_api():
    models = ollama_models()
    # Endast vision-kapabla modeller i LLM-rullgardinen — annars kan man välja
    # en textmodell (eller korrupt vision-modell) som ger 404/500 och gör att
    # en annan modell laddas istället.
    vision = [m for m in models if "vision" in (m.get("capabilities") or [])]
    usable = vision or models  # fallback: visa alla om ingen har vision-metadata
    names = sorted(m.get("name", "") for m in usable)
    sizes = {}
    for m in usable:
        name = m.get("name", "")
        size = m.get("size") or 0
        sizes[name] = round(size / (1024 ** 3), 1)  # bytes -> GB
    return {
        "models": names,
        "sizes": sizes,
        "ollama_available": llm_available(),
        "ollama_error": ollama_models_error(),
    }


# ---------------------------------------------------------------------------
# System-åtgärder (knappar i GUI:t)
# ---------------------------------------------------------------------------

def _detached_flags() -> int:
    # Windows: DETACHED_PROCESS | CREATE_NO_WINDOW (ingen konsol, ingen parent)
    return 0x00000008 | 0x08000000


@app.post("/api/system/unload-models")
def system_unload_models():
    """Ladda ur alla Ollama-modeller ur GPU-minnet (ollama stop per modell)."""
    import subprocess

    stopped, skipped, failed = [], [], []
    for m in ollama_models():
        name = m.get("name", "")
        try:
            r = subprocess.run(["ollama", "stop", name], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                stopped.append(name)
            else:
                skipped.append(name)  # t.ex. redan urladdad
        except Exception as exc:  # noqa: BLE001 - ej kritiskt
            failed.append(f"{name} ({exc})")
    return {"stopped": stopped, "skipped": skipped, "failed": failed}


@app.post("/api/system/restart-server")
def system_restart_server():
    """Starta om servern: en hjälpprocess dödar denna och startar en ny identisk process."""
    import os
    import subprocess
    import sys

    old_pid = os.getpid()
    python = sys.executable
    args = [python] + list(sys.argv)
    code = (
        "import subprocess,time,os;"
        f"time.sleep(1);"
        f"subprocess.run(['taskkill','/F','/PID',str({old_pid})],capture_output=True);"
        f"time.sleep(0.5);"
        f"os.chdir({os.getcwd()!r});"
        f"subprocess.Popen({args!r},creationflags=0x8|0x08000000,close_fds=True)"
    )
    try:
        subprocess.Popen([python, "-c", code], creationflags=_detached_flags(), close_fds=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "restarting": True}


@app.post("/api/system/restart-ollama")
def system_restart_ollama():
    """Starta om Ollama-servern (tömmer allt ur GPU-minnet).

    Använder PowerShell för att hitta processen, hämta dess exakta exe + kommando,
    döda den och starta om med samma kommando — och verifiera att porten svarar igen.
    """
    import subprocess

    ps = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$line = netstat -ano | Select-String ':11434' | Select-String 'LISTENING' | Select-Object -First 1;"
        "if (-not $line) { 'NO_OLLAMA'; exit };"
        "$pid114 = ($line.Line -split '\\s+')[-1];"
        "$p = Get-CimInstance Win32_Process -Filter \"ProcessId=$pid114\";"
        "$exe = $p.ExecutablePath; $cmd = $p.CommandLine;"
        "Stop-Process -Id $pid114 -Force;"
        "Start-Sleep -Milliseconds 1200;"
        "$env:OLLAMA_HOST='0.0.0.0:11434';"
        "if ($exe) { if ($cmd -match 'serve') { Start-Process -FilePath $exe -ArgumentList 'serve' } else { Start-Process -FilePath $exe } }"
        "else { Start-Process -FilePath 'ollama' -ArgumentList 'serve' };"
        "Start-Sleep -Seconds 2;"
        "if (netstat -ano | Select-String ':11434' | Select-String 'LISTENING') { 'OK:' + $pid114 } else { 'FAILED' }"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = (r.stdout + r.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    ok = "OK:" in out
    return {"ok": ok, "output": out}


@app.get("/api/history")
def get_history(limit: int = 20):
    """Recent analyses, newest first."""
    items = list(HISTORY)
    return items[-limit:][::-1]


@app.get("/api/events")
def get_events(limit: int = 50):
    """Senaste HA-detektionerna, newest first."""
    limit = min(50, max(1, limit))
    events = []
    for event in list(EVENT_LOG)[-limit:][::-1]:
        item = dict(event)
        image = item.get("image")
        if image:
            item["image_url"] = f"/media/{Path(image).name}"
        events.append(item)
    response = JSONResponse(events)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/api/lpr")
def get_lpr(limit: int = 100):
    limit = min(100, max(1, limit))
    items = []
    for item in list(LPR_LOG)[-limit:][::-1]:
        value = dict(item)
        if value.get("image"):
            value["image_url"] = f"/media/{Path(value['image']).name}"
        items.append(value)
    response = JSONResponse(items)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@app.get("/api/stats")
def get_stats():
    """Aggregated stats across the kept history."""
    people = animals = vehicles = errors = 0
    per_camera: dict = {}
    colors: set = set()
    inf_times: list = []
    for h in HISTORY:
        c = h.get("counts") or {}
        people += c.get("people", 0)
        animals += c.get("animals", 0)
        vehicles += c.get("vehicles", 0)
        colors.update(c.get("colors") or [])
        cam = h.get("camera", "cam")
        per_camera[cam] = per_camera.get(cam, 0) + 1
        if h.get("error"):
            errors += 1
        if h.get("inference_ms"):
            inf_times.append(h["inference_ms"])
    return {
        "total_analyses": len(HISTORY),
        "total_detections": sum(len(h.get("detections") or []) for h in HISTORY),
        "people": people,
        "animals": animals,
        "vehicles": vehicles,
        "colors": sorted(colors),
        "per_camera": per_camera,
        "avg_inference_ms": round(sum(inf_times) / len(inf_times), 1) if inf_times else 0,
        "errors": errors,
        "uptime_seconds": round(time.time() - START_TIME),
        "model": RUNTIME["model"],
        "conf": RUNTIME["conf"],
        "device": RUNTIME["device"],
        "llm_model": RUNTIME["llm_model"],
    }


@app.get("/")
def index():
    # Ersätter __VER__-platshållare i statiska URL:er så att webbläsare (inkl.
    # telefoner) hämtar färska filer vid varje ny version (cache-busting).
    html = (config.BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__VER__", config.VERSION))


@app.get("/api/health")
def health():
    w = pool.default()
    if w is not None:
        s = w.status()
    else:
        s = {
            "camera_enabled": False,
            "camera_state": "disabled",
            "yolo_state": "stopped",
            "actual_device": analyzer.last_device or config.YOLO_DEVICE,
        }
    return {
        "ok": True,
        "version": config.VERSION,
        "yolo_model": analyzer.model_name,
        "llm_backend": config.LLM_BACKEND,
        "ollama_available": llm_available(),
        "llm_model": (
            active_ollama_model(RUNTIME["llm_model"])
            if config.LLM_BACKEND == "ollama"
            else None
        ),
        "ha_enabled": ha.available(),
        "cameras": pool.count(),
        "camera_enabled": s.get("camera_enabled", False),
        "camera_state": s.get("camera_state", "disabled"),
        "yolo_state": s.get("yolo_state", "stopped"),
        "actual_device": s.get("actual_device"),
    }


@app.get("/api/ha/status")
def ha_status():
    return ha.status()


class _HaSettingsIn(BaseModel):
    enabled: bool | None = None
    transport: str | None = None
    camera_id: str | None = None
    discovery_prefix: str | None = None
    mqtt_host: str | None = None
    mqtt_port: int | None = None
    mqtt_user: str | None = None
    mqtt_pass: str | None = None
    rest_url: str | None = None
    rest_token: str | None = None


_HA_MAP = {
    "enabled": ("HA_ENABLED", "bool"),
    "transport": ("HA_TRANSPORT", "str"),
    "camera_id": ("HA_CAMERA_ID", "str"),
    "discovery_prefix": ("HA_DISCOVERY_PREFIX", "str"),
    "mqtt_host": ("HA_MQTT_HOST", "str"),
    "mqtt_port": ("HA_MQTT_PORT", "int"),
    "mqtt_user": ("HA_MQTT_USER", "str"),
    "mqtt_pass": ("HA_MQTT_PASS", "str"),
    "rest_url": ("HA_REST_URL", "str"),
    "rest_token": ("HA_REST_TOKEN", "str"),
}


def _ha_config_public() -> dict:
    return {
        "enabled": bool(config.HA_ENABLED),
        "transport": config.HA_TRANSPORT,
        "camera_id": config.HA_CAMERA_ID,
        "discovery_prefix": config.HA_DISCOVERY_PREFIX,
        "mqtt_host": config.HA_MQTT_HOST,
        "mqtt_port": int(config.HA_MQTT_PORT),
        "mqtt_user": config.HA_MQTT_USER,
        "mqtt_pass_configured": bool(config.HA_MQTT_PASS),
        "rest_url": config.HA_REST_URL,
        "rest_token_configured": bool(config.HA_REST_TOKEN),
        "status": ha.status(),
    }


def _apply_ha_runtime(values: dict) -> list:
    """Applicera HA-inställningar direkt (runtime) + spara till .env + återanslut."""
    errors: list[str] = []
    env_write: dict[str, str] = {}
    for logical, val in values.items():
        if logical not in _HA_MAP or val is None:
            continue
        attr, typ = _HA_MAP[logical]
        try:
            if typ == "bool":
                v = val if isinstance(val, bool) else str(val).strip().lower() in ("1", "true", "yes", "on")
                setattr(config, attr, v)
                env_write[attr] = "true" if v else "false"
            elif typ == "int":
                v = int(val)
                setattr(config, attr, v)
                env_write[attr] = str(v)
            else:
                v = str(val).strip()
                setattr(config, attr, v)
                env_write[attr] = v
        except (TypeError, ValueError):
            errors.append(f"Ogiltigt värde för '{logical}'.")
    if env_write:
        if not config.persist_env(env_write):
            errors.append("Kunde inte spara HA-inställningarna till .env.")
        else:
            print(f"[ha] sparade till .env: {', '.join(env_write)}")
    try:
        ha.reconnect()  # återanslut (eller koppla från om HA avstängt)
    except Exception as exc:  # noqa: BLE001 - visa fel men spara ändå
        errors.append(f"Kunde inte ansluta till HA: {exc}")
    return errors


@app.get("/api/ha/config")
def ha_config_get():
    """HA-konfiguration (inga hemligheter - bara *_configured-flaggor)."""
    return _ha_config_public()


@app.put("/api/ha/config")
def ha_config_put(payload: _HaSettingsIn):
    body = payload.model_dump(exclude_unset=True, exclude_none=True)
    if body.get("transport") not in (None, "mqtt", "rest"):
        return JSONResponse(
            {"ok": False, "errors": ["Transporten måste vara 'mqtt' eller 'rest'."]},
            status_code=400,
        )
    errs = _apply_ha_runtime(body)
    if errs:
        return JSONResponse({"ok": False, "errors": errs}, status_code=400)
    return {"ok": True, "config": _ha_config_public()}


@app.post("/api/ha/test")
def ha_test():
    """Testa HA-anslutningen (startar om MQTT-klienten med nuvarande config)."""
    try:
        ha.reconnect()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": ha.status(), "error": str(exc)}
    st = ha.status()
    return {"ok": bool(st.get("connected")), "status": st}


# ---------------------------------------------------------------------------
# Live-kamera (RTSP -> YOLO -> MJPEG) - Dashboard-API + inställningar
# ---------------------------------------------------------------------------
_KNOWN_YOLO_MODELS = [
    "yolo11n.pt", "yolo11s.pt", "yolo11m.pt",
    "yolo26n.pt", "yolo26s.pt", "yolo26m.pt",
]
_KNOWN_DEVICES = ["cpu", "openvino:CPU", "openvino:GPU"]
_KNOWN_IMGSZ = [320, 480, 640, 960, 1280]


class _CameraTestIn(BaseModel):
    host: str | None = None
    user: str | None = None
    password: str | None = None
    path: str | None = None
    full_url: str | None = None
    port: int | None = None


class _SettingsIn(BaseModel):
    camera: dict | None = None
    detect: dict | None = None
    live: dict | None = None
    events: dict | None = None
    auth: dict | None = None


class _CameraTestIn(BaseModel):
    camera_id: str | None = None
    host: str | None = None
    user: str | None = None
    password: str | None = None
    path: str | None = None
    full_url: str | None = None
    port: int | None = None


class _CameraIn(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    host: str | None = None
    user: str | None = None
    password: str | None = None
    path: str | None = None
    main_path: str | None = None
    full_url: str | None = None
    reconnect: bool | None = None
    reconnect_delay: int | None = None
    autostart: bool | None = None
    # Detektionslinje (ROI) – äldre, omvandlas till zon
    roi_enabled: bool | None = None
    roi_y: float | None = None
    roi_side: str | None = None
    # Detektionszon(er) (en eller flera polygoner av normaliserade punkter)
    zone_enabled: bool | None = None
    zone_polys: list | None = None
    zone_kinds: list | None = None
    zone_points: list | None = None
    zone_mode: str | None = None


def _resolve_camera(camera: str | None):
    """Resolve en kamera via id/namn (tomt -> första i registret)."""
    if camera and str(camera).strip():
        return pool.get(str(camera))
    return pool.default()


def _cam_errors(name: str | None = None, host: str | None = None,
                full_url: str | None = None, rd: int | None = None) -> list:
    errors: list[str] = []
    if name is not None and not str(name).strip():
        errors.append("Kameranamnet får inte vara tomt.")
    if host is not None and not str(host).strip() and not str(full_url or "").strip():
        errors.append("Ange kamera-IP (eller full RTSP-URL).")
    if rd is not None:
        try:
            rd = int(rd)
        except (TypeError, ValueError):
            rd = 0
        if not 1 <= rd <= 300:
            errors.append("Återanslutningsintervall måste vara 1–300 sekunder.")
    return errors


def _roi_normalize(body: dict) -> list:
    """Validera och normalisera detektionslinjens fält (roi_*)."""
    errors: list[str] = []
    if "roi_enabled" in body:
        body["roi_enabled"] = bool(body["roi_enabled"])
    if "roi_y" in body and body.get("roi_y") is not None:
        try:
            y = float(body["roi_y"])
        except (TypeError, ValueError):
            y = float("nan")
        if not (0.0 <= y <= 1.0):
            errors.append("Linjens höjd måste vara mellan 0 och 1 (andel av bildhöjden).")
        else:
            body["roi_y"] = round(y, 3)
    if "roi_side" in body and body.get("roi_side") not in ("above", "below"):
        errors.append("Linjesidan måste vara 'above' (ovanför) eller 'below' (nedanför).")
    # Detektionszon(er) – en eller flera polygoner. Nytt format: zone_polys
    # (lista av polygoner). Äldre format: en enda zone_points-polygon migreras.
    if "zone_enabled" in body:
        body["zone_enabled"] = bool(body["zone_enabled"])
    if "zone_mode" in body and body.get("zone_mode") not in ("inside", "outside"):
        errors.append("Zonläget måste vara 'inside' (inuti) eller 'outside' (utanför).")
    has_poly_src = "zone_polys" in body or (
        "zone_points" in body and body.get("zone_points") is not None
    )
    if has_poly_src:
        src = body.get("zone_polys")
        if src is None:
            src = [body.get("zone_points") or []]  # legacy: en enda polygon
        if not isinstance(src, list):
            errors.append("Zoner måste vara en lista av polygoner ([ [ [x,y], ... ], ... ]).")
        else:
            polys = []
            for i, poly in enumerate(src):
                if not isinstance(poly, list):
                    errors.append(f"Zon {i + 1} måste vara en lista av punkter.")
                    continue
                pts = []
                for p in poly:
                    try:
                        x, y = float(p[0]), float(p[1])
                    except (TypeError, ValueError, IndexError):
                        errors.append(f"Zon {i + 1}: varje punkt måste vara [x, y] med värden 0–1.")
                        continue
                    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                        errors.append(f"Zon {i + 1}: punkter måste ligga mellan 0 och 1.")
                        continue
                    pts.append([round(x, 3), round(y, 3)])
                if len(pts) >= 3:
                    polys.append(pts)
                elif pts:
                    errors.append(f"Zon {i + 1} behöver minst 3 punkter.")
            if body.get("zone_enabled") and not polys:
                errors.append("Zonen behöver minst 3 punkter för att vara aktiv.")
            # Per-zon-typ ('watch' = bevaka, 'mask' = övervaka INTE)
            if "zone_kinds" in body and body.get("zone_kinds") is not None:
                ksrc = body["zone_kinds"]
                if not isinstance(ksrc, list):
                    errors.append("Zone-typerna måste vara en lista ('watch'/'mask').")
                else:
                    kinds = []
                    for i, k in enumerate(ksrc):
                        if k not in ("watch", "mask"):
                            errors.append("Varje zon-typ måste vara 'watch' (bevaka) eller 'mask' (övervaka INTE).")
                            kinds.append("watch")
                        else:
                            kinds.append(k)
                    body["zone_kinds"] = kinds[: len(polys)]
            body["zone_polys"] = polys
            body["zone_points"] = []  # legacy töms – zone_polys är källan
    return errors


@app.get("/api/cameras/status")
def cameras_status():
    """Status för alla kameror (Dashboard-listning)."""
    return {
        "cameras": pool.statuses(),
        "default": pool.ids()[0] if pool.ids() else None,
    }


@app.get("/api/cameras/list")
def cameras_list():
    """Konfigurationslista (inga hemligheter)."""
    return {"cameras": pool.camera_list()}


@app.get("/api/yolo/classes")
def yolo_classes():
    """Alla klasser YOLO kan detektera (för kryssrutor i Inställningar)."""
    try:
        classes = analyzer.available_classes()
    except Exception:  # noqa: BLE001
        from analyzer import COCO_CLASSES  # noqa: PLC0415
        classes = list(COCO_CLASSES)
    return {"classes": classes, "model": getattr(analyzer, "model_name", None)}


@app.post("/api/cameras")
def camera_add(payload: _CameraIn):
    """Lägg till en ny kamera (startas direkt om enabled)."""
    body = payload.model_dump(exclude_unset=True, exclude_none=True)
    if body.get("password") in (None, ""):
        body.pop("password", None)
    errs = _cam_errors(name=body.get("name"), host=body.get("host"),
                       full_url=body.get("full_url"),
                       rd=body.get("reconnect_delay"))
    if not body.get("host") and not body.get("full_url"):
        errs.append("Ange kamera-IP (eller full RTSP-URL).")
    errs += _roi_normalize(body)
    if errs:
        return JSONResponse({"ok": False, "errors": errs}, status_code=400)
    w = pool.add(body)
    return {"ok": True, "camera": w.public_cfg(), "runtime": w.status()}


@app.put("/api/cameras/{camera_id}")
def camera_update(camera_id: str, payload: _CameraIn):
    """Uppdatera en kamera (startar/stoppar/startar om vid behov)."""
    w = pool.get(camera_id)
    if w is None:
        raise HTTPException(404, f"Kameran '{camera_id}' finns inte.")
    body = payload.model_dump(exclude_unset=True, exclude_none=True)
    existing = w.camera
    errs = _cam_errors(
        name=body.get("name"),
        host=body.get("host") if "host" in body else None,
        full_url=body.get("full_url") if "full_url" in body else str(existing.get("full_url") or ""),
        rd=body.get("reconnect_delay"),
    )
    if errs:
        return JSONResponse({"ok": False, "errors": errs}, status_code=400)
    if body.get("password") in (None, ""):
        body.pop("password", None)
    errs += _roi_normalize(body)
    if errs:
        return JSONResponse({"ok": False, "errors": errs}, status_code=400)
    updated = pool.update(camera_id, body)
    return {"ok": True, "camera": updated.public_cfg(), "runtime": updated.status()}


@app.delete("/api/cameras/{camera_id}")
def camera_delete(camera_id: str):
    if not pool.remove(camera_id):
        raise HTTPException(404, f"Kameran '{camera_id}' finns inte.")
    return {"ok": True, "cameras": pool.camera_list()}


@app.post("/api/cameras/{camera_id}/start")
def camera_start_id(camera_id: str):
    w = pool.start(camera_id)
    if w is None:
        raise HTTPException(404, f"Kameran '{camera_id}' finns inte.")
    return w.status()


@app.post("/api/cameras/{camera_id}/stop")
def camera_stop_id(camera_id: str):
    w = pool.stop(camera_id)
    if w is None:
        raise HTTPException(404, f"Kameran '{camera_id}' finns inte.")
    return w.status()


@app.post("/api/cameras/{camera_id}/stream/start")
def camera_stream_start(camera_id: str):
    """Starta GUI-strömmen. Worker + YOLO + HA-event fortsätter ändå."""
    w = pool.set_stream(camera_id, True)
    if w is None:
        raise HTTPException(404, f"Kameran '{camera_id}' finns inte.")
    return w.status()


@app.post("/api/cameras/{camera_id}/stream/stop")
def camera_stream_stop(camera_id: str):
    """Stoppa GUI-strömmen (videon). YOLO + HA-event fortsätter på servern."""
    w = pool.set_stream(camera_id, False)
    if w is None:
        raise HTTPException(404, f"Kameran '{camera_id}' finns inte.")
    return w.status()


@app.post("/api/cameras/start")
def camera_start():
    """Starta första kameran (bakåtkompatibilitet)."""
    w = pool.default()
    if w is not None:
        w.start()
    return cameras_status()


@app.post("/api/cameras/stop")
def camera_stop():
    """Stoppa första kameran (bakåtkompatibilitet)."""
    w = pool.default()
    if w is not None:
        w.stop()
    return cameras_status()


@app.get("/api/live/{camera}")
def live_stream(camera: str = ""):
    """MJPEG-liveström för en kamera (senaste annoterade bilden, ingen kö).

    Worker + YOLO körs på servern kontinuerligt - endpoints skickar bara den
    senaste bilden till den som tittar just nu.
    """
    w = _resolve_camera(camera)
    if w is None:
        raise HTTPException(404, "Ingen kamera konfigurerad.")

    async def _mjpeg_gen():
        last_v = -1
        while True:
            data, v = w.latest_jpeg()
            if data is not None and v != last_v:
                last_v = v
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                    + data
                    + b"\r\n"
                )
            else:
                await asyncio.sleep(0.05)

    return StreamingResponse(
        _mjpeg_gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/live/{camera}/snapshot.jpg")
def live_snapshot(camera: str = "", clean: bool = False):
    """Stillbild som JPEG. ``clean=1`` ger rå bild utan boxar/linje (för
    förhandsvisning när man sätter detektionslinjen), annars senaste annoterade.

    Används av HA/HACS som en vanlig bild-URL per kamera - enklare än att
    streama MJPEG. 404 tills kameran har producerat en första bild.
    """
    w = _resolve_camera(camera)
    if w is None:
        raise HTTPException(404, "Ingen kamera konfigurerad.")
    if clean:
        data = w.raw_jpeg()
        if not data:
            raise HTTPException(404, "Ingen bild ännu - vänta på första frame:en.")
        return Response(
            content=data,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache"},
        )
    data, _v = w.latest_jpeg()
    if not data:
        raise HTTPException(404, "Ingen bild ännu - vänta på första frame:en.")
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/camera/test")
def camera_test(payload: _CameraTestIn | None = None):
    """Testa en RTSP-kamera. Stör inte aktiva workers.

    Utan override: om kameran (eller default) redan är online återanvänds dess
    status. Annars öppnas en separat testanslutning.
    """
    body = payload.model_dump(exclude_unset=True) if payload else {}
    if body.get("camera_id"):
        w = pool.get(str(body["camera_id"]))
    else:
        w = pool.default()
    if w is not None and not any(k in body for k in ("host", "user", "password", "path", "full_url")):
        s = w.status()
        if s.get("stream_active"):
            return {
                "ok": True,
                "using_live": True,
                "resolution": s.get("resolution"),
                "fps": s.get("source_fps"),
                "codec": s.get("codec"),
            }
        cfg = w.camera
    else:
        cfg = w.camera if w is not None else {}
    host = str(body.get("host") or cfg.get("host") or "")
    user = str(body.get("user") or cfg.get("user") or "")
    password = body["password"] if "password" in body else (cfg.get("password") or "")
    path = str(body.get("path") or cfg.get("path") or "/Preview_01_sub")
    full_url = str(body.get("full_url") or cfg.get("full_url") or "")
    return test_rtsp(host, user, password, path, full_url)


@app.post("/api/camera/scan")
async def camera_scan(payload: _CameraTestIn | None = None):
    """Skanna en RTSP-kamera efter main-/sub-strömmar (som Blue Iris).

    Provar vanliga RTSP-sökvägar och returnerar vilka som svarar + upplösning.
    Använder kamerans sparade inloggning om `camera_id` ges.
    """
    body = payload.model_dump(exclude_unset=True) if payload else {}
    w = pool.get(str(body["camera_id"])) if body.get("camera_id") else None
    cfg = w.camera if w is not None else {}
    host = str(body.get("host") or cfg.get("host") or "")
    user = str(body.get("user") or cfg.get("user") or "")
    password = body["password"] if "password" in body else (cfg.get("password") or "")
    full_url = str(body.get("full_url") or cfg.get("full_url") or "")
    port = int(body.get("port") or 554)
    if not host and not full_url:
        return JSONResponse({"ok": False, "error": "Ange kamera-IP."}, status_code=400)
    result = await asyncio.to_thread(scan_camera, host, user, password, full_url, port)
    return JSONResponse(result)


@app.get("/api/settings")
def get_settings():
    """Nuvarande inställningar (globalt) + kameralista. Inga hemligheter."""
    w = pool.default()
    if w is not None:
        g = w._cfg()
        det, liv, ev = g["detect"], g["live"], g["events"]
        camc = w.public_cfg()
        rt = w.status()
    else:
        det = CameraWorker._detect_defaults()
        liv = CameraWorker._live_defaults()
        ev = CameraWorker._event_defaults()
        camc = {
            "id": None, "enabled": False, "name": "", "host": "", "user": "",
            "path": "/Preview_01_sub", "password_configured": False,
            "full_url_configured": False, "reconnect": True,
            "reconnect_delay": int(config.CAMERA_RECONNECT_DELAY), "autostart": False,
        }
        rt = None
    return {
        "camera": camc,
        "cameras": pool.camera_list(),
        "detect": {
            "yolo_enabled": bool(det["yolo_enabled"]),
            "model": RUNTIME["model"],
            "conf": RUNTIME["conf"],
            "device": RUNTIME["device"],
            "ai_fps": float(det["ai_fps"]),
            "imgsz": int(det["imgsz"]),
            "min_score": float(det.get("min_score", 0.0) or 0.0),
            "min_area": float(det.get("min_area", 0.0) or 0.0),
            "max_area": float(det.get("max_area", 1.0) or 1.0),
            "class_scores": det.get("class_scores", ""),
            "motion_gate": bool(det.get("motion_gate", False)),
            "motion_threshold": float(det.get("motion_threshold", 5.0) or 5.0),
            "lpr_enabled": bool(det.get("lpr_enabled", False)),
            "lpr_engine": str(det.get("lpr_engine", config.LPR_ENGINE)),
            "lpr_engine_options": ["easyocr", "paddleocr"],
            "model_options": list(_KNOWN_YOLO_MODELS),
            "device_options": list(_KNOWN_DEVICES),
            "imgsz_options": list(_KNOWN_IMGSZ),
        },
        "live": {
            "enabled": bool(liv["enabled"]),
            "display_fps": int(liv["display_fps"]),
            "jpeg_quality": int(liv["jpeg_quality"]),
            "show_boxes": bool(liv["show_boxes"]),
            "show_labels": bool(liv["show_labels"]),
            "show_conf": bool(liv["show_conf"]),
        },
        "events": {
            "enabled": bool(ev["enabled"]),
            "classes": ev["classes"],
            "min_conf": float(ev["min_conf"]),
            "clear_after": float(ev["clear_after"]),
            "hold": float(ev["hold"]),
            "min_interval": float(ev["min_interval"]),
            "startup_grace": float(ev["startup_grace"]),
        },
        "runtime": rt,
        "auth": {
            "enabled": bool(config.AUTH_ENABLED),
            "username": config.AUTH_USERNAME,
            "password_configured": bool(config.AUTH_PASSWORD_HASH),
        },
    }


@app.put("/api/settings")
def update_settings(payload: _SettingsIn):
    """Spara live-inställningar (GUI-first). Validering sker här - med
    användarvänliga felmeddelanden, inte HTTP 422. Lösenord skickas aldrig
    tillbaka i GET; tomt lösenordsfält vid PUT behåller det befintliga."""
    body = payload.model_dump(exclude_unset=True)
    w = pool.default()
    if w is not None:
        cur = w._cfg()
        cur_cam = dict(w.camera)
        cur_det, cur_live, cur_ev = cur["detect"], cur["live"], cur["events"]
    else:
        cur_cam = {
            "enabled": False, "name": "Kamera", "host": "", "user": "",
            "password": "", "path": "/Preview_01_sub", "full_url": "",
            "reconnect": True, "reconnect_delay": int(config.CAMERA_RECONNECT_DELAY),
            "autostart": False,
        }
        cur_det = CameraWorker._detect_defaults()
        cur_live = CameraWorker._live_defaults()
        cur_ev = CameraWorker._event_defaults()

    errors: list[str] = []
    requires: list[str] = []
    env_write: dict[str, str] = {}
    pending_cam: dict | None = None
    pending_det: dict | None = None
    pending_live: dict | None = None
    pending_events: dict | None = None

    def _to_bool(v, cur: bool) -> bool:
        try:
            return bool(v) if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
        except (TypeError, ValueError):
            return cur

    # ----------------------------- Säkerhet ---------------------------
    if body.get("auth"):
        auth = dict(body["auth"])
        auth_enabled = _to_bool(auth.get("enabled", config.AUTH_ENABLED), config.AUTH_ENABLED)
        auth_username = str(auth.get("username", config.AUTH_USERNAME) or "").strip()
        auth_password = str(auth.get("password") or "")
        if not auth_username:
            errors.append("Användarnamnet får inte vara tomt.")
        if auth_enabled and not config.AUTH_PASSWORD_HASH and not auth_password:
            errors.append("Ange ett lösenord innan GUI-skydd aktiveras.")
        if auth_password and len(auth_password) < 8:
            errors.append("Lösenordet måste vara minst 8 tecken.")
        if not errors:
            env_write["CAMERA_AUTH_ENABLED"] = "true" if auth_enabled else "false"
            env_write["CAMERA_AUTH_USERNAME"] = auth_username
            if auth_password:
                env_write["CAMERA_AUTH_PASSWORD_HASH"] = config.hash_auth_password(auth_password)

    # ----------------------------- Kamera -----------------------------
    if body.get("camera"):
        c = dict(body["camera"])
        enabled = _to_bool(c.get("enabled", cur_cam["enabled"]), cur_cam["enabled"])
        name = str(c.get("name", cur_cam["name"])).strip()
        if not name:
            errors.append("Kameranamnet får inte vara tomt.")
        host = str(c.get("host", cur_cam.get("host") or "")).strip()
        user = str(c.get("user", cur_cam.get("user") or ""))
        # Tomt lösenordsfält = behåll befintligt lösenord
        password = cur_cam.get("password") or ""
        if "password" in c and c["password"] is not None and str(c["password"]).strip():
            password = str(c["password"])
        path = str(c.get("path", cur_cam.get("path") or "/Preview_01_sub")).strip() or "/Preview_01_sub"
        if not path.startswith("/"):
            path = "/" + path
        reconnect = _to_bool(c.get("reconnect", cur_cam["reconnect"]), cur_cam["reconnect"])
        autostart = _to_bool(c.get("autostart", cur_cam["autostart"]), cur_cam["autostart"])
        rd = int(cur_cam["reconnect_delay"])
        if "reconnect_delay" in c:
            try:
                rd = int(c["reconnect_delay"])
            except (TypeError, ValueError):
                rd = 0
            if not 1 <= rd <= 300:
                errors.append("Återanslutningsintervall måste vara 1–300 sekunder.")
        full_url = str(c.get("full_url", cur_cam.get("full_url") or "")).strip()
        if not host and not full_url:
            errors.append("Ange kamera-IP (eller full RTSP-URL).")
        if not errors:
            pending_cam = {
                "enabled": enabled, "name": name, "host": host, "user": user,
                "password": password, "path": path, "reconnect": reconnect,
                "reconnect_delay": rd, "autostart": autostart, "full_url": full_url,
            }
            env_write.update({
                "CAMERA_ENABLED": "true" if enabled else "false",
                "CAMERA_NAME": name,
                "CAMERA_HOST": host,
                "CAMERA_USER": user,
                "CAMERA_PASS": password,
                "CAMERA_PATH": path,
                "CAMERA_RECONNECT": "true" if reconnect else "false",
                "CAMERA_RECONNECT_DELAY": str(rd),
                "CAMERA_AUTOSTART": "true" if autostart else "false",
                "CAMERA_RTSP_URL": full_url,
            })
            if any(k in c for k in (
                "enabled", "name", "host", "user", "password", "path",
                "reconnect", "reconnect_delay", "full_url", "autostart",
            )):
                requires.append("camera_restart")

    # --------------------------- Detektering --------------------------
    if body.get("detect"):
        d = dict(body["detect"])
        yolo_en = _to_bool(d.get("yolo_enabled", cur_det["yolo_enabled"]), cur_det["yolo_enabled"])
        af = float(cur_det["ai_fps"])
        if "ai_fps" in d:
            try:
                af = float(d["ai_fps"])
            except (TypeError, ValueError):
                af = 0.0
            if not 1 <= af <= 30:
                errors.append("AI FPS måste vara mellan 1 och 30.")
        imgsz = int(cur_det["imgsz"])
        if "imgsz" in d:
            try:
                imgsz = int(d["imgsz"])
            except (TypeError, ValueError):
                imgsz = 0
            if imgsz not in _KNOWN_IMGSZ:
                errors.append(f"Bildstorleken måste vara en av: {', '.join(map(str, _KNOWN_IMGSZ))}.")
        # Objektfilter: extra min-konfidens + min/max-area + per-klass-konfidens
        min_score = float(cur_det.get("min_score", 0.0) or 0.0)
        if "min_score" in d:
            try:
                min_score = float(d["min_score"])
            except (TypeError, ValueError):
                min_score = -1.0
            if not 0.0 <= min_score <= 1.0:
                errors.append("Extra lägsta konfidens måste vara mellan 0 och 1.")
        min_area = float(cur_det.get("min_area", 0.0) or 0.0)
        if "min_area" in d:
            try:
                min_area = float(d["min_area"])
            except (TypeError, ValueError):
                min_area = -1.0
            if not 0.0 <= min_area <= 1.0:
                errors.append("Minsta storlek måste vara mellan 0 och 1 (andel av bildytan).")
        max_area = float(cur_det.get("max_area", 1.0) or 1.0)
        if "max_area" in d:
            try:
                max_area = float(d["max_area"])
            except (TypeError, ValueError):
                max_area = 2.0
            if not 0.0 <= max_area <= 1.0:
                errors.append("Max storlek måste vara mellan 0 och 1 (andel av bildytan).")
        if min_area > max_area:
            errors.append("Minsta storlek får inte vara större än max storlek.")
        class_scores = str(cur_det.get("class_scores", "") or "").strip()
        if "class_scores" in d:
            parsed = CameraWorker._parse_class_scores(str(d.get("class_scores") or ""))
            if any(v < 0.0 or v > 1.0 for v in parsed.values()):
                errors.append("Klass-konfidenser måste ligga mellan 0 och 1 (t.ex. car=0.6, person=0.5).")
            class_scores = ", ".join(f"{k}={v:g}" for k, v in sorted(parsed.items()))
        # Pixel-motion-gate: kör YOLO bara vid rörelse (av som standard)
        motion_gate = bool(cur_det.get("motion_gate", False))
        if "motion_gate" in d:
            motion_gate = _to_bool(d.get("motion_gate", motion_gate), motion_gate)
        motion_thr = float(cur_det.get("motion_threshold", 5.0) or 5.0)
        if "motion_threshold" in d:
            try:
                motion_thr = float(d["motion_threshold"])
            except (TypeError, ValueError):
                motion_thr = -1.0
            if not 1.0 <= motion_thr <= 255.0:
                errors.append("Rörelsekänsligheten måste vara mellan 1 och 255.")
        lpr_enabled = bool(cur_det.get("lpr_enabled", False))
        if "lpr_enabled" in d:
            lpr_enabled = _to_bool(d.get("lpr_enabled"), lpr_enabled)
        lpr_engine = str(cur_det.get("lpr_engine", config.LPR_ENGINE) or config.LPR_ENGINE).lower()
        if "lpr_engine" in d:
            lpr_engine = str(d.get("lpr_engine") or "").strip().lower()
            if lpr_engine not in ("easyocr", "paddleocr"):
                errors.append("OCR-motorn måste vara easyocr eller paddleocr.")
        # Model/conf/device delas med stillbildsanalysen via analyzer + RUNTIME
        model_changed = False
        model = RUNTIME["model"]
        if "model" in d:
            model = str(d["model"] or "").strip()
            if not model:
                errors.append("YOLO-modellen får inte vara tom.")
            elif model != RUNTIME["model"]:
                model_changed = True
        conf = RUNTIME["conf"]
        if "conf" in d:
            try:
                conf = float(d["conf"])
            except (TypeError, ValueError):
                conf = -1.0
            if not 0.01 <= conf <= 1.0:
                errors.append("Konfidensen måste vara mellan 0.01 och 1.0.")
        device = RUNTIME["device"]
        device_changed = False
        if "device" in d:
            device = str(d["device"] or "").strip()
            if device not in _KNOWN_DEVICES:
                errors.append(f"Enheten måste vara en av: {', '.join(_KNOWN_DEVICES)}.")
            elif device != RUNTIME["device"]:
                device_changed = True
        if not errors:
            pending_det = {"yolo_enabled": yolo_en, "ai_fps": af, "imgsz": imgsz}
            env_write["YOLO_STREAM_FPS"] = str(af)
            env_write["YOLO_IMG_SIZE"] = str(imgsz)
            if "min_score" in d:
                pending_det["min_score"] = min_score
                env_write["CAMERA_FILTER_MIN_SCORE"] = str(round(min_score, 3))
            if "min_area" in d:
                pending_det["min_area"] = min_area
                env_write["CAMERA_FILTER_MIN_AREA"] = str(round(min_area, 4))
            if "max_area" in d:
                pending_det["max_area"] = max_area
                env_write["CAMERA_FILTER_MAX_AREA"] = str(round(max_area, 4))
            if "class_scores" in d:
                pending_det["class_scores"] = class_scores
                env_write["CAMERA_FILTER_CLASS_SCORES"] = class_scores
            if "motion_gate" in d:
                pending_det["motion_gate"] = motion_gate
                env_write["MOTION_GATE_ENABLED"] = "true" if motion_gate else "false"
            if "motion_threshold" in d:
                pending_det["motion_threshold"] = motion_thr
                env_write["MOTION_GATE_THRESHOLD"] = str(round(motion_thr, 1))
            if "lpr_enabled" in d:
                pending_det["lpr_enabled"] = lpr_enabled
                env_write["LPR_ENABLED"] = "true" if lpr_enabled else "false"
            if "lpr_engine" in d:
                pending_det["lpr_engine"] = lpr_engine
                env_write["LPR_ENGINE"] = lpr_engine
            if model_changed:
                env_write["YOLO_MODEL"] = model
                requires.append("yolo_reload")
            if "conf" in d and conf != RUNTIME["conf"]:
                env_write["YOLO_CONF"] = str(conf)
            if device_changed:
                env_write["YOLO_DEVICE"] = device
                requires.append("yolo_reload")

    # ------------------------- Live-stream ----------------------------
    if body.get("live"):
        lv = dict(body["live"])
        enabled = _to_bool(lv.get("enabled", cur_live["enabled"]), cur_live["enabled"])
        dfps = int(cur_live["display_fps"])
        if "display_fps" in lv:
            try:
                dfps = int(lv["display_fps"])
            except (TypeError, ValueError):
                dfps = 0
            if not 1 <= dfps <= 30:
                errors.append("Visnings-FPS (display FPS) måste vara mellan 1 och 30.")
        jq = int(cur_live["jpeg_quality"])
        if "jpeg_quality" in lv:
            try:
                jq = int(lv["jpeg_quality"])
            except (TypeError, ValueError):
                jq = 0
            if not 20 <= jq <= 100:
                errors.append("JPEG-kvaliteten måste vara mellan 20 och 100.")
        show_boxes = _to_bool(lv.get("show_boxes", cur_live["show_boxes"]), cur_live["show_boxes"])
        show_labels = _to_bool(lv.get("show_labels", cur_live["show_labels"]), cur_live["show_labels"])
        show_conf = _to_bool(lv.get("show_conf", cur_live["show_conf"]), cur_live["show_conf"])
        if not errors:
            pending_live = {
                "enabled": enabled, "display_fps": dfps, "jpeg_quality": jq,
                "show_boxes": show_boxes, "show_labels": show_labels,
                "show_conf": show_conf,
            }
            env_write.update({
                "LIVE_STREAM_ENABLED": "true" if enabled else "false",
                "LIVE_STREAM_FPS": str(dfps),
                "LIVE_JPEG_QUALITY": str(jq),
                "LIVE_SHOW_BOXES": "true" if show_boxes else "false",
                "LIVE_SHOW_LABELS": "true" if show_labels else "false",
                "LIVE_SHOW_CONF": "true" if show_conf else "false",
            })

    # ------------------------- HA-event (nya detektioner) ------------
    if body.get("events"):
        e = dict(body["events"])
        en = _to_bool(e.get("enabled", cur_ev["enabled"]), cur_ev["enabled"])
        classes = str(e.get("classes", cur_ev["classes"]) or "").strip()
        toks = [t.strip() for t in classes.split(",") if t.strip()]
        if not toks:
            errors.append("Ange minst en händelseklass (t.ex. person, car, cat, dog).")
        classes = ",".join(sorted({t.lower() for t in toks}))

        def _clamp(v, cur, lo, hi, name):
            try:
                val = float(v)
            except (TypeError, ValueError):
                val = float(cur)
            if not lo <= val <= hi:
                errors.append(f"{name} måste vara mellan {lo:g} och {hi:g}.")
            return val

        ca = _clamp(e.get("clear_after", cur_ev["clear_after"]), cur_ev["clear_after"], 1.0, 120.0, "Vila innan återaktivering")
        hd = _clamp(e.get("hold", cur_ev["hold"]), cur_ev["hold"], 1.0, 300.0, "ON-tid i HA")
        mi = _clamp(e.get("min_interval", cur_ev["min_interval"]), cur_ev["min_interval"], 0.5, 300.0, "Minsta intervall")
        sg = _clamp(e.get("startup_grace", cur_ev["startup_grace"]), cur_ev["startup_grace"], 0.0, 120.0, "Start-grace")
        mc = _clamp(e.get("min_conf", cur_ev["min_conf"]), cur_ev["min_conf"], 0.0, 1.0, "Lägsta konfidens för händelse")
        if not errors:
            pending_events = {
                "enabled": en,
                "classes": classes,
                "min_conf": mc,
                "clear_after": ca,
                "hold": hd,
                "min_interval": mi,
                "startup_grace": sg,
            }
            env_write.update({
                "LIVE_EVENT_ENABLED": "true" if en else "false",
                "LIVE_EVENT_CLASSES": classes,
                "LIVE_EVENT_MIN_CONF": str(round(mc, 2)),
                "LIVE_EVENT_CLEAR_AFTER": str(round(ca, 1)),
                "LIVE_EVENT_HOLD": str(round(hd, 1)),
                "LIVE_EVENT_MIN_INTERVAL": str(round(mi, 2)),
                "LIVE_EVENT_STARTUP_GRACE": str(round(sg, 1)),
            })

    # ------------------------------ Apply -----------------------------
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)

    if pending_cam is not None:
        # Bakåtkompatibilitet: camera-gruppen i /api/settings styr första
        # kameran (eller lägger till om ingen finns). Nytt GUI använder /api/cameras.
        dw = pool.default()
        if dw is not None:
            pool.update(dw.camera_id, pending_cam)
        else:
            pool.add(pending_cam)
    if pending_det is not None:
        pool.apply_all("detect", pending_det)
        # Model/conf/device -> delad analyzer (live + stillbilder)
        if "model" in body.get("detect", {}) or "conf" in body.get("detect", {}) or "device" in body.get("detect", {}):
            RUNTIME["model"] = body["detect"].get("model", RUNTIME["model"])
            if "conf" in body["detect"]:
                RUNTIME["conf"] = body["detect"]["conf"]
            if "device" in body["detect"]:
                RUNTIME["device"] = body["detect"]["device"]
            analyzer.configure(
                model=RUNTIME["model"], conf=RUNTIME["conf"], device=RUNTIME["device"]
            )
            if "model" in body["detect"]:
                start_yolo_model_download(str(RUNTIME["model"]))
    if pending_live is not None:
        pool.apply_all("live", pending_live)
    if pending_events is not None:
        pool.apply_all("events", pending_events)

    if env_write:
        if not config.persist_env(env_write):
            return JSONResponse(
                {"ok": False, "errors": ["Kunde inte spara inställningarna till .env."]},
                status_code=500,
            )
        print(f"[settings] sparade till .env: {', '.join(env_write)}")

    # Globala värden ska även synas för nya/kommande kameror (runtime)
    _sync_config_attrs(env_write)

    dw = pool.default()
    return {
        "ok": True,
        "saved": True,
        "requires": requires,
        "runtime": dw.status() if dw is not None else None,
    }


@app.get("/media/{name}")
def media(name: str):
    path = (config.MEDIA_DIR / name).resolve()
    if not str(path).startswith(str(config.MEDIA_DIR.resolve())) or not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path)


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    model: str = Form(""),
    conf: float | None = Form(None),
    use_llm: bool = Form(False),
    prompt: str = Form(""),
    use_ha: bool = Form(False),
    camera: str = Form("cam"),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED))}")

    filename = f"{uuid.uuid4().hex}{ext}"
    upload_path = config.UPLOAD_DIR / filename
    upload_path.write_bytes(await file.read())
    result = await asyncio.to_thread(
        _run_pipeline, upload_path, model, conf, use_llm, prompt, use_ha, camera
    )
    return JSONResponse(result)


@app.post("/api/analyze-url")
async def analyze_url(
    url: str = Form(...),
    model: str = Form(""),
    conf: float | None = Form(None),
    use_llm: bool = Form(False),
    prompt: str = Form(""),
    use_ha: bool = Form(False),
    camera: str = Form("cam"),
):
    """HA-push endpoint: HA saves a Reolink snapshot, then POSTs its URL here."""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        content = resp.content
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not fetch image from HA ({url}): {exc}") from exc

    ext = Path(urlparse(url).path).suffix.lower()
    if ext not in ALLOWED:
        ext = ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    upload_path = config.UPLOAD_DIR / filename
    upload_path.write_bytes(content)
    result = await asyncio.to_thread(
        _run_pipeline, upload_path, model, conf, use_llm, prompt, use_ha, camera
    )
    return JSONResponse(result)


def _run_pipeline(upload_path, model: str, conf: float | None, use_llm: bool, prompt: str, use_ha: bool, camera: str = "cam") -> dict:
    """Shared YOLO + LLM + HA pipeline used by /api/analyze and /api/analyze-url."""
    model = model or RUNTIME["model"]
    conf = conf if conf is not None else RUNTIME["conf"]
    use_llm = bool(use_llm or RUNTIME["use_llm"])
    prompt = prompt or RUNTIME["prompt"]

    result = analyzer.analyze(upload_path, model=model, conf=conf)
    yolo_summary = summarize_detections(result["detections"])

    response = {
        "camera": camera,
        "filename": upload_path.name,
        "detections": result["detections"],
        "summary": yolo_summary,
        "yolo_summary": yolo_summary,
        "counts": categorize_detections(result["detections"]),
        "annotated_url": f"/media/{Path(result['annotated']).name}" if result["annotated"] else None,
        "model": result["model"],
        "inference_ms": result["inference_ms"],
        "error": result["error"],
        "description": None,
        "llm_error": None,
        "ha_error": None,
    }

    if use_llm and not result["error"]:
        try:
            desc = describe_with_ollama(
                upload_path, model=RUNTIME["llm_model"], prompt=prompt
            )
            response["description"] = desc
            has_dets = bool(result["detections"])
            if desc and not _is_prompt_echo(desc, prompt) and not _is_low_quality(desc):
                if has_dets and _llm_says_nothing(desc):
                    # LLM:en missade objekten som YOLO ser -> behåll YOLO-sammanfattningen
                    response["description"] = None
                    response["llm_error"] = (
                        "Vision LLM såg inget trots att YOLO detekterade objekt - "
                        "visar YOLO-sammanfattningen."
                    )
                else:
                    # The LLM actually sees the scene -> it is authoritative
                    response["summary"] = desc
            elif desc:
                # LLM:en ekade prompten eller gav ett repetitivt svar
                # (t.ex. "Topshop 1. Topshop 2. ...") -> behåll YOLO-sammanfattningen
                response["description"] = None
                response["llm_error"] = (
                    "Vision LLM gav ett repetitivt/ekande svar - visar "
                    "YOLO-sammanfattningen. Prova en annan prompt."
                )
        except Exception as exc:  # noqa: BLE001 - degrade gracefully to YOLO-only
            response["llm_error"] = f"Vision LLM failed: {exc}"

    if use_ha:
        try:
            ha.publish_result(
                detections=result["detections"],
                description=response["description"],
                annotated_path=result["annotated"],
                camera=camera,
            )
        except Exception as exc:  # noqa: BLE001 - YOLO result still returned
            response["ha_error"] = f"Home Assistant publish failed: {exc}"

    HISTORY.append(
        {
            "ts": int(time.time()),
            "camera": camera,
            "summary": response["summary"],
            "counts": response["counts"],
            "detections": result["detections"],
            "model": response["model"],
            "inference_ms": response["inference_ms"],
            "error": bool(result["error"]),
        }
    )
    return response


# --------------------------------------------------------------------------
# LPR-test: ladda upp en bild, kör YOLO -> fordon -> OCR-skylt (test-sida).
# --------------------------------------------------------------------------
_LPR_TEST_READER = None
_LPR_TEST_READER_ENGINE = None
_LPR_TEST_READER_LOCK = threading.Lock()
_VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "vehicle"}


def _get_lpr_test_reader(engine: str):
    """Cached PlateReader for the LPR test page (OCR-laddning är tung)."""
    global _LPR_TEST_READER, _LPR_TEST_READER_ENGINE
    engine = (engine or config.LPR_ENGINE).strip().lower()
    if engine not in ("easyocr", "paddleocr"):
        engine = config.LPR_ENGINE
    with _LPR_TEST_READER_LOCK:
        if _LPR_TEST_READER is None or _LPR_TEST_READER_ENGINE != engine:
            from license_plate import PlateReader

            _LPR_TEST_READER = PlateReader(
                engine=engine,
                language=config.LPR_LANGUAGE,
                min_conf=config.LPR_MIN_CONF,
            )
            _LPR_TEST_READER_ENGINE = engine
        return _LPR_TEST_READER


@app.post("/api/lpr/test")
async def lpr_test(
    file: UploadFile = File(...),
    engine: str = Form(""),
    min_conf: float | None = Form(None),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(
            400,
            f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED))}",
        )
    filename = f"{uuid.uuid4().hex}{ext}"
    upload_path = config.UPLOAD_DIR / filename
    upload_path.write_bytes(await file.read())
    result = await asyncio.to_thread(_run_lpr_test, upload_path, engine, min_conf)
    return JSONResponse(result)


def _run_lpr_test(upload_path, engine: str, min_conf: float | None) -> dict:
    """YOLO fordon -> OCR-skylt -> annoterad bild med skylttext."""
    import cv2

    reader = _get_lpr_test_reader(engine)
    if min_conf is not None:
        reader.min_conf = min(1.0, max(0.1, float(min_conf)))
    result = analyzer.analyze(upload_path)
    detections = result.get("detections") or []
    try:
        frame = cv2.imread(str(upload_path))
    except Exception:  # noqa: BLE001 - utan bild kan vi inte rita/OCR:a
        frame = None

    done = []
    for d in detections:
        entry = dict(d)
        if d.get("class") in _VEHICLE_CLASSES and frame is not None:
            try:
                plate = reader.read_vehicle(frame, d.get("box"))
            except Exception as exc:  # noqa: BLE001 - OCR får inte stoppa testet
                plate = None
                entry["plate_error"] = str(exc)
            entry["plate"] = plate["text"] if plate else None
            entry["plate_confidence"] = plate["confidence"] if plate else None
        else:
            entry["plate"] = None
            entry["plate_confidence"] = None
        done.append(entry)

    annotated_path = None
    if frame is not None and detections:
        for d in done:
            box = d.get("box")
            if not box or len(box) < 4:
                continue
            x1, y1, x2, y2 = (int(round(float(v))) for v in box[:4])
            if d.get("plate"):
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
                label = f"{d['plate']} {round(float(d['plate_confidence'] or 0) * 100)}%"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                top = max(0, y1 - th - 12)
                cv2.rectangle(frame, (x1, top), (x1 + tw + 4, y1), (0, 200, 0), -1)
                cv2.putText(
                    frame, label, (x1 + 2, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA,
                )
            else:
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 1)
        try:
            out = config.MEDIA_DIR / f"lpr_{int(time.time() * 1000)}.jpg"
            cv2.imwrite(str(out), frame)
            annotated_path = str(out)
        except Exception:  # noqa: BLE001 - fallback till YOLO-annoteringen
            annotated_path = result.get("annotated")
    else:
        annotated_path = result.get("annotated")

    return {
        "engine": reader.engine,
        "detections": done,
        "plates": [
            {
                "text": p.get("plate"),
                "confidence": p.get("plate_confidence"),
                "class": p.get("class"),
                "box": p.get("box"),
            }
            for p in done
            if p.get("plate")
        ],
        "annotated_url": f"/media/{Path(annotated_path).name}" if annotated_path else None,
        "model": result.get("model"),
        "inference_ms": result.get("inference_ms"),
        "error": result.get("error"),
    }


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


if __name__ == "__main__":
    # Bind 0.0.0.0 so the app is reachable through the container's network
    # interface (Docker port mapping). 127.0.0.1 would only be reachable from
    # inside the container itself.
    uvicorn.run(app, host="0.0.0.0", port=8000)
