"""Sensorer för Camera AI (globala + en uppsättning per serverkamera)."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import (
    CameraAICameraEntity,
    CameraAIServerEntity,
    detection_counts,
    server_cameras,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list = [
        CameraAIStatusSensor(coordinator, entry),
        CameraAIRuntimeConfigSensor(coordinator, entry),
        CameraAIDescriptionSensor(coordinator, entry),
        CameraAIEventCountSensor(coordinator, entry),
        CameraAILastEventSensor(coordinator, entry),
        CameraAILastPlateSensor(coordinator, entry),
    ]
    for cam in server_cameras(coordinator.data):
        if not cam.get("camera_id"):
            continue
        entities += [
            CameraAILastDetectionSensor(coordinator, entry, cam),
            CameraAIPeopleSensor(coordinator, entry, cam),
            CameraAIAnimalSensor(coordinator, entry, cam),
            CameraAIVehicleSensor(coordinator, entry, cam),
            CameraAIPlateSensor(coordinator, entry, cam),
        ]
    async_add_entities(entities)


class CameraAIStatusSensor(CameraAIServerEntity, SensorEntity):
    """Online/offline + info om servern."""

    _attr_icon = "mdi:server-network"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_server_status"
        self._attr_name = "Server status"

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        return "online" if (self.coordinator.data or {}).get("health") else "offline"

    @property
    def extra_state_attributes(self) -> dict:
        health = (self.coordinator.data or {}).get("health") or {}
        return {
            "url": self.coordinator.client.url,
            "cameras": len((self.coordinator.data or {}).get("cameras") or []),
            "model": health.get("yolo_model"),
            "llm_model": health.get("llm_model"),
            "ollama_available": health.get("ollama_available"),
            "version": health.get("version"),
        }


class CameraAIRuntimeConfigSensor(CameraAIServerEntity, SensorEntity):
    """Aktiv modell/conf/device på servern (läses från /api/config)."""

    _attr_icon = "mdi:tune-variant"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_runtime_config"
        self._attr_name = "Runtime config"

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        cfg = (self.coordinator.data or {}).get("config") or {}
        return cfg.get("model", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        cfg = (self.coordinator.data or {}).get("config") or {}
        return {
            "confidence": cfg.get("conf"),
            "device": cfg.get("device"),
            "use_llm": cfg.get("use_llm"),
            "llm_model": cfg.get("llm_model"),
            "keep_alive": cfg.get("keep_alive"),
            "ollama_available": cfg.get("ollama_available"),
        }


class CameraAIDescriptionSensor(CameraAIServerEntity, SensorEntity):
    """Senaste svenska beskrivning från serverns vision-LLM."""

    _attr_icon = "mdi:form-textbox"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_description"
        self._attr_name = "Scene description"

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        desc = data.get("description")
        if desc:
            return str(desc)
        summary = (data.get("result") or {}).get("summary")
        return summary or "Inget"


def _events(coordinator) -> list[dict]:
    return [event for event in ((coordinator.data or {}).get("events") or []) if isinstance(event, dict)]


def _lpr(coordinator) -> list[dict]:
    """Senast upplästa registreringsskyltarna (nyaste först)."""
    return [item for item in ((coordinator.data or {}).get("lpr") or []) if isinstance(item, dict)]


def _lpr_for_camera(coordinator, cam_name: str) -> list[dict]:
    return [item for item in _lpr(coordinator) if (item.get("camera") or "") == cam_name]


class CameraAIEventCountSensor(CameraAIServerEntity, SensorEntity):
    """Antal detektionsevent från den senaste timmen."""

    _attr_icon = "mdi:bell-badge-outline"
    _attr_native_unit_of_measurement = "event"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_events_last_hour"
        self._attr_name = "Events last hour"

    @property
    def native_value(self) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - 3600
        return sum(float(event.get("ts") or 0) >= cutoff for event in _events(self.coordinator))


class CameraAILastEventSensor(CameraAIServerEntity, SensorEntity):
    """Senaste eventets sammanfattning med tidsstämpel som attribut."""

    _attr_icon = "mdi:bell-outline"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_event"
        self._attr_name = "Last event"

    @property
    def native_value(self) -> str:
        events = _events(self.coordinator)
        return str(events[0].get("summary") or "Ny detektion") if events else "Inget"

    @property
    def extra_state_attributes(self) -> dict:
        events = _events(self.coordinator)
        if not events:
            return {"event_id": None, "timestamp": None, "camera": None}
        event = events[0]
        return {
            "event_id": event.get("id"),
            "timestamp": event.get("ts"),
            "camera": event.get("camera"),
            "classes": event.get("classes") or [],
        }


class CameraAILastPlateSensor(CameraAIServerEntity, SensorEntity):
    """Senast upplästa registreringsskylten från valfri kamera."""

    _attr_icon = "mdi:car-key"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_lpr_last_plate"
        self._attr_name = "LPR last plate"

    @property
    def native_value(self) -> str:
        items = _lpr(self.coordinator)
        return str(items[0].get("plate") or "Inget") if items else "Inget"

    @property
    def extra_state_attributes(self) -> dict:
        items = _lpr(self.coordinator)
        if not items:
            return {"plate": None, "camera": None, "timestamp": None, "confidence": None}
        item = items[0]
        return {
            "plate": item.get("plate"),
            "camera": item.get("camera"),
            "timestamp": item.get("ts"),
            "confidence": item.get("confidence"),
        }


class CameraAILastDetectionSensor(CameraAICameraEntity, SensorEntity):
    """Senaste detekterade klasser + konfidens för kameran."""

    _attr_icon = "mdi:eye-outline"

    def __init__(self, coordinator, entry: ConfigEntry, cam: dict) -> None:
        super().__init__(coordinator, entry, cam)
        self._attr_unique_id = f"{entry.entry_id}_{self._cam_id}_last_detection"
        self._attr_name = "Last detection"

    @property
    def native_value(self) -> str:
        cam = self.camera() or {}
        dets = cam.get("detections") or []
        if not dets:
            return "Inget"
        return ", ".join(d["class"] for d in dets)

    @property
    def extra_state_attributes(self) -> dict:
        cam = self.camera() or {}
        dets = cam.get("detections") or []
        counts = detection_counts(cam)
        return {
            "camera_id": self._cam_id,
            "camera_name": cam.get("camera_name") or self._cam_name,
            "camera_state": cam.get("camera_state"),
            "stream_active": cam.get("stream_active"),
            "count": len(dets),
            "classes": [d["class"] for d in dets],
            "confidence": {d["class"]: d["confidence"] for d in dets},
            "people": counts["people"],
            "vehicles": counts["vehicles"],
            "animals": counts["animals"],
            "last_detection_ts": cam.get("last_detection_ts"),
        }


class CameraAIPeopleSensor(CameraAICameraEntity, SensorEntity):
    """Antal personer just nu på kameran."""

    _attr_icon = "mdi:account-group"
    _attr_native_unit_of_measurement = "st"

    def __init__(self, coordinator, entry: ConfigEntry, cam: dict) -> None:
        super().__init__(coordinator, entry, cam)
        self._attr_unique_id = f"{entry.entry_id}_{self._cam_id}_people"
        self._attr_name = "People"

    @property
    def native_value(self) -> int:
        return detection_counts(self.camera()).get("people", 0)


class CameraAIAnimalSensor(CameraAICameraEntity, SensorEntity):
    """Antal djur just nu på kameran."""

    _attr_icon = "mdi:paw"
    _attr_native_unit_of_measurement = "st"

    def __init__(self, coordinator, entry: ConfigEntry, cam: dict) -> None:
        super().__init__(coordinator, entry, cam)
        self._attr_unique_id = f"{entry.entry_id}_{self._cam_id}_animals"
        self._attr_name = "Animals"

    @property
    def native_value(self) -> int:
        return detection_counts(self.camera()).get("animals", 0)


class CameraAIVehicleSensor(CameraAICameraEntity, SensorEntity):
    """Antal fordon just nu på kameran."""

    _attr_icon = "mdi:car"
    _attr_native_unit_of_measurement = "st"

    def __init__(self, coordinator, entry: ConfigEntry, cam: dict) -> None:
        super().__init__(coordinator, entry, cam)
        self._attr_unique_id = f"{entry.entry_id}_{self._cam_id}_vehicles"
        self._attr_name = "Vehicles"

    @property
    def native_value(self) -> int:
        return detection_counts(self.camera()).get("vehicles", 0)


class CameraAIPlateSensor(CameraAICameraEntity, SensorEntity):
    """Senast upplästa registreringsskylten för den här kameran."""

    _attr_icon = "mdi:car-key"

    def __init__(self, coordinator, entry: ConfigEntry, cam: dict) -> None:
        super().__init__(coordinator, entry, cam)
        self._attr_unique_id = f"{entry.entry_id}_{self._cam_id}_lpr_last_plate"
        self._attr_name = "LPR last plate"

    @property
    def native_value(self) -> str:
        items = _lpr_for_camera(self.coordinator, self._cam_name)
        return str(items[0].get("plate") or "Inget") if items else "Inget"

    @property
    def extra_state_attributes(self) -> dict:
        items = _lpr_for_camera(self.coordinator, self._cam_name)
        counts = detection_counts(self.camera())
        if not items:
            return {
                "camera_id": self._cam_id,
                "camera_name": self._cam_name,
                "plate": None,
                "confidence": None,
                "timestamp": None,
                "count": 0,
                "vehicles": counts["vehicles"],
            }
        item = items[0]
        return {
            "camera_id": self._cam_id,
            "camera_name": self._cam_name,
            "plate": item.get("plate"),
            "confidence": item.get("confidence"),
            "timestamp": item.get("ts"),
            "count": len(items),
            "vehicles": counts["vehicles"],
        }
