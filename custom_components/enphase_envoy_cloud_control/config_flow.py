"""Config flow for Enphase Envoy Cloud Control (Enlighten credentials)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import requests
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .enphase_client import AuthError, EnphaseClient
from .options_flow import EnphaseOptionsFlowHandler

__all__ = ["EnphaseConfigFlow"]

_LOGGER = logging.getLogger(__name__)


async def _async_validate_credentials(
    hass: HomeAssistant, email: str, password: str
) -> str | None:
    """Try a real Enlighten login; return an error code or None on success."""
    client = EnphaseClient(email, password, None, None, persist_cache=False)
    try:
        await hass.async_add_executor_job(client.ensure_authenticated)
    except AuthError as err:
        _LOGGER.warning("[Enphase] Credential validation failed: %s", err)
        return "invalid_auth"
    except requests.RequestException as err:
        _LOGGER.warning("[Enphase] Could not reach Enphase cloud: %s", err)
        return "cannot_connect"
    return None


class EnphaseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the configuration flow for Enphase Envoy Cloud Control."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry_id: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step for setup."""
        errors = {}

        if user_input is not None:
            if not user_input.get("email") or not user_input.get("password"):
                errors["base"] = "missing_credentials"
            else:
                await self.async_set_unique_id(user_input["email"])
                self._abort_if_unique_id_configured()
                error = await _async_validate_credentials(
                    self.hass, user_input["email"], user_input["password"]
                )
                if error:
                    errors["base"] = error
                else:
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

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle reauthentication when stored credentials stop working."""
        self._reauth_entry_id = self.context["entry_id"]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for an updated password and validate it."""
        entry = self.hass.config_entries.async_get_entry(self._reauth_entry_id)
        if entry is None:
            return self.async_abort(reason="reauth_failed")

        errors = {}
        email = entry.data.get("email", "")

        if user_input is not None:
            error = await _async_validate_credentials(
                self.hass, email, user_input["password"]
            )
            if error:
                errors["base"] = error
            else:
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, "password": user_input["password"]}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                _LOGGER.info("[Enphase] Reauthentication successful for %s", email)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required("password"): str}),
            errors=errors,
            description_placeholders={"email": email},
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
