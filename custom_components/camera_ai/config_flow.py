"""Config flow and options flow for the Camera AI integration."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .client import CameraAIClient
from .const import (
    CONF_CAMERA,
    CONF_CONFIDENCE,
    CONF_MODEL,
    CONF_USE_LLM,
    DEFAULT_CONFIDENCE,
    DEFAULT_MODEL,
    DEFAULT_MODELS,
    DEFAULT_USE_LLM,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def _fetch_health(url: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as session:
        client = CameraAIClient(url, session)
        return await client.health()


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_URL, default=d.get(CONF_URL, "")): str,
            vol.Required(
                CONF_MODEL, default=d.get(CONF_MODEL, DEFAULT_MODEL)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=m, label=m)
                        for m in DEFAULT_MODELS
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_CONFIDENCE,
                default=d.get(CONF_CONFIDENCE, DEFAULT_CONFIDENCE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.05, max=0.95, step=0.05, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_USE_LLM, default=d.get(CONF_USE_LLM, DEFAULT_USE_LLM)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_CAMERA, default=d.get(CONF_CAMERA, "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="camera")),
        }
    )


class CameraAIConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Camera AI."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = str(user_input[CONF_URL]).strip().rstrip("/")
            try:
                await _fetch_health(url)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Health check failed for %s: %s", url, exc)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                data = {**user_input, CONF_URL: url}
                return self.async_create_entry(title="Camera AI", data=data)
        return self.async_show_form(step_id="user", data_schema=_schema(), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return CameraAIOptionsFlow(config_entry)


class CameraAIOptionsFlow(config_entries.OptionsFlow):
    """Handle options (model, confidence, camera, LLM)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(defaults))
