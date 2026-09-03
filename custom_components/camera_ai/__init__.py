"""Camera AI integration — connects Home Assistant to the Camera AI server.

Provides sensors (status / runtime config / last detection / Swedish scene
description), a motion binary sensor, a camera showing the annotated snapshot,
and services to analyze a camera snapshot or an image URL (with selectable YOLO
model / prompt) and to change all runtime settings on the server (model,
confidence, device, LLM prompt, keep-alive). The analyze services return the
result so automations can use it via response_variable.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import CameraAIClient, server_payload
from .const import (
    CONF_CAMERA,
    CONF_CONFIDENCE,
    CONF_MODEL,
    CONF_PROMPT,
    CONF_USE_LLM,
    DEFAULT_CONFIDENCE,
    DEFAULT_MODEL,
    DEFAULT_USE_LLM,
    DOMAIN,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)


class CameraAICoordinator(DataUpdateCoordinator[dict]):
    """Poll the server health and hold the latest analysis result."""

    def __init__(self, hass: HomeAssistant, client: CameraAIClient) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=10)
        )
        self.client = client

    async def _async_update_data(self) -> dict:
        try:
            health, cfg, cam_st = await asyncio.gather(
                self.client.health(), self.client.get_config(), self.client.cameras_status()
            )
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Camera AI unreachable: {err}") from err
        data = dict(self.data or {})
        data["health"] = health
        data["config"] = cfg
        data["cameras"] = cam_st.get("cameras") or []
        data["camera_default"] = cam_st.get("default")
        return data


def _entry_config(entry: ConfigEntry) -> dict:
    return {**entry.data, **entry.options}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    client = CameraAIClient(entry.data[CONF_URL], session)
    coordinator = CameraAICoordinator(hass, client)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "config": _entry_config(entry),
    }

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Refresh the stored config when options change."""
    store = hass.data[DOMAIN][entry.entry_id]
    store["config"] = _entry_config(entry)


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

def _register_services(hass: HomeAssistant) -> None:
    async def _analyze_camera(call: ServiceCall) -> dict:
        return await _run_analysis(hass, call, by_url=False)

    async def _analyze_url(call: ServiceCall) -> dict:
        return await _run_analysis(hass, call, by_url=True)

    async def _set_config(call: ServiceCall) -> None:
        await _set_runtime_config(hass, call)

    hass.services.async_register(
        DOMAIN,
        "analyze_camera",
        _analyze_camera,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "analyze_url",
        _analyze_url,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, "set_config", _set_config)


async def _set_runtime_config(hass: HomeAssistant, call: ServiceCall) -> None:
    """Ändra inställningar på servern direkt från en automation."""
    entry_id = next(iter(hass.data[DOMAIN]))
    store = hass.data[DOMAIN][entry_id]
    client: CameraAIClient = store["client"]
    coordinator: CameraAICoordinator = store["coordinator"]

    if not call.data:
        raise HomeAssistantError("Provide at least one setting to change")
    payload = server_payload(call.data)
    if not payload:
        raise HomeAssistantError("No supported settings provided")

    await client.set_config(payload)

    # Uppdatera cachad config så sensorerna visar nya värden direkt
    cfg = await client.get_config()
    store["config"] = cfg
    data = dict(coordinator.data or {})
    data["config"] = cfg
    await coordinator.async_set_updated_data(data)


async def _run_analysis(hass: HomeAssistant, call: ServiceCall, by_url: bool) -> dict:
    """Kör analys och returnerar resultatet så automations kan använda det.

    Returnerar bl.a. detections, counts (people/vehicles/animals), summary,
    description och annoterad bild som absolut URL (för t.ex. Telegram).
    """
    entry_id = next(iter(hass.data[DOMAIN]))
    store = hass.data[DOMAIN][entry_id]
    client: CameraAIClient = store["client"]
    coordinator: CameraAICoordinator = store["coordinator"]
    cfg: dict = store["config"]

    model = call.data.get(CONF_MODEL, cfg.get(CONF_MODEL, DEFAULT_MODEL))
    conf = float(
        call.data.get(CONF_CONFIDENCE, cfg.get(CONF_CONFIDENCE, DEFAULT_CONFIDENCE))
    )
    use_llm = bool(call.data.get(CONF_USE_LLM, cfg.get(CONF_USE_LLM, DEFAULT_USE_LLM)))
    prompt = call.data.get(CONF_PROMPT)

    if by_url:
        url = call.data.get("url")
        if not url:
            raise HomeAssistantError("url is required")
        result = await client.analyze_url(url, model, conf, use_llm, prompt)
    else:
        camera_entity = call.data.get("camera_entity") or cfg.get(CONF_CAMERA)
        if not camera_entity:
            raise HomeAssistantError(
                "No camera entity configured — set it in the integration options "
                "or pass camera_entity"
            )
        snap_dir = Path(hass.config.path("www", "snapshots"))
        await hass.async_add_executor_job(
            lambda: snap_dir.mkdir(parents=True, exist_ok=True)
        )
        snap_path = snap_dir / "camera_ai_latest.jpg"
        await hass.services.async_call(
            "camera",
            "snapshot",
            {"entity_id": camera_entity, "filename": str(snap_path)},
            blocking=True,
        )
        result = await client.analyze_file(snap_path, model, conf, use_llm, prompt)

    if result.get("error"):
        raise HomeAssistantError(f"Camera AI error: {result['error']}")

    # Gör den annoterade bilden tillgänglig som absolut URL (t.ex. för Telegram)
    if result.get("annotated_url"):
        result["annotated_url"] = f"{client.url}{result['annotated_url']}"

    health = await client.health()
    data = dict(coordinator.data or {})
    data["health"] = health
    data["result"] = result
    data["annotated_url"] = result.get("annotated_url")
    await coordinator.async_set_updated_data(data)
    return result
