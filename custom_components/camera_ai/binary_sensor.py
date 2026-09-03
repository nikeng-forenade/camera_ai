"""Binary sensor (motion) for the Camera AI integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import CameraAIEntity, live_camera


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([CameraAIMotionSensor(coordinator, entry)])


class CameraAIMotionSensor(CameraAIEntity, BinarySensorEntity):
    """ON när person/bil/djur detekteras på live-kameran (eller senaste analysen)."""

    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_motion"
        self._attr_name = "Motion"

    @property
    def is_on(self) -> bool:
        cam = live_camera(self.coordinator.data or {})
        if cam is not None:
            return bool(cam.get("detections"))
        result = (self.coordinator.data or {}).get("result")
        return bool((result or {}).get("detections"))

    @property
    def extra_state_attributes(self) -> dict:
        cam = live_camera(self.coordinator.data or {})
        if cam is None:
            return {}
        return {
            "camera_id": cam.get("camera_id"),
            "camera": cam.get("camera_name"),
            "camera_state": cam.get("camera_state"),
            "detection_counts": cam.get("detection_counts") or {},
        }
