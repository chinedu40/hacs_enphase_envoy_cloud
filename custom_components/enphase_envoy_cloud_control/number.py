"""Number entities for schedule editing."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .device import schedule_editor_device_info
from .editor import get_entry_data

__all__ = ["EnphaseScheduleLimit", "async_setup_entry"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up schedule number entities."""
    async_add_entities(
        [
            EnphaseScheduleLimit(entry.entry_id, False),
            EnphaseScheduleLimit(entry.entry_id, True),
        ],
        True,
    )


class EnphaseScheduleLimit(NumberEntity):
    """Number entity for schedule limit."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"

    def __init__(self, entry_id: str, is_new: bool) -> None:
        self.entry_id = entry_id
        self.is_new = is_new
        schedule_label = "New Schedule" if is_new else "Schedule"
        self._attr_name = f"Enphase {schedule_label} Limit"
        suffix = "new" if is_new else "edit"
        self._attr_unique_id = f"{entry_id}_{suffix}_limit"

    @property
    def native_value(self) -> float | None:
        entry_data = get_entry_data(self.hass, self.entry_id)
        editor_key = "new_editor" if self.is_new else "editor"
        return float(entry_data[editor_key].get("limit", 0))

    async def async_set_native_value(self, value: float) -> None:
        entry_data = get_entry_data(self.hass, self.entry_id)
        editor_key = "new_editor" if self.is_new else "editor"
        entry_data[editor_key]["limit"] = int(value)
        self.async_write_ha_state()

    @property
    def device_info(self) -> dict[str, Any]:
        return schedule_editor_device_info(self.entry_id)
