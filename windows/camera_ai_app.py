"""Camera AI - Windows desktop launcher.

Starts the Camera AI web server and opens a native window (pywebview) with the
existing web GUI, so it behaves like a desktop app. Falls back to the default
browser if pywebview is unavailable.

Run:  python windows/camera_ai_app.py      (or double-click windows/start.bat)

YOLO runs on the Intel Arc GPU via OpenVINO (YOLO_DEVICE=openvino:GPU -> intel:gpu),
and the vision LLM (Ollama) can use the Arc GPU via the Vulkan backend
(set the OLLAMA_VULKAN=1 environment variable before starting Ollama).
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

# Make the repo root importable (this file lives in windows/) and use it as CWD.
# In a PyInstaller build the app data lives next to the .exe.
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

LOG_FILE = Path(__file__).resolve().parent / "camera_ai.log"
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("camera_ai_app")

# Bind 0.0.0.0 so Home Assistant on another machine can reach the REST API.
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
URL = f"http://127.0.0.1:{PORT}"

ICON_ICO = Path(__file__).resolve().parent / "camera_ai.ico"

_window = None  # pywebview window, set in main()


def _ensure_icon() -> str | None:
    """Skapa en appikon (ICO) med Pillow om den inte redan finns."""
    if ICON_ICO.exists():
        return str(ICON_ICO)
    try:
        from PIL import Image, ImageDraw

        size = 256
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((8, 8, size - 8, size - 8), radius=48, fill=(22, 33, 66, 255))
        d.ellipse((size // 2 - 78, size // 2 - 78, size // 2 + 78, size // 2 + 78),
                  outline=(120, 200, 255, 255), width=16)
        d.ellipse((size // 2 - 34, size // 2 - 34, size // 2 + 34, size // 2 + 34),
                  fill=(120, 200, 255, 255))
        d.rounded_rectangle((size // 2 - 42, 42, size // 2 + 42, 88), radius=16,
                            fill=(120, 200, 255, 255))
        img.save(ICON_ICO, format="ICO",
                 sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return str(ICON_ICO)
    except Exception as exc:  # noqa: BLE001 - ikon är bara kosmetisk
        log.warning("could not create app icon: %s", exc)
        return None


def run_server() -> None:
    """Run the FastAPI app with uvicorn in a background thread."""
    try:
        import uvicorn

        import app as server  # repo root is on sys.path

        log.info("starting server on %s:%s", HOST, PORT)
        uvicorn.run(server.app, host=HOST, port=PORT, log_level="warning")
    except Exception as exc:  # noqa: BLE001 - aldrig dö tyst
        log.exception("server thread failed: %s", exc)
        # Kasta vidare så --server-läget avslutas med felkod och Task Scheduler
        # ser felet (icke-noll) samt kan starta om aktiviteten automatiskt.
        raise


def _show_window() -> None:
    global _window
    if _window is not None:
        _window.show()
        _window.restore()
        _window.focus()


def _run_tray() -> None:
    """System tray-ikon (pystray): öppna fönstret eller avsluta."""
    try:
        import pystray
        from PIL import Image

        icon_img = Image.open(ICON_ICO) if ICON_ICO.exists() else Image.new("RGB", (64, 64), "navy")
        menu = pystray.Menu(
            pystray.MenuItem("Öppna Camera AI", lambda *_: _show_window(), default=True),
            pystray.MenuItem("Avsluta", lambda *_: os._exit(0)),
        )
        pystray.Icon("camera_ai", icon_img, "Camera AI", menu).run()
    except Exception as exc:  # noqa: BLE001 - tray är valfri
        log.warning("tray icon unavailable: %s", exc)


def main() -> None:
    # Headless server mode (--server): bara webbservern, inget fönster/tray.
    if "--server" in sys.argv:
        log.info("headless server mode (--server)")
        try:
            run_server()  # blockerar (uvicorn.run)
        except Exception:  # noqa: BLE001
            log.exception("server stopped with error")
            sys.exit(1)
        return

    global _window
    import importlib.util as _util

    use_tray = _util.find_spec("pystray") is not None

    _ensure_icon()  # skapar camera_ai.ico (används av tray-ikonen)
    threading.Thread(target=run_server, daemon=True).start()
    if use_tray:
        threading.Thread(target=_run_tray, daemon=True).start()

    try:
        import webview  # pywebview

        log.info("opening pywebview window: %s", URL)
        _window = webview.create_window(
            "Camera AI",
            URL,
            width=1200,
            height=820,
            min_size=(900, 600),
            # Observera: pywebview 6.x create_window() har inget 'icon'-argument.
            # Fönster-/taskbar-ikonen kommer från exe:n (byggd med --icon).
        )
        if use_tray:
            # Stänga fönstret = minimera till tray (avsluta via tray-ikonen).
            _window.events.closed += _show_window
        webview.start()
    except Exception as exc:  # noqa: BLE001 - fall back to the browser
        log.exception("pywebview window failed, using browser: %s", exc)
        import webbrowser

        webbrowser.open(URL)
        print(f"Camera AI running at {URL} - press Ctrl+C to stop.")
        try:
            while True:
                input()
        except (KeyboardInterrupt, EOFError):
            pass


if __name__ == "__main__":
    main()
