"""Sensors for the Camera AI integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
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
    async_add_entities(
        [
            CameraAIStatusSensor(coordinator, entry),
            CameraAILastDetectionSensor(coordinator, entry),
            CameraAIDescriptionSensor(coordinator, entry),
        ]
    )


class CameraAIStatusSensor(CameraAIEntity, SensorEntity):
    """Online/offline + which model the server uses."""

    _attr_icon = "mdi:server-network"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_name = "Server status"

    @property
    def native_value(self) -> str:
        health = (self.coordinator.data or {}).get("health")
        return "online" if health else "offline"

    @property
    def extra_state_attributes(self) -> dict:
        health = (self.coordinator.data or {}).get("health") or {}
        return {
            "url": self.coordinator.client.url,
            "model": health.get("yolo_model"),
            "llm_model": health.get("llm_model"),
            "ollama_available": health.get("ollama_available"),
            "ha_enabled": health.get("ha_enabled"),
        }

    @property
    def available(self) -> bool:
        return True


class CameraAILastDetectionSensor(CameraAIEntity, SensorEntity):
    """Most recent detection classes + confidence."""

    _attr_icon = "mdi:eye-outline"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_detection"
        self._attr_name = "Last detection"

    @property
    def native_value(self) -> str:
        result = (self.coordinator.data or {}).get("result")
        if not result:
            return "unknown"
        dets = result.get("detections") or []
        if not dets:
            return "Inget"
        return ", ".join(d["class"] for d in dets)

    @property
    def extra_state_attributes(self) -> dict:
        result = (self.coordinator.data or {}).get("result") or {}
        dets = result.get("detections") or []
        return {
            "count": len(dets),
            "classes": [d["class"] for d in dets],
            "confidence": {d["class"]: d["confidence"] for d in dets},
            "summary": result.get("summary"),
            "model": result.get("model"),
            "inference_ms": result.get("inference_ms"),
        }


class CameraAIDescriptionSensor(CameraAIEntity, SensorEntity):
    """The Swedish scene description, e.g. 'Jag ser 1 bil och 1 katt.'"""

    _attr_icon = "mdi:form-textbox"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_description"
        self._attr_name = "Scene description"

    @property
    def native_value(self) -> str:
        result = (self.coordinator.data or {}).get("result")
        if not result:
            return "unknown"
        return result.get("summary") or "Inget"
