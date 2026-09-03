"""Sensors for the Camera AI integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import CameraAIEntity, detection_counts, live_camera


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            CameraAIStatusSensor(coordinator, entry),
            CameraAIRuntimeConfigSensor(coordinator, entry),
            CameraAILastDetectionSensor(coordinator, entry),
            CameraAIDescriptionSensor(coordinator, entry),
            CameraAIPeopleSensor(coordinator, entry),
            CameraAIAnimalSensor(coordinator, entry),
            CameraAIVehicleSensor(coordinator, entry),
            CameraAIVehicleColorsSensor(coordinator, entry),
        ]
    )


def _counts(coordinator) -> dict:
    """people/vehicles/animals - live-kamera om möjligt, annars senaste analys."""
    cam = live_camera(coordinator.data or {})
    if cam is not None:
        return detection_counts(cam)
    return ((coordinator.data or {}).get("result") or {}).get("counts") or {}


def _detections(coordinator) -> tuple:
    """Returnerar (detections, camera_id, camera_name) från live om möjligt."""
    cam = live_camera(coordinator.data or {})
    if cam is not None:
        return (
            (cam.get("detections") or []),
            cam.get("camera_id"),
            cam.get("camera_name"),
        )
    result = (coordinator.data or {}).get("result") or {}
    return (result.get("detections") or []), None, None


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


class CameraAIRuntimeConfigSensor(CameraAIEntity, SensorEntity):
    """Current server runtime settings (from /api/config)."""

    _attr_icon = "mdi:tune-variant"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_runtime_config"
        self._attr_name = "Runtime config"

    @property
    def native_value(self) -> str:
        cfg = (self.coordinator.data or {}).get("config") or {}
        return cfg.get("model", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        cfg = (self.coordinator.data or {}).get("config") or {}
        keep_alive = cfg.get("keep_alive")
        return {
            "model": cfg.get("model"),
            "confidence": cfg.get("conf"),
            "device": cfg.get("device"),
            "use_llm": cfg.get("use_llm"),
            "llm_model": cfg.get("llm_model"),
            "prompt": cfg.get("prompt"),
            "keep_alive": keep_alive if keep_alive is not None else "default (5 min)",
            "ollama_available": cfg.get("ollama_available"),
        }


class CameraAILastDetectionSensor(CameraAIEntity, SensorEntity):
    """Most recent detection classes + confidence."""

    _attr_icon = "mdi:eye-outline"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_detection"
        self._attr_name = "Last detection"

    @property
    def native_value(self) -> str:
        dets, _, _ = _detections(self.coordinator)
        if not dets:
            return "Inget"
        return ", ".join(d["class"] for d in dets)

    @property
    def extra_state_attributes(self) -> dict:
        dets, cam_id, cam_name = _detections(self.coordinator)
        counts = _counts(self.coordinator)
        cam = live_camera(self.coordinator.data or {})
        attrs: dict = {
            "count": len(dets),
            "classes": [d["class"] for d in dets],
            "confidence": {d["class"]: d["confidence"] for d in dets},
            "people": counts.get("people", 0),
            "animals": counts.get("animals", 0),
            "vehicles": counts.get("vehicles", 0),
        }
        if cam_id:
            attrs["camera_id"] = cam_id
            attrs["camera"] = cam_name
        if cam:
            attrs["camera_state"] = cam.get("camera_state")
            attrs["last_detection_ts"] = cam.get("last_detection_ts")
        result = (self.coordinator.data or {}).get("result") or {}
        if result:
            attrs["summary"] = result.get("summary")
            attrs["model"] = result.get("model")
            attrs["inference_ms"] = result.get("inference_ms")
        return attrs


class CameraAIDescriptionSensor(CameraAIEntity, SensorEntity):
    """The Swedish scene description, e.g. 'Jag ser 1 röd bil och 1 katt.'"""

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


class CameraAIPeopleSensor(CameraAIEntity, SensorEntity):
    """Number of people detected in the last analysis."""

    _attr_icon = "mdi:account-group"
    _attr_native_unit_of_measurement = "st"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_people"
        self._attr_name = "People"

    @property
    def native_value(self) -> int:
        return _counts(self.coordinator).get("people", 0)


class CameraAIAnimalSensor(CameraAIEntity, SensorEntity):
    """Number of animals detected in the last analysis."""

    _attr_icon = "mdi:paw"
    _attr_native_unit_of_measurement = "st"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_animals"
        self._attr_name = "Animals"

    @property
    def native_value(self) -> int:
        return _counts(self.coordinator).get("animals", 0)


class CameraAIVehicleSensor(CameraAIEntity, SensorEntity):
    """Number of vehicles detected in the last analysis."""

    _attr_icon = "mdi:car"
    _attr_native_unit_of_measurement = "st"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_vehicles"
        self._attr_name = "Vehicles"

    @property
    def native_value(self) -> int:
        return _counts(self.coordinator).get("vehicles", 0)


class CameraAIVehicleColorsSensor(CameraAIEntity, SensorEntity):
    """Colours of the vehicles detected in the last analysis."""

    _attr_icon = "mdi:palette"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_vehicle_colors"
        self._attr_name = "Vehicle colours"

    @property
    def native_value(self) -> str:
        colors = _counts(self.coordinator).get("colors") or []
        if not colors:
            return "Inga"
        return ", ".join(dict.fromkeys(colors))

    @property
    def extra_state_attributes(self) -> dict:
        return {"colors": _counts(self.coordinator).get("colors") or []}
