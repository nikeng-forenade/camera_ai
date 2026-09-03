"""Camera AI - live-kamera-worker (Reolink RTSP -> YOLO -> Dashboard).

En enda RTSP-session per kamera. Den senaste bilden (latest frame) delas av
live-visningen och YOLO - inga växande köer. YOLO körs schemalagt (AI FPS) på
den senaste bilden och överlagringen (boxes) ritas + JPEG-kodas i display-FPS-
takt. Vid tappad anslutning återanvänds samma worker (reconnect - inga nya
trådar per försök). Workern kraschar aldrig servern: alla fel hamnar i
statusfältet så GUI/API fungerar även utan kamera.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from urllib.parse import quote

import cv2  # finns via ultralytics (requirements: opencv-python)

import config
from analyzer import annotate_frame_bgr


def _slugify(name: str) -> str:
    """Gör ett kamera-namn till ett säkert id (t.ex. 'Garden 2' -> 'garden-2')."""
    s = re.sub(r"[^a-z0-9åäö]+", "-", (name or "").lower()).strip("-")
    return s or "kam"

# Kamera-states (lättare att hantera i GUI/API än magiska strängar)
CAM_DISABLED = "disabled"
CAM_CONNECTING = "connecting"
CAM_ONLINE = "online"
CAM_RECONNECTING = "reconnecting"
CAM_OFFLINE = "offline"
CAM_ERROR = "error"

YOLO_STOPPED = "stopped"
YOLO_LOADING = "loading"
YOLO_RUNNING = "running"
YOLO_ERROR = "error"


def _draw_roi_line(img, roi_cfg):
    """Rita detektionsöverlägg: vågrät linje och/eller zonpolygoner.

    Inga text-etiketter – bara linjen/polygonerna så bilden blir ren.
    ``roi_cfg`` = {"line": {"enabled","roi_y","roi_side"},
    "zones": {"enabled","polys","mode"}} – båda kan vara på samtidigt.
    """
    if not roi_cfg:
        return img
    h, w = img.shape[:2]
    # --- Vågrät linje ---
    line = roi_cfg.get("line") or {}
    if line.get("enabled"):
        y = int(round(float(line.get("roi_y", 0.5)) * h))
        y = min(max(y, 0), h - 1)
        cv2.line(img, (0, y), (w, y), (255, 60, 60), 2, cv2.LINE_AA)  # BGR röd
    # --- Zonpolygoner ---
    zones = roi_cfg.get("zones") or {}
    items = zones.get("items") or []
    if zones.get("enabled") and items:
        import numpy as np

        for it in items:
            raw_p = it.get("points") or []
            if len(raw_p) < 3:
                continue
            # watch = grön (bevaka), mask = röd (övervaka INTE)
            color = (80, 230, 120) if it.get("kind", "watch") == "watch" else (48, 59, 255)
            poly = np.array(
                [[int(float(p[0]) * w), int(float(p[1]) * h)] for p in raw_p], np.int32
            ).reshape(-1, 1, 2)
            cv2.polylines(img, [poly], True, color, 2, cv2.LINE_AA)
            for p in poly.reshape(-1, 2):
                cv2.circle(img, (int(p[0]), int(p[1])), 4, color, -1, cv2.LINE_AA)
    return img


class _FpsMeter:
    """Rullande FPS-mätare (EMA-fönster av tidsstämplar)."""

    def __init__(self, window: int = 25):
        self._t: deque = deque(maxlen=window)

    def tick(self, t: float | None = None) -> None:
        self._t.append(t if t is not None else time.time())

    def fps(self) -> float:
        if len(self._t) < 2:
            return 0.0
        dt = self._t[-1] - self._t[0]
        if dt <= 0:
            return 0.0
        return round((len(self._t) - 1) / dt, 1)

    def reset(self) -> None:
        self._t.clear()


class _EventTracker:
    """Avgör när en händelseklass blir NY (löser statiska objekt).

    Statiska objekt (t.ex. en parkerad bil på uppfarten) ska inte skapa
    händelser hela tiden. Därför hålls klassen som "aktiv" tills den varit
    BORTA i ``clear_after`` sekunder - en händelse skapas bara när klassen
    faktiskt dyker upp (efter att ha varit frånvarande) eller kommer tillbaka
    efter ett uppehåll. En bil som står stilla genererar alltså bara en enda
    händelse när den först sågs.
    """

    def __init__(self) -> None:
        self._active: dict[str, float] = {}   # klass -> tidpunkt aktiv
        self._absent_since: dict[str, float] = {}
        self._streak: dict[str, int] = {}     # antal på varandra följande inferenser

    def update(self, present: set, now: float, clear_after: float) -> list:
        """Anropa varje AI-tick. Returnerar klasser som blivit nya (fire)."""
        fired: list[str] = []
        # Uppdatera aktiva klasser: har de varit borta tillräckligt länge?
        for cls in list(self._active):
            if cls in present:
                self._absent_since.pop(cls, None)
                self._streak[cls] = self._streak.get(cls, 0) + 1
            else:
                a = self._absent_since.get(cls)
                if a is None:
                    a = now
                    self._absent_since[cls] = a
                if now - a >= clear_after:
                    self._active.pop(cls)
                    self._absent_since.pop(cls)
                    self._streak[cls] = 0
        # Nya kandidater: kräv 2 på varandra följande inferenser (mindre
        # falska utlösningar på enstaka felklassningar).
        for cls in present:
            if cls in self._active:
                continue
            streak = self._streak.get(cls, 0) + 1
            self._streak[cls] = streak
            if streak >= 2:
                self._active[cls] = now
                self._streak[cls] = 0
                fired.append(cls)
        # Städa streaks som inte längre är relevanta
        for cls in list(self._streak):
            if cls not in present and cls not in self._active and self._streak.get(cls) == 0:
                self._streak.pop(cls, None)
        return fired

    def reset(self) -> None:
        self._active.clear()
        self._absent_since.clear()
        self._streak.clear()


def _quote_cred(value: str) -> str:
    return quote((value or ""), safe="")


def build_rtsp_url(
    host: str = "",
    user: str = "",
    password: str = "",
    path: str = "",
    full_url: str = "",
) -> str:
    """Bygg en RTSP-URL av delar (säkert - specialtecken i lösenord URL-kodas).

    Om ``full_url`` är satt används den som den är (legacy/avancerat).
    """
    full = (full_url or "").strip()
    if full:
        return full
    h = (host or "").strip()
    if not h:
        return ""
    if "://" not in h:
        h = "rtsp://" + h
    scheme, rest = h.split("://", 1)
    if "@" in rest:
        rest = rest.split("@", 1)[1]  # ev. inbäddade credentials ignoreras
    p = (path or "/Preview_01_sub").strip()
    if p and not p.startswith("/"):
        p = "/" + p
    cred = ""
    if user or password:
        cred = f"{_quote_cred(user)}:{_quote_cred(password)}@"
    return f"{scheme}://{cred}{rest}{p}"


def redact_rtsp_url(url: str) -> str:
    """Maskera lösenord i en RTSP-URL för loggning: user:*****@host."""
    try:
        if not url:
            return ""
        if "://" not in url:
            return url
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            pre, host = rest.split("@", 1)
            user = pre.split(":", 1)[0]
            return f"{scheme}://{user}:*****@{host}"
        return f"{scheme}://{rest}"
    except Exception:  # noqa: BLE001 - maskering får aldrig krascha
        return "<url>"


def test_rtsp(
    host: str = "",
    user: str = "",
    password: str = "",
    path: str = "",
    full_url: str = "",
    timeout: float = 8.0,
) -> dict:
    """Testanslut mot en RTSP-kamera (stör inte aktiv worker).

    Returnerar {ok, width, height, fps, codec, latency_ms, url, error}.
    """
    url = build_rtsp_url(host, user, password, path, full_url)
    if not url:
        return {"ok": False, "error": "RTSP-adress saknas (ange kamera-IP)."}
    cap = None
    start = time.time()
    try:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        for prop in ("CAP_PROP_OPEN_TIMEOUT_MSEC", "CAP_PROP_READ_TIMEOUT_MSEC"):
            p = getattr(cv2, prop, None)
            if p:
                try:
                    cap.set(p, int(timeout * 1000))
                except cv2.error:
                    pass
        if not cap.isOpened():
            return {
                "ok": False,
                "url": redact_rtsp_url(url),
                "error": (
                    "Kunde inte ansluta till kameran. Kontrollera IP, "
                    "användarnamn/lösenord och att kameran är nåbar."
                ),
            }
        got_frame = False
        while time.time() - start < timeout:
            ret, frame = cap.read()
            if ret and frame is not None:
                got_frame = True
                break
            if cv2.waitKey(1) == 27:  # noqa: S110 - ESC avbryter
                break
        if not got_frame:
            return {
                "ok": False,
                "url": redact_rtsp_url(url),
                "error": (
                    "Ingen bild mottogs inom tidsgränsen (RTSP-timeout). "
                    "Kontrollera strömmen (sub-stream rekommenderas för YOLO)."
                ),
            }
        h, w = frame.shape[:2]
        # Mät faktisk bildhastighet genom att läsa några frames till
        n, s = 0, time.time()
        while n < 6 and time.time() - s < 2.0:
            ret2, _f2 = cap.read()
            if not ret2 or _f2 is None:
                break
            n += 1
        eff = (n / (time.time() - s)) if time.time() > s and n else 0.0
        codec_int = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
        codec = "".join(
            chr((codec_int >> (8 * i)) & 0xFF) for i in range(4)
        ).strip() or "okänt"
        return {
            "ok": True,
            "url": redact_rtsp_url(url),
            "width": int(w),
            "height": int(h),
            "fps": round(eff or float(cap.get(cv2.CAP_PROP_FPS) or 0), 1),
            "codec": codec,
            "latency_ms": round((time.time() - start) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 - returnera begripligt fel
        return {"ok": False, "url": redact_rtsp_url(url), "error": str(exc)}
    finally:
        if cap is not None:
            cap.release()


class CameraWorker:
    """En live-kamera: RTSP-läsning + schemalagd YOLO + annoterad JPEG-cache.

    Trådar:
      - rtsp-tråd: öppnar/läser RTSP, skriver senaste raw-frame.
      - loop-tråd: kör YOLO i AI-FPS-takt och kodar annoterad JPEG i display-FPS.
    All delad state skyddas av en lås. start()/stop()/restart() är skyddade mot
    dubbla anrop (ingen worker-/tråd-dubbling vid reconnect/refresh).
    """

    def __init__(self, analyzer, camera_id: str = "", camera_cfg: dict | None = None):
        self.analyzer = analyzer
        self._lock = threading.RLock()
        self._restart_lock = threading.Lock()  # skyddar mot samtidig restart
        self._stop = threading.Event()
        self._rtsp_thread: threading.Thread | None = None
        self._loop_thread: threading.Thread | None = None

        # --- Konfiguration (default från config/.env, kan överlagras per kamera) ---
        self.camera = self._camera_defaults()
        if camera_cfg:
            merged = dict(self.camera)
            merged.update({k: v for k, v in camera_cfg.items() if k in self.camera})
            self.camera = merged
        name = str(self.camera.get("name") or "Kamera").strip()
        if not name:
            name = "Kamera"
        self.camera["name"] = name
        self.camera_id = (camera_id or _slugify(name) or "kam1").lower()
        self.camera["id"] = self.camera_id
        self.detect = self._detect_defaults()
        self.live = self._live_defaults()
        self.events = self._event_defaults()

        # --- Runtime-state ---
        self.state = CAM_DISABLED
        self.state_detail = "Inte startad"
        self.error: str | None = None
        self.yolo_state = YOLO_STOPPED
        self.yolo_error: str | None = None
        self.resolution: tuple[int, int] | None = None
        self.source_codec: str | None = None
        self.last_frame_ts: float = 0.0
        self.last_detection_ts: float = 0.0
        self.inference_ms: float = 0.0  # EMA
        self._raw_frame = None
        self._raw_ts = 0.0
        self._boxes: list[dict] = []      # senaste YOLO-detektioner
        self._boxes_ts = 0.0
        self._jpeg = None
        self._jpeg_v = 0
        self._jpeg_ts = 0.0
        self._started_ts = time.time()
        self._src_fps = _FpsMeter()
        self._ai_fps = _FpsMeter()
        self._disp_fps = _FpsMeter()
        self._placeholder = None
        self._placeholder_text = ""
        self._running = False
        # Event-tillstånd (HA-publicering av nya detektioner)
        self._event_callback = None
        self._evt = _EventTracker()
        self._ev_classes = self._parse_event_classes(self.events["classes"])
        self._ev_binary_until = 0.0   # binary_sensor i HA hålls ON till denna tid
        self._ev_last_pub = 0.0
        self.last_event: str | None = None
        self.last_event_ts: float | None = None
        self.event_count = 0

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _camera_defaults() -> dict:
        return {
            "enabled": config.CAMERA_ENABLED,
            "name": config.CAMERA_NAME,
            "host": config.CAMERA_HOST,
            "user": config.CAMERA_USER,
            "password": config.CAMERA_PASS,
            "path": config.CAMERA_PATH,
            "full_url": config.CAMERA_RTSP_URL,
            "reconnect": config.CAMERA_RECONNECT,
            "reconnect_delay": config.CAMERA_RECONNECT_DELAY,
            "autostart": config.CAMERA_AUTOSTART,
# Detektionszoner (en eller flera polygoner); gamla linjer (roi_*) stöds fortfarande
    "roi_enabled": False,
    "roi_y": 0.5,
    "roi_side": "above",
    "zone_enabled": False,
    "zone_polys": [],  # list av polygoner (flera zoner)
    "zone_kinds": [],  # per zon: 'watch' (bevaka) | 'mask' (ignorera)
        }

    @staticmethod
    def _detect_defaults() -> dict:
        return {
            "yolo_enabled": True,
            "ai_fps": float(config.YOLO_STREAM_FPS),
            "imgsz": int(config.YOLO_IMG_SIZE),
        }

    @staticmethod
    def _live_defaults() -> dict:
        return {
            "enabled": config.LIVE_STREAM_ENABLED,
            "display_fps": int(config.LIVE_STREAM_FPS),
            "jpeg_quality": int(config.LIVE_JPEG_QUALITY),
            "show_boxes": config.LIVE_SHOW_BOXES,
            "show_labels": config.LIVE_SHOW_LABELS,
            "show_conf": config.LIVE_SHOW_CONF,
        }

    @staticmethod
    def _event_defaults() -> dict:
        return {
            "enabled": config.LIVE_EVENT_ENABLED,
            "classes": config.LIVE_EVENT_CLASSES,
            "clear_after": float(config.LIVE_EVENT_CLEAR_AFTER),
            "hold": float(config.LIVE_EVENT_HOLD),
            "min_interval": float(config.LIVE_EVENT_MIN_INTERVAL),
            "startup_grace": float(config.LIVE_EVENT_STARTUP_GRACE),
        }

    @staticmethod
    def _parse_event_classes(classes: str) -> set:
        return {
            c.strip().lower()
            for c in (classes or "").split(",")
            if c.strip()
        }

    def _cfg(self) -> dict:
        with self._lock:
            return {
                "camera": dict(self.camera),
                "detect": dict(self.detect),
                "live": dict(self.live),
                "events": dict(self.events),
            }

    def _set_state(self, state: str, detail: str = "", error: str | None = None) -> None:
        with self._lock:
            self.state = state
            self.state_detail = detail
            if error is not None:
                self.error = error
            elif state in (CAM_ONLINE, CAM_CONNECTING):
                self.error = None

    # ------------------------------------------------------------- livscykel
    def start(self) -> None:
        with self._restart_lock:
            if self._running and not self._stop.is_set():
                return
            self._stop.clear()
            self._running = True
            self._started_ts = time.time()
            self._rtsp_thread = threading.Thread(
                target=self._rtsp_loop, daemon=True, name="camera-rtsp"
            )
            self._loop_thread = threading.Thread(
                target=self._process_loop, daemon=True, name="camera-yolo"
            )
            self._rtsp_thread.start()
            self._loop_thread.start()

    def stop(self, join: float = 3.0) -> None:
        with self._restart_lock:
            if not self._running:
                return
            self._running = False
            self._stop.set()
            for t in (self._rtsp_thread, self._loop_thread):
                if t and t.is_alive():
                    t.join(timeout=join)
            self._rtsp_thread = None
            self._loop_thread = None
            self._raw_frame = None
            self._raw_ts = 0.0
            with self._lock:
                self.state = CAM_DISABLED
                self.state_detail = "Stoppad"

    def restart(self) -> None:
        """Stoppa och starta om rent (används vid kamera-inställningsändringar)."""
        with self._restart_lock:
            self._running = False
            self._stop.set()
            for t in (self._rtsp_thread, self._loop_thread):
                if t and t.is_alive():
                    t.join(timeout=3.0)
            self._stop.clear()
            self._running = True
            self._started_ts = time.time()
            self._raw_frame = None
            self._raw_ts = 0.0
            self._rtsp_thread = threading.Thread(
                target=self._rtsp_loop, daemon=True, name="camera-rtsp"
            )
            self._loop_thread = threading.Thread(
                target=self._process_loop, daemon=True, name="camera-yolo"
            )
            self._rtsp_thread.start()
            self._loop_thread.start()

    # -------------------------------------------------------------- RTSP-loop
    def _rtsp_loop(self) -> None:
        while not self._stop.is_set():
            cfg = self._cfg()["camera"]
            url = build_rtsp_url(
                cfg["host"], cfg["user"], cfg["password"], cfg["path"], cfg["full_url"]
            )
            if not cfg["enabled"] or not url:
                self._set_state(
                    CAM_DISABLED,
                    "Kamera inaktiverad" if not cfg["enabled"] else "RTSP-adress saknas",
                )
                self._stop.wait(1.0)
                continue

            self._set_state(CAM_CONNECTING, f"Ansluter till {cfg['name']} …")
            cap = None
            try:
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except cv2.error:
                    pass
                if not cap.isOpened():
                    raise RuntimeError("Kunde inte öppna RTSP-strömmen (fel IP/användare/lösenord?).")
                # Vänta på första giltiga bilden (timeout ~10 s)
                first = self._wait_first_frame(cap, timeout=10.0)
                if not first:
                    raise RuntimeError("Ingen bild från kameran (RTSP-timeout).")
                self._src_fps.reset()
                with self._lock:
                    self.resolution = (
                        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0) or None,
                        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0) or None,
                    )
                    codec_int = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
                    self.source_codec = "".join(
                        chr((codec_int >> (8 * i)) & 0xFF) for i in range(4)
                    ).strip() or None
                    self.resolution = (
                        (self.resolution[0] or first.shape[1], self.resolution[1] or first.shape[0])
                        if self.resolution and (self.resolution[0] or self.resolution[1])
                        else (first.shape[1], first.shape[0])
                    )
                print(
                    f"[camera] {cfg['name']} ansluten "
                    f"({redact_rtsp_url(url)})"
                )
                self._set_state(
                    CAM_ONLINE,
                    f"Stream "
                    f"{self.resolution[0]}x{self.resolution[1]}"
                    f"{(' · ' + self.source_codec) if self.source_codec else ''}",
                )
                self._read_loop(cap)
                # Här hamnar vi när strömmen tappats
                if not self._stop.is_set():
                    print(f"[camera] {cfg['name']} tappade anslutningen")
            except Exception as exc:  # noqa: BLE001 - reconnect, krascha aldrig
                self.error = str(exc)
                print(f"[camera] {cfg['name']} fel: {exc}")
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except cv2.error:
                        pass

            if self._stop.is_set():
                return
            # Reconnect med väntetid (ingen busy-loop)
            if cfg["reconnect"]:
                self._set_state(
                    CAM_RECONNECTING,
                    f"Återansluter om {cfg['reconnect_delay']} s …",
                )
                self._stop.wait(float(cfg["reconnect_delay"]))
            else:
                self._set_state(CAM_OFFLINE, "Kameran frånkopplad")
                self._stop.wait(2.0)

    def _wait_first_frame(self, cap, timeout: float) -> bool:
        """Vänta på första giltiga frame. Returnerar True om en mottogs."""
        start = time.time()
        while not self._stop.is_set() and time.time() - start < timeout:
            ret, frame = cap.read()
            if ret and frame is not None:
                with self._lock:
                    self._raw_frame = frame
                    self._raw_ts = time.time()
                    self.last_frame_ts = self._raw_ts
                self._src_fps.tick()
                return True
            time.sleep(0.02)
        return False

    def _read_loop(self, cap) -> None:
        """Läs frames tills strömmen slutar eller workern stoppas."""
        while not self._stop.is_set():
            ret, frame = cap.read()
            if not ret or frame is None:
                return
            now = time.time()
            with self._lock:
                self._raw_frame = frame
                self._raw_ts = now
                self.last_frame_ts = now
                self._src_fps.tick()
            # Liten paus så CPU inte ligger på max även vid hög ingående FPS
            time.sleep(0.001)

    # ------------------------------------------------------------ process-loop
    def _process_loop(self) -> None:
        """Schemalägger YOLO (AI FPS) och JPEG-kodning (display FPS)."""
        last_ai = 0.0
        last_disp = 0.0
        ai_ran_for_ts = 0.0
        disp_ran_for_ts = 0.0
        while not self._stop.is_set():
            now = time.time()
            cfg = self._cfg()
            camera, detect, live = cfg["camera"], cfg["detect"], cfg["live"]
            # Skicka OFF när binary-hålltiden i HA gått ut (oberoende av frames)
            self._maybe_event_off(now)
            with self._lock:
                raw = self._raw_frame
                raw_ts = self._raw_ts

            if raw is None:
                # Ingen bild - visa tydlig placeholder (~1 gång/sekund)
                self._push_placeholder(
                    self._placeholder_reason(camera, cfg), force=(now - self._jpeg_ts > 1.0)
                )
                time.sleep(0.1)
                continue

            # --- YOLO-schemaläggning (analysera senaste bilden, kasta gamla) ---
            ai_interval = 1.0 / max(0.5, float(detect["ai_fps"]))
            if (
                detect["yolo_enabled"]
                and (now - last_ai) >= ai_interval
                and raw_ts != ai_ran_for_ts
            ):
                self.yolo_state = YOLO_RUNNING
                res = self.analyzer.infer_frame(
                    raw,
                    imgsz=detect["imgsz"] or None,
                    draw={
                        "boxes": live["show_boxes"],
                        "labels": live["show_labels"],
                        "conf": live["show_conf"],
                    },
                )
                last_ai = now
                ai_ran_for_ts = raw_ts
                if res["error"]:
                    self.yolo_state = YOLO_ERROR
                    self.yolo_error = res["error"]
                    print(f"[yolo] live-inferensfel: {res['error']}")
                else:
                    self.yolo_error = None
                    dets = res["detections"]
                    # Klassfilter: bara listade klasser ska visas/räknas/skickas.
                    # (Tom lista = alla klasser.) Annars räknas t.ex. falsklarm
                    # som "train" ändå som fordon i HA/räknarna.
                    allowed = self._ev_classes
                    if allowed:
                        dets = [d for d in dets if d.get("class") in allowed]
                    # Filter: linje (ovanför/nedanför) OCH/ELLER zoner – oberoende.
                    # Är båda på måste detektionen klara BÅDA (t.ex. nedanför
                    # linjen OCH inte i en "övervaka INTE"-zon).
                    roi = self._roi_cfg()
                    kept = dets
                    if roi["line"]["enabled"]:
                        kept = self._apply_line(kept, roi["line"], raw.shape[1], raw.shape[0])
                    if roi["zones"]["enabled"]:
                        kept = self._apply_zones(kept, roi["zones"], raw.shape[1], raw.shape[0])
                    with self._lock:
                        self._boxes = kept
                        self._boxes_ts = now
                        if kept:
                            self.last_detection_ts = now
                        # EMA för inferenstid
                        ms = float(res.get("inference_ms") or 0)
                        self.inference_ms = (
                            ms if self.inference_ms <= 0 else self.inference_ms * 0.8 + ms * 0.2
                        )
                    self._ai_fps.tick()
                    # HA-event: nya detektioner (statiska objekt -> bara en händelse)
                    self._eval_events(
                        kept,
                        res.get("annotated"),
                        raw,
                        {
                            "boxes": live["show_boxes"],
                            "labels": live["show_labels"],
                            "conf": live["show_conf"],
                        },
                        roi,
                        now,
                    )

            # --- JPEG-cache: alltid senaste raw + nuvarande boxes ---
            # När strömmen (MJPEG till GUI) är på kodas i display-FPS. Är den av
            # kodas ändå en snapshot ~var 2:e sekund så att /snapshot.jpg,
            # HA-bilden och förhandsvisningen för detektionslinjen fungerar.
            disp_interval = (
                1.0 / max(1.0, float(live["display_fps"])) if live["enabled"] else 2.0
            )
            if (now - last_disp) >= disp_interval and raw_ts != disp_ran_for_ts:
                with self._lock:
                    boxes = list(self._boxes)
                roi = self._roi_cfg()
                annotated = annotate_frame_bgr(
                    raw,
                    boxes,
                    {
                        "boxes": live["show_boxes"],
                        "labels": live["show_labels"],
                        "conf": live["show_conf"],
                    },
                )
                _draw_roi_line(annotated, roi)  # ritar linje och/eller zoner
                ok, buf = cv2.imencode(
                    ".jpg",
                    annotated,
                    [int(cv2.IMWRITE_JPEG_QUALITY), int(live["jpeg_quality"])],
                )
                if ok:
                    data = buf.tobytes()
                    with self._lock:
                        self._jpeg = data
                        self._jpeg_v += 1
                        self._jpeg_ts = now
                    self._disp_fps.tick()
                last_disp = now
                disp_ran_for_ts = raw_ts

            time.sleep(0.02)

    # --------------------------------------------------------- placeholder-JPEG
    def _placeholder_reason(self, camera: dict, cfg: dict) -> str:
        with self._lock:
            state = self.state
            detail = self.state_detail
        if not camera["enabled"]:
            return "Kamera inaktiverad – aktivera i Inställningar"
        if state == CAM_RECONNECTING:
            return detail or "Återansluter …"
        if state == CAM_OFFLINE:
            return "Kameran är frånkopplad"
        if self.error:
            return f"Fel: {self.error}"
        return "Ansluter till kameran …"

    def _push_placeholder(self, text: str, force: bool = True) -> None:
        """Sätt en mörk 'ingen signal'-bild som senaste JPEG (cachad per text)."""
        if not force and text == self._placeholder_text and self._jpeg is not None:
            return
        if text != self._placeholder_text:
            self._placeholder = self._make_placeholder(text)
            self._placeholder_text = text
        if self._placeholder is not None:
            with self._lock:
                self._jpeg = self._placeholder
                self._jpeg_v += 1
                self._jpeg_ts = time.time()

    @staticmethod
    def _make_placeholder(text: str):
        import numpy as np

        img = np.full((270, 480, 3), (16, 18, 24), dtype=np.uint8)  # mörk bakgrund
        cv2.putText(
            img, "Camera AI", (150, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (88, 166, 255), 2, cv2.LINE_AA
        )
        lines = (text or "").split("\n")
        y = 160
        for ln in lines[:3]:
            cv2.putText(
                img, ln, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA
            )
            y += 28
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return buf.tobytes() if ok else None

    # ------------------------------------------------------------- API/metoder
    def update_camera(self, values: dict) -> None:
        """Uppdatera kamera-inställningar i minnet (utan omstart)."""
        with self._lock:
            for k, v in values.items():
                if k in self.camera and k != "password_configured":
                    self.camera[k] = v

    def _roi_cfg(self) -> dict:
        """Nuvarande detektionsfiltrering – linje OCH/ELLER zoner (oberoende).

        Läses varje inferens – ingen omstart. Linjefilter
        (roi_enabled/roi_y/roi_side) = "bevaka bara ovanför/nedanför linjen".
        Zonfilter (zone_enabled + zone_polys/zone_mode) = union: INUTI = i
        någon zon, UTANFÖR = inte i någon ("övervaka INTE dessa"). Båda kan
        vara på samtidigt – en detektion måste då klara BÅDA.
        """
        with self._lock:
            c = self.camera
            ry = min(1.0, max(0.0, float(c.get("roi_y", 0.5))))
            line = {
                "enabled": bool(c.get("roi_enabled")),
                "roi_y": ry,
                "roi_side": str(c.get("roi_side", "above")),
            }
            items = self._zone_items_from_cfg(c)
            zones = {
                "enabled": bool(c.get("zone_enabled")) and len(items) >= 1,
                "items": [{"points": p, "kind": k} for p, k in items],
            }
        return {"line": line, "zones": zones}

    @staticmethod
    def _norm_poly(raw) -> list:
        """Rensa en polygon till [[x, y], ...] (float, 0–1)."""
        pts: list = []
        if isinstance(raw, list):
            for p in raw:
                try:
                    x = min(1.0, max(0.0, float(p[0])))
                    y = min(1.0, max(0.0, float(p[1])))
                except (TypeError, ValueError, IndexError):
                    continue
                pts.append([x, y])
        return pts

    def _zone_items_from_cfg(self, c: dict) -> list:
        """[(punkter, typ)] för alla zoner (normaliserade).

        Typ per zon: 'watch' (bevaka) eller 'mask' (övervaka INTE). Äldre
        configs utan zone_kinds migreras från zone_mode: outside → mask,
        annars watch.
        """
        raw = c.get("zone_polys")
        polys: list = []
        if isinstance(raw, list):
            for poly in raw:
                pts = self._norm_poly(poly)
                if len(pts) >= 3:
                    polys.append(pts)
        if not polys:
            pts = self._norm_poly(c.get("zone_points"))
            if len(pts) >= 3:
                polys.append(pts)
        legacy_mask = str(c.get("zone_mode", "inside")) == "outside"
        kinds_raw = c.get("zone_kinds")
        items = []
        for i, poly in enumerate(polys):
            if (
                isinstance(kinds_raw, list)
                and i < len(kinds_raw)
                and kinds_raw[i] in ("watch", "mask")
            ):
                kind = kinds_raw[i]
            else:
                kind = "mask" if legacy_mask else "watch"
            items.append((poly, kind))
        return items

    @staticmethod
    def _point_in_poly(px: float, py: float, poly: list) -> bool:
        """Ray-casting point-in-polygon på normaliserade koordinater."""
        inside = False
        n = len(poly)
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > py) != (yj > py)) and (
                px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-9) + xi
            ):
                inside = not inside
            j = i
        return inside

    def _keep_in_polys(self, dets: list, polys: list, inside_mode: bool, width: int, height: int) -> list:
        """Behåll detektioner vars box-mittpunkt är i någon polygon (inside_mode)
        respektive inte i någon. Polygoner normaliserade 0–1, boxar i pixlar."""
        if not polys or not dets or width <= 0 or height <= 0:
            return dets
        out = []
        for d in dets:
            box = d.get("box")
            if not box or len(box) < 4:
                out.append(d)
                continue
            cx = ((float(box[0]) + float(box[2])) / 2.0) / float(width)
            cy = ((float(box[1]) + float(box[3])) / 2.0) / float(height)
            in_any = any(self._point_in_poly(cx, cy, poly) for poly in polys)
            if in_any == inside_mode:
                out.append(d)
        return out

    def _apply_line(self, dets: list, line: dict, width: int, height: int) -> list:
        """Behåll bara detektioner ovanför/nedanför linjen (ovanför/nedanför)."""
        ry = float(line.get("roi_y", 0.5))
        if str(line.get("roi_side", "above")) == "above":
            poly = [[0.0, 0.0], [1.0, 0.0], [1.0, ry], [0.0, ry]]
        else:
            poly = [[0.0, ry], [1.0, ry], [1.0, 1.0], [0.0, 1.0]]
        return self._keep_in_polys(dets, [poly], True, width, height)

    def _apply_zones(self, dets: list, zones: dict, width: int, height: int) -> list:
        """Behåll enligt zonerna. 'mask' = i en sådan → släng (övervaka INTE).
        'watch' = om någon bevaka-zon finns måste detektionen ligga i en av dem.
        Kombineras (AND) med linjefiltret i processloopen."""
        if not zones.get("enabled") or not dets or width <= 0 or height <= 0:
            return dets
        items = zones.get("items") or []
        watch = [it["points"] for it in items if it["kind"] == "watch"]
        mask = [it["points"] for it in items if it["kind"] == "mask"]
        out = []
        for d in dets:
            box = d.get("box")
            if not box or len(box) < 4:
                out.append(d)
                continue
            cx = ((float(box[0]) + float(box[2])) / 2.0) / float(width)
            cy = ((float(box[1]) + float(box[3])) / 2.0) / float(height)
            if any(self._point_in_poly(cx, cy, p) for p in mask):
                continue  # i en "övervaka INTE"-zon
            if watch and not any(self._point_in_poly(cx, cy, p) for p in watch):
                continue  # bevaka-zoner finns men den är inte i någon
            out.append(d)
        return out

    def update_detect(self, values: dict) -> None:
        with self._lock:
            for k, v in values.items():
                if k in self.detect:
                    self.detect[k] = v
            if not self.detect.get("yolo_enabled", True):
                # YOLO av -> visa rå ström utan gamla/utdaterade boxar
                self._boxes = []
                self._boxes_ts = 0.0
                self.yolo_state = YOLO_STOPPED
                self.yolo_error = None

    def update_live(self, values: dict) -> None:
        with self._lock:
            for k, v in values.items():
                if k in self.live:
                    self.live[k] = v

    # --------------------------------------------------------- HA-event (live)
    def on_event(self, fn) -> None:
        """Registrera callback som anropas vid nya händelser (kind=event/clear)."""
        with self._lock:
            self._event_callback = fn

    def update_events(self, values: dict) -> None:
        with self._lock:
            for k, v in values.items():
                if k in self.events:
                    self.events[k] = v
            self._ev_classes = self._parse_event_classes(self.events["classes"])
            enabled = bool(self.events.get("enabled"))
            was_on = self._ev_binary_until > 0.0
            cb = self._event_callback
            if not enabled:
                self._ev_binary_until = 0.0
                self._evt.reset()
                self._ev_last_pub = 0.0
        if not enabled and was_on and cb is not None:
            try:
                cb({
                    "kind": "clear", "classes": [], "detections": [],
                    "summary": "", "jpeg": None,
                    "ts": time.time(), "camera_name": self.camera["name"],
                })
            except Exception as exc:  # noqa: BLE001
                print(f"[event] clear misslyckades: {exc}")

    def _maybe_event_off(self, now: float) -> None:
        """Skicka OFF till HA när binary-hålltiden gått ut (körs varje loopvarv)."""
        with self._lock:
            until = self._ev_binary_until
            cb = self._event_callback
            if until and now >= until:
                self._ev_binary_until = 0.0
        if until and now >= until and cb is not None:
            try:
                cb({
                    "kind": "clear", "classes": [], "detections": [],
                    "summary": "", "jpeg": None,
                    "ts": now, "camera_name": self.camera["name"],
                })
            except Exception as exc:  # noqa: BLE001
                print(f"[event] clear misslyckades: {exc}")

    def _eval_events(self, dets: list, annotated_bgr, raw_bgr, draw, roi, now: float) -> None:
        """Kör event-trackern på senaste inferensen och publicerar nya händelser."""
        with self._lock:
            enabled = bool(self.events.get("enabled"))
            cfg = dict(self.events)
            cb = self._event_callback
            camera_name = self.camera["name"]
            classes = set(self._ev_classes)
        if not enabled or cb is None:
            return
        with self._lock:
            present = {d.get("class") for d in dets if d.get("class") in classes}
            fired = self._evt.update(present, now, float(cfg.get("clear_after", 5.0)))
            grace_until = self._started_ts + float(cfg.get("startup_grace", 0.0))
            if fired and now >= grace_until:
                min_int = float(cfg.get("min_interval", 5.0))
                hold = float(cfg.get("hold", 10.0))
                can_pub = (now - self._ev_last_pub) >= min_int
                if can_pub:
                    self._ev_last_pub = now
                # Förläng alltid ON så binary_sensorn inte slår av mitt i aktivitet
                self._ev_binary_until = max(self._ev_binary_until, now + hold)
            else:
                can_pub = False
        if not fired:
            return
        if now < grace_until:
            return  # låt redan närvarande objekt "landa" innan man larmar
        if not can_pub:
            return
        ev_dets = [d for d in dets if d.get("class") in fired]
        summary = self._event_summary(ev_dets)
        jpeg = None
        with self._lock:
            q = int(self.live.get("jpeg_quality", 80))
        # Med detektionsfilter ritas bara godkända boxar (annars skulle
        # bortfiltrerade objekt synas på händelsebilden).
        img = None
        has_roi = bool(roi.get("line", {}).get("enabled") or roi.get("zones", {}).get("enabled"))
        if has_roi and raw_bgr is not None:
            img = annotate_frame_bgr(raw_bgr, ev_dets, draw)
            _draw_roi_line(img, roi)
        elif annotated_bgr is not None:
            img = annotated_bgr
        if img is not None:
            ok, buf = cv2.imencode(
                ".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), q]
            )
            if ok:
                jpeg = buf.tobytes()
        with self._lock:
            self.last_event = summary
            self.last_event_ts = now
            self.event_count += 1
        try:
            cb({
                "kind": "event",
                "classes": list(fired),
                "detections": ev_dets,
                "summary": summary,
                "jpeg": jpeg,
                "ts": now,
                "camera_name": camera_name,
            })
        except Exception as exc:  # noqa: BLE001 - workern får aldrig krascha
            print(f"[event] publicering misslyckades: {exc}")

    @staticmethod
    def _event_summary(ev_dets: list) -> str:
        if not ev_dets:
            return ""
        return ", ".join(
            f"{d.get('class', '?')} {float(d.get('confidence', 0.0)) * 100:.0f}%"
            for d in ev_dets[:4]
        )

    @property
    def running(self) -> bool:
        return self._running and not self._stop.is_set()

    def record(self) -> dict:
        """Hela kameraknfigurationen (inkl. lösenord - sparas bara lokalt)."""
        with self._lock:
            return dict(self.camera)

    def public_cfg(self) -> dict:
        """Kamera-konfiguration utan hemligheter (för GUI/API)."""
        with self._lock:
            c = dict(self.camera)
        full = c.get("full_url") or ""
        return {
            "id": self.camera_id,
            "enabled": bool(c.get("enabled")),
            "name": c.get("name") or "",
            "host": c.get("host") or "",
            "user": c.get("user") or "",
            "path": c.get("path") or "/Preview_01_sub",
            "password_configured": bool((c.get("password") or "") or ("@" in full)),
            "full_url_configured": bool(full),
            "reconnect": bool(c.get("reconnect")),
            "reconnect_delay": int(c.get("reconnect_delay", 5)),
            "autostart": bool(c.get("autostart")),
            # Detektionszon
            "roi_enabled": bool(c.get("roi_enabled")),
            "roi_y": float(c.get("roi_y", 0.5)),
            "roi_side": str(c.get("roi_side", "above")),
            "zone_enabled": bool(c.get("zone_enabled")),
            "zone_points": c.get("zone_points") or [],
            "zone_polys": [p for p, _k in self._zone_items_from_cfg(c)],
            "zone_kinds": [k for _p, k in self._zone_items_from_cfg(c)],
            "zone_mode": str(c.get("zone_mode", "inside")),
        }

    def latest_jpeg(self):
        """Returnera (jpeg-bytes, versionsnummer) för senaste annoterade bilden."""
        with self._lock:
            return self._jpeg, self._jpeg_v

    def raw_jpeg(self, quality: int = 80) -> bytes | None:
        """Senaste råa frame:n som JPEG (utan boxar/linje) – för förhandsvisning."""
        with self._lock:
            raw = self._raw_frame
        if raw is None:
            return None
        ok, buf = cv2.imencode(
            ".jpg", raw, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
        )
        return buf.tobytes() if ok else None

    def detections_now(self) -> tuple[list, float]:
        with self._lock:
            return list(self._boxes), self._boxes_ts

    def status(self) -> dict:
        """Samlad runtime-status för Dashboard/API (inga hemligheter)."""
        with self._lock:
            camera = dict(self.camera)
            detect = dict(self.detect)
            live = dict(self.live)
            events = dict(self.events)
            state = self.state
            detail = self.state_detail
            error = self.error
            yolo_state = self.yolo_state
            yolo_error = self.yolo_error
            resolution = self.resolution
            last_frame = self.last_frame_ts
            last_det = self.last_detection_ts
            inference = self.inference_ms
            boxes = list(self._boxes)
        cfg = self.analyzer
        configured_device = getattr(cfg, "device", None)
        actual_device = getattr(cfg, "last_device", None) or configured_device
        model = getattr(cfg, "model_name", None)
        conf = getattr(cfg, "conf", None)
        # Antal per klass (för 'Detected now')
        counts: dict[str, int] = {}
        for d in boxes:
            c = d.get("class", "?")
            counts[c] = counts.get(c, 0) + 1
        top = sorted(
            ({"class": d.get("class"), "confidence": d.get("confidence", 0.0)} for d in boxes),
            key=lambda d: d["confidence"],
            reverse=True,
        )[:12]
        # Fallback = GPU begärdes men CPU används. Jämför kapacitetsnivå, inte
        # text: konfigurerat "openvino:GPU" körs som "intel:gpu" (samma nivå).
        def _tier(dev: str | None) -> str:
            return "gpu" if dev and "gpu" in str(dev).lower() else "cpu"

        fallback = _tier(configured_device) == "gpu" and _tier(actual_device) == "cpu"
        return {
            "camera_id": self.camera_id,
            "camera_name": camera["name"],
            "camera_enabled": bool(camera["enabled"]),
            "camera_state": state,
            "camera_detail": detail,
            "camera_error": error,
            "stream_active": state == CAM_ONLINE,
            "yolo_state": yolo_state,
            "yolo_error": yolo_error,
            "resolution": f"{resolution[0]}x{resolution[1]}" if resolution else None,
            "codec": self.source_codec,
            "model": model,
            "confidence": conf,
            "configured_device": configured_device,
            "actual_device": actual_device,
            "gpu_fallback": fallback,
            "inference_ms": round(inference, 1),
            "source_fps": self._src_fps.fps(),
            "ai_fps": self._ai_fps.fps(),
            "target_ai_fps": float(detect["ai_fps"]),
            "display_fps": self._disp_fps.fps(),
            "target_display_fps": int(live["display_fps"]),
            "jpeg_quality": int(live["jpeg_quality"]),
            "imgsz": int(detect["imgsz"]),
            "live_enabled": bool(live["enabled"]),
            "detections": top,
            "detection_counts": counts,
            "last_frame_ts": last_frame or None,
            "last_detection_ts": last_det or None,
            "last_frame_age": round(time.time() - last_frame, 1) if last_frame else None,
            "uptime": round(time.time() - self._started_ts),
            "show_boxes": bool(live["show_boxes"]),
            "show_labels": bool(live["show_labels"]),
            "show_conf": bool(live["show_conf"]),
            # HA-event-status
            "events_enabled": bool(events["enabled"]),
            "event_classes": (events["classes"] or ""),
            "event_clear_after": float(events["clear_after"]),
            "event_hold": float(events["hold"]),
            "event_min_interval": float(events["min_interval"]),
            "event_startup_grace": float(events["startup_grace"]),
            "last_event": self.last_event,
            "last_event_ts": self.last_event_ts,
            "event_count": self.event_count,
        }


# ---------------------------------------------------------------------------
# CameraPool: hanterar flera kameraworkers + lokalt register (data/cameras.json)
# ---------------------------------------------------------------------------
# Registret sparas i config.CAMERAS_FILE (data/cameras.json), som bevaras av
# install/update (data/ exkluderas i robocopy). Fält = worker.camera.
_CAMERA_FIELDS = (
    "enabled", "name", "host", "user", "password", "path", "full_url",
    "reconnect", "reconnect_delay", "autostart",
    "roi_enabled", "roi_y", "roi_side",
    "zone_enabled", "zone_polys", "zone_kinds", "zone_points", "zone_mode",
)


class CameraPool:
    """Register + livscykel för N kameror (en CameraWorker per kamera)."""

    def __init__(self, analyzer):
        self.analyzer = analyzer
        self._lock = threading.RLock()
        self._workers: dict[str, CameraWorker] = {}
        self._order: list[str] = []
        self._event_cb = None

    # ------------------------------------------------------------- register
    def load(self) -> None:
        """Ladda register från data/cameras.json (eller seeda från CAMERA_*)."""
        records: list[dict] = []
        if config.CAMERAS_FILE.exists():
            try:
                data = json.loads(config.CAMERAS_FILE.read_text(encoding="utf-8"))
                records = data if isinstance(data, list) else []
            except Exception as exc:  # noqa: BLE001 - fall tillbaka på seed
                print(f"[camera] kunde inte läsa register ({exc}) - startar om från .env")
                records = []
        if not records:
            seed = self._seed_from_env()
            if seed:
                records = [seed]
        for rec in records:
            self._add_record(rec, start=False)
        self._save()

    def _seed_from_env(self) -> dict | None:
        """Migration: om inget register finns används befintlig CAMERA_*/REOLINK_*."""
        if not config.CAMERA_ENABLED and not config.CAMERA_HOST:
            return None
        return {
            "enabled": config.CAMERA_ENABLED,
            "name": config.CAMERA_NAME,
            "host": config.CAMERA_HOST,
            "user": config.CAMERA_USER,
            "password": config.CAMERA_PASS,
            "path": config.CAMERA_PATH,
            "full_url": config.CAMERA_RTSP_URL,
            "reconnect": config.CAMERA_RECONNECT,
            "reconnect_delay": config.CAMERA_RECONNECT_DELAY,
            "autostart": config.CAMERA_AUTOSTART,
            # Detektionszoner
            "roi_enabled": False,
            "roi_y": 0.5,
            "roi_side": "above",
            "zone_enabled": False,
            "zone_polys": [],
            "zone_mode": "inside",
        }

    def _save(self) -> None:
        try:
            records = [self._workers[c].record() for c in self._order if c in self._workers]
            config.CAMERAS_FILE.write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:  # noqa: BLE001
            print(f"[camera] kunde inte spara register: {exc}")

    def _add_record(self, rec: dict, start: bool) -> CameraWorker:
        base = str(rec.get("id") or _slugify(rec.get("name", "kamera"))).lower()
        cid, n = base, 2
        while cid in self._workers:
            cid = f"{base}-{n}"
            n += 1
        w = CameraWorker(self.analyzer, camera_id=cid, camera_cfg=rec)
        with self._lock:
            self._workers[cid] = w
            self._order.append(cid)
        if self._event_cb is not None:
            w.on_event(self._event_cb)
        if start and bool(w.camera.get("enabled")):
            w.start()
        return w

    # -------------------------------------------------------------- lookup
    def get(self, key: str) -> CameraWorker | None:
        """Hämta worker via id eller (skifteslöst) namn."""
        key = (key or "").strip().lower()
        with self._lock:
            if key in self._workers:
                return self._workers[key]
            for w in self._workers.values():
                if str(w.camera.get("name", "")).lower() == key:
                    return w
        return None

    def require(self, key: str) -> CameraWorker:
        w = self.get(key)
        if w is None:
            raise KeyError(key)
        return w

    def default(self) -> CameraWorker | None:
        with self._lock:
            for cid in self._order:
                if cid in self._workers:
                    return self._workers[cid]
        return None

    def ids(self) -> list:
        with self._lock:
            return list(self._order)

    def all(self) -> list:
        with self._lock:
            return [self._workers[c] for c in self._order if c in self._workers]

    def count(self) -> int:
        with self._lock:
            return len(self._order)

    # -------------------------------------------------------------- CRUD
    def add(self, cfg: dict) -> CameraWorker:
        """Lägg till en kamera (startas direkt om enabled)."""
        rec = {k: cfg.get(k) for k in _CAMERA_FIELDS if cfg.get(k) is not None}
        rec.setdefault("name", "Kamera")
        rec.setdefault("enabled", False)
        rec.setdefault("reconnect", True)
        rec.setdefault("reconnect_delay", int(config.CAMERA_RECONNECT_DELAY))
        rec.setdefault("autostart", True)
        rec.setdefault("path", "/Preview_01_sub")
        w = self._add_record(rec, start=True)
        self._save()
        return w

    def update(self, cid: str, patch: dict) -> CameraWorker | None:
        """Uppdatera en kamera; startar/stoppar/startar om vid behov."""
        w = self.get(cid)
        if w is None:
            return None
        values = {k: v for k, v in patch.items() if k in _CAMERA_FIELDS and k != "id"}
        if values.get("name") is not None:
            values["name"] = str(values["name"]).strip()
        if values.get("password") in (None, ""):
            values.pop("password", None)  # tomt = behåll befintligt
        if values.get("host") is not None:
            values["host"] = str(values["host"]).strip()
        if values.get("path") is not None:
            p = str(values["path"]).strip() or "/Preview_01_sub"
            values["path"] = p if p.startswith("/") else "/" + p
        if values.get("full_url") is not None:
            values["full_url"] = str(values["full_url"]).strip()

        was_running = w.running
        enabled = values.get("enabled", w.camera.get("enabled", False))
        # Starta bara om RTSP-anslutningen om något som faktiskt påverkar den
        # ändrats – annars tappar man strömmen i onödan vid varje "Spara".
        restart_keys = ("host", "user", "password", "path", "full_url")
        needs_restart = False
        for k in restart_keys:
            if k in values:
                new_v = values[k]
                old_v = w.camera.get(k)
                if k == "password":
                    if new_v and str(new_v) != str(old_v or ""):
                        needs_restart = True
                elif str(new_v) != str(old_v or ""):
                    needs_restart = True
        w.update_camera(values)

        if not enabled:
            w.stop()
        else:
            if not w.running:
                w.start()
            elif needs_restart:
                w.restart()
        self._save()
        return w

    def remove(self, cid: str) -> bool:
        w = self.get(cid)
        if w is None:
            return False
        w.stop()
        with self._lock:
            self._workers.pop(cid, None)
            if cid in self._order:
                self._order.remove(cid)
        self._save()
        return True

    # --------------------------------------------------------- lifecycle
    def start(self, cid: str) -> CameraWorker | None:
        w = self.get(cid)
        if w is not None:
            w.start()
        return w

    def stop(self, cid: str) -> CameraWorker | None:
        w = self.get(cid)
        if w is not None:
            w.stop()
        return w

    def set_stream(self, cid: str, on: bool) -> CameraWorker | None:
        """Sätt live-ström (MJPEG till GUI) på/av för en kamera.

        Worker + YOLO + HA-event fortsätter oavsett - det här styr bara om
        videon kodas/skickas till GUI/API.
        """
        w = self.get(cid)
        if w is not None:
            w.update_live({"enabled": bool(on)})
        return w

    def start_all(self) -> None:
        """Starta aktiverade kameror (kontinuerligt, oavsett webbläsare)."""
        for w in self.all():
            if bool(w.camera.get("enabled")):
                w.start()

    def stop_all(self, join: float = 3.0) -> None:
        for w in self.all():
            w.stop(join=join)

    # ----------------------------------------------------------- settings
    def on_event(self, fn) -> None:
        self._event_cb = fn
        for w in self.all():
            w.on_event(fn)

    def apply_all(self, kind: str, values: dict) -> None:
        """Applicera globala inställningar (detect/live/events) på alla kameror."""
        method = getattr(CameraWorker, f"update_{kind}", None)
        if method is None:
            return
        for w in self.all():
            method(w, values)

    def statuses(self) -> list:
        return [w.status() for w in self.all()]

    def camera_list(self) -> list:
        return [w.public_cfg() for w in self.all()]

