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
