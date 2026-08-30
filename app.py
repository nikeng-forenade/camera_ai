"""Camera AI test GUI — upload pictures, run YOLO detection, get a small-LLM description.

Run:  python app.py        (then open http://127.0.0.1:8000)
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
from analyzer import (
    YoloAnalyzer,
    active_ollama_model,
    describe_with_ollama,
    llm_available,
    summarize_detections,
)
from ha_client import HAClient

analyzer = YoloAnalyzer()
ha = HAClient(config)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        ha.connect()
    except Exception as exc:  # noqa: BLE001 - never crash the server on HA failure
        print(f"[ha] startup connect failed: {exc}")
    yield


app = FastAPI(title="Camera AI", version="0.1.0", lifespan=lifespan)

ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@app.get("/")
def index():
    return FileResponse(config.BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "yolo_model": analyzer.model_name,
        "llm_backend": config.LLM_BACKEND,
        "ollama_available": llm_available(),
        "llm_model": active_ollama_model() if config.LLM_BACKEND == "ollama" else None,
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
    model: str = Form(config.DEFAULT_MODEL),
    conf: float = Form(config.DEFAULT_CONF),
    use_llm: bool = Form(False),
    prompt: str = Form(""),
    use_ha: bool = Form(False),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED))}")

    filename = f"{uuid.uuid4().hex}{ext}"
    upload_path = config.UPLOAD_DIR / filename
    upload_path.write_bytes(await file.read())

    result = analyzer.analyze(upload_path, model=model, conf=conf)

    response = {
        "filename": filename,
        "detections": result["detections"],
        "summary": summarize_detections(result["detections"]),
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
            response["description"] = describe_with_ollama(upload_path, prompt=prompt or None)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully to YOLO-only
            response["llm_error"] = f"Vision LLM failed: {exc}"

    if use_ha:
        try:
            ha.publish_result(
                detections=result["detections"],
                description=response["description"],
                annotated_path=result["annotated"],
            )
        except Exception as exc:  # noqa: BLE001 - YOLO result still returned
            response["ha_error"] = f"Home Assistant publish failed: {exc}"

    return JSONResponse(response)


app.mount("/static", StaticFiles(directory=config.BASE_DIR / "static"), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
