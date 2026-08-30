"""Binary sensor (motion) for the Camera AI integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import CameraAIEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([CameraAIMotionSensor(coordinator, entry)])


class CameraAIMotionSensor(CameraAIEntity, BinarySensorEntity):
    """ON when people/cars/animals were detected in the last analysis."""

    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_motion"
        self._attr_name = "Motion"

    @property
    def is_on(self) -> bool:
        result = (self.coordinator.data or {}).get("result")
        if not result:
            return False
        return bool(result.get("detections"))
