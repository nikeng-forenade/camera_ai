"""Binary sensors (motion) – en per serverkamera."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    entities = []
    for cam in server_cameras(coordinator.data):
        if cam.get("camera_id"):
            entities.append(CameraAIMotionSensor(coordinator, entry, cam))
    async_add_entities(entities)


class CameraAIMotionSensor(CameraAICameraEntity, BinarySensorEntity):
    """ON när ett person-, djur- eller fordonsobjekt flyttar sig."""

    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, coordinator, entry: ConfigEntry, cam: dict) -> None:
        super().__init__(coordinator, entry, cam)
        self._attr_unique_id = f"{entry.entry_id}_{self._cam_id}_motion"
        self._attr_name = "Motion"

    @property
    def is_on(self) -> bool:
        cam = self.camera()
        return bool(cam and (cam.get("last_frame_age") or 0) <= 10 and cam.get("moving"))

    @property
    def extra_state_attributes(self) -> dict:
        cam = self.camera() or {}
        return {
            "camera_id": self._cam_id,
            "camera_name": cam.get("camera_name") or self._cam_name,
            "camera_state": cam.get("camera_state"),
            "stream_active": cam.get("stream_active"),
            "last_frame_age": cam.get("last_frame_age"),
            "detection_counts": cam.get("detection_counts") or {},
            "moving_counts": cam.get("moving_counts") or {},
        }
