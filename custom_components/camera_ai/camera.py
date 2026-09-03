"""Camera-platform – live-annoterad snapshot per serverkamera."""

from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import CameraAICameraEntity, server_cameras


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    entities = []
    for cam in server_cameras(coordinator.data):
        if cam.get("camera_id"):
            entities.append(CameraAICamera(coordinator, entry, client, cam))
    async_add_entities(entities)


class CameraAICamera(CameraAICameraEntity, Camera):
    """Visar senaste annoterade bilden från servern för en specifik kamera."""

    _attr_icon = "mdi:cctv"
    content_type = "image/jpeg"

    def __init__(self, coordinator, entry: ConfigEntry, client, cam: dict) -> None:
        CameraAICameraEntity.__init__(self, coordinator, entry, cam)
        Camera.__init__(self)
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_{self._cam_id}_camera"
        self._attr_name = "Live"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        if self.camera() is None:
            return None
        try:
            return await self._client.fetch_image(
                f"/api/live/{self._cam_id}/snapshot.jpg"
            )
        except Exception:  # noqa: BLE001 – kameran ska inte krascha på nätverksfel
            return None

    @property
    def extra_state_attributes(self) -> dict:
        cam = self.camera() or {}
        return {
            "camera_id": self._cam_id,
            "camera_name": cam.get("camera_name") or self._cam_name,
            "camera_state": cam.get("camera_state"),
            "stream_active": cam.get("stream_active"),
            "live_enabled": cam.get("live_enabled"),
            "events_enabled": cam.get("events_enabled"),
            "model": cam.get("model"),
            "device": cam.get("actual_device"),
            "ai_fps": cam.get("ai_fps"),
            "detection_counts": cam.get("detection_counts") or {},
        }
