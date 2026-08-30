"""Async HTTP client for the Camera AI server REST API."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx


class CameraAIClient:
    """Thin async client for the Camera AI server."""

    def __init__(self, url: str, session: httpx.AsyncClient) -> None:
        self.url = url.rstrip("/")
        self._session = session

    async def health(self) -> dict:
        resp = await self._session.get(f"{self.url}/api/health", timeout=10)
        resp.raise_for_status()
        return resp.json()

    async def analyze_file(
        self,
        image_path: Path,
        model: str,
        conf: float,
        use_llm: bool = False,
    ) -> dict:
        payload = await asyncio.to_thread(image_path.read_bytes)
        files = {"file": (image_path.name, payload, "image/jpeg")}
        data = {
            "model": model,
            "conf": str(conf),
            "use_llm": str(use_llm).lower(),
            "use_ha": "false",
        }
        resp = await self._session.post(
            f"{self.url}/api/analyze", data=data, files=files, timeout=120
        )
        resp.raise_for_status()
        return resp.json()

    async def analyze_url(
        self,
        url: str,
        model: str,
        conf: float,
        use_llm: bool = False,
    ) -> dict:
        data = {
            "url": url,
            "model": model,
            "conf": str(conf),
            "use_llm": str(use_llm).lower(),
            "use_ha": "false",
        }
        resp = await self._session.post(
            f"{self.url}/api/analyze-url", data=data, timeout=120
        )
        resp.raise_for_status()
        return resp.json()

    async def fetch_image(self, path: str) -> bytes:
        resp = await self._session.get(f"{self.url}{path}", timeout=30)
        resp.raise_for_status()
        return resp.content

    async def set_config(self, config: dict) -> dict:
        """Push runtime settings (model, conf, device, LLM model/prompt) to the server."""
        resp = await self._session.post(f"{self.url}/api/config", json=config, timeout=15)
        resp.raise_for_status()
        return resp.json()
