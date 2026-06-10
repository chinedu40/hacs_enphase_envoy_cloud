"""Diagnostics support for Enphase Envoy Cloud Control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

__all__ = ["async_get_config_entry_diagnostics"]

# Anything identifying or secret is redacted from diagnostics downloads.
TO_REDACT = {
    "email",
    "password",
    "user_id",
    "battery_id",
    "userId",
    "siteId",
    "scheduleId",
    "jwt",
    "xsrf",
    "cookies",
    "e-auth-token",
    "x-xsrf-token",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = entry_data.get("coordinator") if isinstance(entry_data, dict) else None

    diagnostics: dict[str, Any] = {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
    }

    if coordinator is not None:
        diagnostics["coordinator"] = {
            "last_update_success": coordinator.last_update_success,
            "last_successful_poll": str(coordinator.last_successful_poll),
            "update_interval": str(coordinator.update_interval),
            "data": async_redact_data(coordinator.data or {}, TO_REDACT),
        }
        diagnostics["editor_state"] = {
            "editor": async_redact_data(
                dict(entry_data.get("editor") or {}), TO_REDACT
            ),
            "new_editor": dict(entry_data.get("new_editor") or {}),
        }

    return diagnostics
