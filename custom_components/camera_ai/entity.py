"""Shared entity base for the Camera AI integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION


class CameraAIEntity(CoordinatorEntity):
    """Base entity that links to the coordinator and the Camera AI device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Camera AI",
            "manufacturer": "Camera AI",
            "model": "Reolink + YOLO + LLM",
            "sw_version": VERSION,
            "configuration_url": coordinator.client.url,
        }


def live_camera(data: dict | None) -> dict | None:
    """Den kamera entiteterna följer (serverns default, annars första).

    Komponenten läser löpande /api/cameras/status från servern och visar
    entiteter + bild för den här kameran.
    """
    if not data:
        return None
    cams = data.get("cameras") or []
    if not cams:
        return None
    did = data.get("camera_default")
    for c in cams:
        if c.get("camera_id") == did:
            return c
    return cams[0]


_VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle", "boat", "airplane", "train"}
_ANIMAL_CLASSES = {"cat", "dog", "bird", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}


def detection_counts(camera: dict | None) -> dict:
    """people/vehicles/animals/colors från en kamerastatus (live)."""
    if not camera:
        return {"people": 0, "vehicles": 0, "animals": 0, "colors": []}
    counts = camera.get("detection_counts") or {}
    people = counts.get("person", 0)
    vehicles = sum(v for k, v in counts.items() if k in _VEHICLE_CLASSES)
    animals = sum(v for k, v in counts.items() if k in _ANIMAL_CLASSES)
    return {"people": people, "vehicles": vehicles, "animals": animals, "colors": []}
