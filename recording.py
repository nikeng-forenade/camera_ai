"""Segmented camera recording with ffmpeg stream copy."""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
import logging
from pathlib import Path

import config


LOGGER = logging.getLogger("camera_ai.recording")


class RecordingManager:
    """Runs one ffmpeg process per camera and prunes expired segments."""

    def __init__(self, camera_id: str, config_getter, rtsp_url_getter, motion_getter) -> None:
        self.camera_id = camera_id
        self._config_getter = config_getter
        self._rtsp_url_getter = rtsp_url_getter
        self._motion_getter = motion_getter
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._error = ""
        self._saved_segments = 0
        self._started_at = 0.0

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name="camera-recording")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            process = self._process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=4)

    def restart(self) -> None:
        self.stop()
        self.start()

    def status(self) -> dict:
        cfg = self._config_getter()
        with self._lock:
            active = bool(self._process and self._process.poll() is None)
            return {
                "recording_mode": cfg.get("recording_mode", "off"),
                "recording_active": active,
                "recording_folder": str(self._folder(cfg)),
                "recording_retention_days": int(cfg.get("recording_retention_days", 7)),
                "recording_error": self._error or None,
                "recording_segments": self._saved_segments,
                "recording_started_at": self._started_at or None,
            }

    def _folder(self, cfg: dict) -> Path:
        raw = str(cfg.get("recording_folder") or "").strip()
        return Path(raw).expanduser() if raw else Path("recordings")

    def _run(self) -> None:
        ffmpeg = config.FFMPEG_BIN
        if not Path(ffmpeg).is_file() and not shutil.which(ffmpeg):
            LOGGER.error("%s: ffmpeg saknas i PATH - inspelning kan inte starta.", self.camera_id)
            with self._lock:
                self._error = "ffmpeg saknas i PATH - installera ffmpeg för inspelning."
            return
        while not self._stop.is_set():
            cfg = self._config_getter()
            mode = cfg.get("recording_mode", "off")
            if mode == "off":
                return
            folder = self._folder(cfg) / self.camera_id / time.strftime("%Y-%m-%d")
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                LOGGER.error("%s: kunde inte skapa inspelningsmapp: %s", self.camera_id, exc)
                with self._lock:
                    self._error = f"Kunde inte skapa inspelningsmapp: {exc}"
                return
            url = self._rtsp_url_getter()
            if not url:
                LOGGER.error("%s: RTSP-adress saknas för inspelning.", self.camera_id)
                with self._lock:
                    self._error = "RTSP-adress saknas för inspelning."
                return
            pattern = str(folder / "%H-%M-%S.mp4")
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "warning", "-rtsp_transport", "tcp",
                "-i", url, "-map", "0:v:0", "-an", "-c", "copy", "-f", "segment",
                "-segment_time", str(int(cfg.get("recording_segment_seconds", 10))),
                "-reset_timestamps", "1", "-strftime", "1", pattern,
            ]
            try:
                LOGGER.info("%s: startar inspelning (%s) till %s", self.camera_id, mode, folder)
                with self._lock:
                    self._error = ""
                    self._started_at = time.time()
                    self._process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                self._wait_for_process(mode, folder, int(cfg.get("recording_retention_days", 7)))
            except OSError as exc:
                LOGGER.error("%s: kunde inte starta ffmpeg: %s", self.camera_id, exc)
                with self._lock:
                    self._error = f"Kunde inte starta ffmpeg: {exc}"
                return
            finally:
                with self._lock:
                    self._process = None
            if not self._stop.wait(3):
                continue

    def _wait_for_process(self, mode: str, folder: Path, retention_days: int) -> None:
        while not self._stop.wait(5):
            process = self._process
            if process is None or process.poll() is not None:
                LOGGER.warning("%s: ffmpeg avslutades - försöker återansluta.", self.camera_id)
                with self._lock:
                    self._error = "ffmpeg avslutades - försöker återansluta."
                return
            self._apply_mode(folder, mode)
            self._prune(retention_days)

    def _apply_mode(self, folder: Path, mode: str) -> None:
        segments = list(folder.glob("*.mp4"))
        if mode == "motion" and not self._motion_getter():
            # Keep the currently written segment; discard completed idle segments.
            for segment in segments[:-1]:
                try:
                    segment.unlink()
                except OSError:
                    pass
        with self._lock:
            self._saved_segments = len(list(folder.glob("*.mp4")))

    def _prune(self, retention_days: int) -> None:
        cutoff = time.time() - max(1, retention_days) * 86400
        root = self._folder(self._config_getter()) / self.camera_id
        try:
            for segment in root.rglob("*.mp4"):
                if segment.stat().st_mtime < cutoff:
                    segment.unlink()
        except OSError:
            pass