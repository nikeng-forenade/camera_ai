"""Camera platform — shows the latest annotated snapshot from Camera AI."""

from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    async_add_entities([CameraAICamera(coordinator, entry, client)])


class CameraAICamera(CoordinatorEntity, Camera):
    """Proxies the annotated image served by the Camera AI server."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:cctv"

    def __init__(self, coordinator, entry, client) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_camera"
        self._attr_name = "Annotated snapshot"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Camera AI",
            "manufacturer": "Camera AI",
            "model": "Reolink + YOLO + LLM",
            "sw_version": "0.1.0",
            "configuration_url": coordinator.client.url,
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        url = (self.coordinator.data or {}).get("annotated_url")
        if not url:
            return None
        try:
            return await self._client.fetch_image(url)
        except Exception:  # noqa: BLE001 - camera should not crash on network issues
            return None
