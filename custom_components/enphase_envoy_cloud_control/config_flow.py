from __future__ import annotations
import logging
import re
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from .const import DOMAIN
from .options_flow import EnphaseOptionsFlowHandler

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_LOGGER = logging.getLogger(__name__)


class EnphaseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the configuration flow for Enphase Envoy Cloud Control."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step for setup."""
        errors = {}

        if user_input is not None:
            email = (user_input.get("email") or "").strip()
            password = user_input.get("password") or ""

            if not email or not password:
                errors["base"] = "missing_credentials"
            elif not _EMAIL_RE.match(email):
                errors["email"] = "invalid_email"
            else:
                user_input = {**user_input, "email": email}
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
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        _LOGGER.debug(
            "[Enphase] Creating options flow handler for entry_id=%s",
            config_entry.entry_id,
        )
        return EnphaseOptionsFlowHandler(config_entry)
