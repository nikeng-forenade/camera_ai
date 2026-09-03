"""Config flow för Camera AI – bara server-URL, allt annat auto-hämtas.

När användaren anger URL:en frågar vi servern om hälsa + kameror och visar
vilka som hittats. Kameror/entiteter skapas sedan automatiskt per serverkamera –
inget manuellt val av kamera eller entitet krävs.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .client import CameraAIClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def _discover(url: str) -> dict:
    """Fråga servern om hälsa och kameror (auto-discovery)."""
    async with httpx.AsyncClient(timeout=10) as session:
        client = CameraAIClient(url, session)
        health = await client.health()
        cam_st = await client.cameras_status()
    names = [
        f"- {c.get('camera_name') or c.get('camera_id')}"
        for c in (cam_st.get("cameras") or [])
    ]
    return {
        "count": len(names),
        "names": "\n".join(names) if names else "- (inga kameror registrerade än)",
        "version": health.get("version") or "?",
    }


class CameraAIConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Camera AI."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = str(user_input[CONF_URL]).strip().rstrip("/")
            try:
                info = await _discover(url)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Discovery failed for %s: %s", url, exc)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                self._url = url
                self._info = info
                return await self.async_step_confirm()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_URL, default="http://"): str}
            ),
            errors=errors,
        )

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="Camera AI", data={CONF_URL: self._url}
            )
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "version": self._info["version"],
                "camera_count": str(self._info["count"]),
                "cameras": self._info["names"],
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return CameraAIOptionsFlow(config_entry)


class CameraAIOptionsFlow(config_entries.OptionsFlow):
    """Server-URL + visa Camera AI i HA:s sidofält (panel)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    def _schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_URL,
                    default=self.config_entry.data.get(CONF_URL, ""),
                ): str,
                vol.Optional(
                    "panel_enabled",
                    default=bool(self.config_entry.options.get("panel_enabled", True)),
                ): bool,
            }
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        try:
            if user_input is not None:
                url = str(user_input.get(CONF_URL)).strip().rstrip("/")
                panel = bool(user_input.get("panel_enabled", True))
                data = {**self.config_entry.data, CONF_URL: url}
                options = {"panel_enabled": panel}
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=data, options=options
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data=options)
            return self.async_show_form(step_id="init", data_schema=self._schema())
        except Exception as exc:  # noqa: BLE001 – logga så vi ser orsaken till 500
            _LOGGER.exception("Fel i Camera AI-alternativ: %s", exc)
            return self.async_show_form(step_id="init", data_schema=self._schema())
