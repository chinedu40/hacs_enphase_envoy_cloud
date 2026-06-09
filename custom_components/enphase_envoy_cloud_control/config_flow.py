"""Config flow for Enphase Envoy Cloud Control (Enlighten credentials)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .options_flow import EnphaseOptionsFlowHandler

__all__ = ["EnphaseConfigFlow"]

_LOGGER = logging.getLogger(__name__)


class EnphaseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the configuration flow for Enphase Envoy Cloud Control."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step for setup."""
        errors = {}

        if user_input is not None:
            # Basic validation
            if not user_input.get("email") or not user_input.get("password"):
                errors["base"] = "missing_credentials"
            else:
                await self.async_set_unique_id(user_input["email"])
                self._abort_if_unique_id_configured()
                _LOGGER.info(
                    "[Enphase] Creating new config entry for %s",
                    user_input["email"],
                )
                return self.async_create_entry(
                    title="Enphase Envoy Cloud Control", data=user_input
                )

        data_schema = vol.Schema(
            {
                vol.Required("email"): str,
                vol.Required("password"): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EnphaseOptionsFlowHandler:
        """Return the options flow handler."""
        _LOGGER.debug(
            "[Enphase] Creating options flow handler for entry_id=%s",
            config_entry.entry_id,
        )
        return EnphaseOptionsFlowHandler(config_entry)
