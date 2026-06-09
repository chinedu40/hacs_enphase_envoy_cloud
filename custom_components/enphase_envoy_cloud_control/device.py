"""Device helpers for Enphase Envoy Cloud Control."""

from __future__ import annotations

from .const import DEVICE_KIND_BATTERY, DEVICE_KIND_SCHEDULE_EDITOR, DOMAIN

__all__ = ["battery_device_info", "schedule_editor_device_info"]


def battery_device_info(entry_id: str) -> dict:
    """Return device info for the main battery device."""
    return {
        "identifiers": {(DOMAIN, entry_id)},
        "name": "Enphase Battery",
        "manufacturer": "Enphase",
        "model": "IQ Battery",
    }


def schedule_editor_device_info(entry_id: str) -> dict:
    """Return device info for the schedule editor device."""
    return {
        "identifiers": {(DOMAIN, entry_id, DEVICE_KIND_SCHEDULE_EDITOR)},
        "name": "Enphase Schedule Editor",
        "manufacturer": "Enphase",
        "model": "Schedule Editor",
        "via_device": (DOMAIN, entry_id),
    }
