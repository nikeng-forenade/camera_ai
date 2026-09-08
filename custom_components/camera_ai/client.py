"""Async HTTP client for the Camera AI server REST API."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx


def server_payload(settings: dict) -> dict:
    """Map integration option keys to the server's /api/config field names.

    The HA integration uses ``confidence`` for the threshold while the server
    expects ``conf``; everything else matches 1:1.
    """
    mapping = {
        "model": "model",
        "confidence": "conf",
        "device": "device",
        "use_llm": "use_llm",
        "llm_model": "llm_model",
        "prompt": "prompt",
        "keep_alive": "keep_alive",
    }
    payload = {}
    for integration_key, server_key in mapping.items():
        if integration_key in settings and settings[integration_key] is not None:
            value = settings[integration_key]
            payload[server_key] = float(value) if server_key == "conf" else value
    return payload


class CameraAIClient:
    """Thin async client for the Camera AI server."""

    def __init__(self, url: str, session: httpx.AsyncClient, username: str = "", password: str = "") -> None:
        self.url = url.rstrip("/")
        self._session = session
        self._auth = httpx.BasicAuth(username, password) if username else None

    async def _request(self, method: str, path: str, **kwargs):
        kwargs.setdefault("auth", self._auth)
        return await self._session.request(method, f"{self.url}{path}", **kwargs)

    async def health(self) -> dict:
        resp = await self._request("GET", "/api/health", timeout=10)
        resp.raise_for_status()
        return resp.json()

    async def get_config(self) -> dict:
        """Current server runtime settings (model, conf, device, LLM, keep_alive)."""
        resp = await self._request("GET", "/api/config", timeout=10)
        resp.raise_for_status()
        return resp.json()

    async def cameras_status(self) -> dict:
        """Löpande status för serverns kameror (live: state, detections, fps)."""
        resp = await self._request("GET", "/api/cameras/status", timeout=10)
        resp.raise_for_status()
        return resp.json()

    async def events(self, limit: int = 50) -> list[dict]:
        """Senaste detektionseventen för historik och diagnostik."""
        resp = await self._request("GET", "/api/events", params={"limit": limit}, timeout=10)
        resp.raise_for_status()
        return resp.json()

    async def analyze_file(
        self,
        image_path: Path,
        model: str,
        conf: float,
        use_llm: bool = False,
        prompt: str | None = None,
    ) -> dict:
        payload = await asyncio.to_thread(image_path.read_bytes)
        files = {"file": (image_path.name, payload, "image/jpeg")}
        data = {
            "model": model,
            "conf": str(conf),
            "use_llm": str(use_llm).lower(),
            "use_ha": "false",
        }
        if prompt:
            data["prompt"] = prompt
        resp = await self._request("POST", "/api/analyze", data=data, files=files, timeout=120)
        resp.raise_for_status()
        return resp.json()

    async def analyze_url(
        self,
        url: str,
        model: str,
        conf: float,
        use_llm: bool = False,
        prompt: str | None = None,
    ) -> dict:
        data = {
            "url": url,
            "model": model,
            "conf": str(conf),
            "use_llm": str(use_llm).lower(),
            "use_ha": "false",
        }
        if prompt:
            data["prompt"] = prompt
        resp = await self._request("POST", "/api/analyze-url", data=data, timeout=120)
        resp.raise_for_status()
        return resp.json()

    async def fetch_image(self, path: str) -> bytes:
        resp = await self._request("GET", path, timeout=30)
        resp.raise_for_status()
        return resp.content

    async def set_config(self, config: dict) -> dict:
        """Push runtime settings (model, conf, device, LLM model/prompt) to the server."""
        resp = await self._request("POST", "/api/config", json=config, timeout=15)
        resp.raise_for_status()
        return resp.json()
