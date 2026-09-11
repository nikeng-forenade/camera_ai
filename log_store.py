"""Small thread-safe in-memory log buffer for the web diagnostics view."""
from __future__ import annotations

import logging
from collections import deque
from threading import Lock


class _MemoryHandler(logging.Handler):
    def __init__(self, entries: deque, lock: Lock) -> None:
        super().__init__()
        self.entries = entries
        self.entries_lock = lock

    def emit(self, record: logging.LogRecord) -> None:
        try:
            item = {
                "time": self.formatter.formatTime(record, "%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "source": record.name,
                "message": record.getMessage(),
            }
            with self.entries_lock:
                self.entries.append(item)
        except Exception:
            pass


_ENTRIES: deque = deque(maxlen=500)
_LOCK = Lock()


def install() -> None:
    """Attach one buffer handler to the root logger without duplicating it."""
    root = logging.getLogger()
    if any(isinstance(handler, _MemoryHandler) for handler in root.handlers):
        return
    handler = _MemoryHandler(_ENTRIES, _LOCK)
    handler.setFormatter(logging.Formatter())
    root.addHandler(handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)


def entries(limit: int = 200) -> list[dict]:
    with _LOCK:
        return list(_ENTRIES)[-max(1, min(limit, 500)):][::-1]