"""Camera AI-integration – kopplar Home Assistant till Camera AI-servern.

Auto-discovery: bara server-URL krävs i konfigurationen. Integrationen hämtar
därefter kameror och inställningar från servern och skapar enheter automatiskt:

  * En global "Camera AI"-enhet med serverstatus, runtime-config och senaste
    LLM-beskrivning.
  * En enhet per serverkamera ("Camera AI <kamera>") med motion, senaste
    detektering, person-/djur-/fordonsräknare och en live-snapshot.

Inget manuellt val av kameror eller entiteter behövs – lägger du till/tar bort
en kamera på servern laddas integrationen om automatiskt.

Tjänster:
  * analyze_camera / analyze_url – analys av en bild (YOLO + ev. LLM).
  * describe_image               – skicka en bild till serverns vision-LLM och
                                   få en beskrivning (camera_entity eller url).
  * set_config                   – ändra serverinställningar direkt.
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

_SERVICES = ("analyze_camera", "analyze_url", "describe_image", "set_config")
_services_registered = False


class CameraAICoordinator(DataUpdateCoordinator[dict]):
    """Pollar servern (health, config, kamerastatus) var 10:e sekund."""

    def __init__(self, hass: HomeAssistant, client: CameraAIClient, entry_id: str) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=10)
        )
        self.client = client
        self._entry_id = entry_id
        self._known_camera_ids: set[str] | None = None

    async def _async_update_data(self) -> dict:
        try:
            health, cfg, cam_st = await asyncio.gather(
                self.client.health(),
                self.client.get_config(),
                self.client.cameras_status(),
            )
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Camera AI unreachable: {err}") from err

        cams = cam_st.get("cameras") or []
        ids = {str(c.get("camera_id")) for c in cams if c.get("camera_id")}
        # Kamera tillagd/borttagen på servern → skapa/ta bort entiteter genom en
        # automatisk omladdning (ny coordinator → inga upprepade omladdningar).
        if self._known_camera_ids is not None and ids != self._known_camera_ids:
            _LOGGER.info("Kameror på servern ändrades – laddar om integrationen")
            self._known_camera_ids = ids
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self._entry_id)
            )
        self._known_camera_ids = ids

        data = dict(self.data or {})
        data["health"] = health
        data["config"] = cfg
        data["cameras"] = cams
        data["camera_default"] = cam_st.get("default")
        return data


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    global _services_registered

    session = async_get_clientsession(hass)
    client = CameraAIClient(entry.data[CONF_URL], session)
    coordinator = CameraAICoordinator(hass, client, entry.entry_id)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not _services_registered:
        _register_services(hass)
        _services_registered = True
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    global _services_registered

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        # Avregistrera tjänsterna när den sista instansen tas bort.
        if not hass.data[DOMAIN] and _services_registered:
            for service in _SERVICES:
                hass.services.async_remove(DOMAIN, service)
            _services_registered = False
    return unload_ok


# ---------------------------------------------------------------------------
# Hjälpare som tjänsterna delar
# ---------------------------------------------------------------------------

def _store(hass: HomeAssistant) -> tuple[CameraAIClient, CameraAICoordinator]:
    """Returnera (client, coordinator) för integrationens aktiva instans."""
    entry_id = next(iter(hass.data[DOMAIN]))
    store = hass.data[DOMAIN][entry_id]
    return store["client"], store["coordinator"]


async def _snapshot_camera(hass: HomeAssistant, camera_entity: str) -> Path:
    """Ta en snapshot av en HA-kameraentity och returnera filsökvägen."""
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
    return snap_path


async def _store_result(
    coordinator: CameraAICoordinator, client: CameraAIClient, result: dict
) -> dict:
    """Spara analys-/LLM-resultat i coordinatorn så entiteterna uppdateras."""
    if result.get("error"):
        raise HomeAssistantError(f"Camera AI error: {result['error']}")
    if result.get("annotated_url"):
        result["annotated_url"] = f"{client.url}{result['annotated_url']}"
    data = dict(coordinator.data or {})
    data["health"] = await client.health()
    data["result"] = result
    data["description"] = (
        result.get("description")
        or result.get("summary")
        or (result.get("result") or {}).get("description")
    )
    await coordinator.async_set_updated_data(data)
    return result


def _analyze_options(
    call: ServiceCall, server_cfg: dict
) -> tuple[str, float, bool, str | None]:
    """Läs model/conf/use_llm/prompt ur service-call (fallback: serverconfig)."""
    model = call.data.get(CONF_MODEL) or server_cfg.get("model") or DEFAULT_MODEL
    try:
        conf = float(
            call.data.get(CONF_CONFIDENCE)
            or server_cfg.get("conf")
            or DEFAULT_CONFIDENCE
        )
    except (TypeError, ValueError):
        conf = float(DEFAULT_CONFIDENCE)
    use_llm = (
        call.data[CONF_USE_LLM]
        if CONF_USE_LLM in call.data
        else bool(server_cfg.get("use_llm", DEFAULT_USE_LLM))
    )
    prompt = call.data.get(CONF_PROMPT)
    return model, conf, bool(use_llm), prompt


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

def _register_services(hass: HomeAssistant) -> None:
    async def _analyze_camera(call: ServiceCall) -> dict:
        return await _run_analysis(hass, call, by_url=False, force_llm=False)

    async def _analyze_url(call: ServiceCall) -> dict:
        return await _run_analysis(hass, call, by_url=True, force_llm=False)

    async def _describe_image(call: ServiceCall) -> dict:
        return await _run_analysis(
            hass, call, by_url=bool(call.data.get("url")), force_llm=True
        )

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
    hass.services.async_register(
        DOMAIN,
        "describe_image",
        _describe_image,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, "set_config", _set_config)


async def _run_analysis(
    hass: HomeAssistant, call: ServiceCall, by_url: bool, force_llm: bool
) -> dict:
    """Analysera en bild (snapshot av kameraentity ELLER URL) på servern.

    force_llm=True skickar bilden till serverns vision-LLM (beskrivning).
    """
    client, coordinator = _store(hass)
    server_cfg: dict = (coordinator.data or {}).get("config") or {}
    model, conf, use_llm, prompt = _analyze_options(call, server_cfg)
    if force_llm:
        use_llm = True

    if by_url:
        url = call.data.get("url")
        if not url:
            raise HomeAssistantError("Field 'url' is required.")
        result = await client.analyze_url(url, model, conf, use_llm, prompt)
    else:
        camera_entity = call.data.get("camera_entity")
        if not camera_entity:
            raise HomeAssistantError(
                "Field 'camera_entity' is required – a camera entity to snapshot, "
                "e.g. camera.camera_ai_backyard_live or your Reolink camera."
            )
        snap_path = await _snapshot_camera(hass, camera_entity)
        result = await client.analyze_file(snap_path, model, conf, use_llm, prompt)

    return await _store_result(coordinator, client, result)


async def _set_runtime_config(hass: HomeAssistant, call: ServiceCall) -> None:
    """Ändra serverinställningar (model/conf/device/LLM) direkt via service."""
    client, coordinator = _store(hass)
    if not call.data:
        raise HomeAssistantError("Provide at least one setting to change")
    payload = server_payload(call.data)
    if not payload:
        raise HomeAssistantError("No supported settings provided")
    await client.set_config(payload)
    cfg = await client.get_config()
    data = dict(coordinator.data or {})
    data["config"] = cfg
    await coordinator.async_set_updated_data(data)
