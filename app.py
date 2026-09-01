"""Camera AI test GUI — upload pictures, run YOLO detection, get a small-LLM description.

Run:  python app.py        (then open http://127.0.0.1:8000)
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from analyzer import (
    YoloAnalyzer,
    active_ollama_model,
    categorize_detections,
    describe_with_ollama,
    llm_available,
    ollama_models,
    ollama_models_error,
    set_llm_keep_alive,
    summarize_detections,
)
from ha_client import HAClient

analyzer = YoloAnalyzer()
ha = HAClient(config)

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
START_TIME = time.time()


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
    bilden (moondream gör ibland det när prompten innehåller exempel)."""
    import re

    if not text or not prompt:
        return False
    norm = lambda s: re.sub(r"[^a-zåäö0-9 ]", " ", s.lower())
    t, p = norm(text), norm(prompt)
    return bool(p and (p in t or t in p))


_STOPWORDS = frozenset({
    "en", "ett", "och", "att", "med", "på", "i", "för", "av", "som", "är",
    "det", "den", "de", "till", "har", "man", "men", "inte", "eller", "om",
    "vid", "från", "under", "över", "detta", "the", "a", "an", "and", "with",
    "of", "in", "on", "for", "to", "is", "are",
})


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
    env_file = config.BASE_DIR / ".env"
    try:
        lines = (
            env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
        )
        out = []
        for line in lines:
            if "=" in line:
                key = line.split("=", 1)[0].strip()
                if key in to_write:
                    out.append(f"{key}={to_write.pop(key)}")
                    continue
            out.append(line)
        for key, val in to_write.items():
            out.append(f"{key}={val}")
        env_file.write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"[config] sparade till .env: {', '.join(_ENV_KEYS.get(k, k) for k in changes if _ENV_KEYS.get(k))}")
    except OSError as exc:
        print(f"[config] kunde inte spara .env: {exc}")


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
    yield


app = FastAPI(title="Camera AI", version=config.VERSION, lifespan=lifespan)

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


@app.get("/api/ollama/models")
def ollama_models_api():
    names = sorted(m.get("name", "") for m in ollama_models())
    return {
        "models": names,
        "ollama_available": llm_available(),
        "ollama_error": ollama_models_error(),
    }


@app.get("/api/history")
def get_history(limit: int = 20):
    """Recent analyses, newest first."""
    items = list(HISTORY)
    return items[-limit:][::-1]


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
    return FileResponse(config.BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health():
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
    }


@app.get("/api/ha/status")
def ha_status():
    return ha.status()


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
            if desc and not _is_prompt_echo(desc, prompt) and not _is_low_quality(desc):
                # The LLM actually sees the scene -> it is authoritative
                response["summary"] = desc
            elif desc:
                # LLM:en ekade prompten eller gav ett repetitivt svar
                # (t.ex. "Topshop 1. Topshop 2. ...") -> behåll YOLO-sammanfattningen
                response["description"] = None
                response["llm_error"] = (
                    "Vision LLM gav ett repetitivt/ekande svar (t.ex. upprepade ord) - "
                    "visar YOLO-sammanfattningen. Prova en annan prompt eller en bättre "
                    "modell (t.ex. llava) i inställningarna."
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


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


if __name__ == "__main__":
    # Bind 0.0.0.0 so the app is reachable through the container's network
    # interface (Docker port mapping). 127.0.0.1 would only be reachable from
    # inside the container itself.
    uvicorn.run(app, host="0.0.0.0", port=8000)
