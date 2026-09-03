"""Basklasser + hjälpare för Camera AI-integrationen.

Två sorters enheter skapas automatiskt från servern:
  * "Camera AI"                       – global server (status/runtime/beskrivning)
  * "Camera AI <kamera>" (per kamera) – motion, räknare och live-snapshot
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION

_VEHICLE_CLASSES = {
    "car", "truck", "bus", "motorcycle", "bicycle", "boat", "airplane", "train",
}
_ANIMAL_CLASSES = {
    "cat", "dog", "bird", "horse", "sheep", "cow", "elephant", "bear",
    "zebra", "giraffe",
}


def server_cameras(data: dict | None) -> list:
    """Alla kameror servern rapporterar just nu."""
    return (data or {}).get("cameras") or []


def server_device_info(entry: ConfigEntry) -> dict:
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": "Camera AI",
        "manufacturer": "Camera AI",
        "model": "YOLO + vision-LLM",
        "sw_version": VERSION,
    }


def camera_device_info(entry: ConfigEntry, cam: dict) -> dict:
    cam_id = str(cam.get("camera_id") or "")
    cam_name = str(cam.get("camera_name") or cam_id or "Kamera")
    return {
        "identifiers": {(DOMAIN, entry.entry_id, cam_id)},
        "name": f"Camera AI {cam_name}",
        "manufacturer": "Camera AI",
        "model": "Live-kamera",
        "sw_version": VERSION,
    }


def detection_counts(camera: dict | None) -> dict:
    """people/vehicles/animals ur live detection_counts (per klass)."""
    out = {"people": 0, "vehicles": 0, "animals": 0}
    if not camera:
        return out
    counts = camera.get("detection_counts") or {}
    out["people"] = int(counts.get("person", 0))
    out["vehicles"] = sum(int(v) for k, v in counts.items() if k in _VEHICLE_CLASSES)
    out["animals"] = sum(int(v) for k, v in counts.items() if k in _ANIMAL_CLASSES)
    return out


class CameraAIServerEntity(CoordinatorEntity):
    """Global entitet på 'Camera AI'-enheten (serverstatus, runtime …)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = server_device_info(entry)


class CameraAICameraEntity(CoordinatorEntity):
    """Bas för entiteter som hör till en specifik serverkamera."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, cam: dict) -> None:
        super().__init__(coordinator)
        self._cam_id = str(cam.get("camera_id") or "")
        self._cam_name = str(cam.get("camera_name") or self._cam_id or "Kamera")
        self._attr_device_info = camera_device_info(entry, cam)

    def camera(self) -> dict | None:
        """Senaste status för den här kameran (None om borttagen från servern)."""
        for cam in server_cameras(self.coordinator.data):
            if cam.get("camera_id") == self._cam_id:
                return cam
        return None

    @property
    def available(self) -> bool:
        if self.camera() is None:
            return False
        return super().available
