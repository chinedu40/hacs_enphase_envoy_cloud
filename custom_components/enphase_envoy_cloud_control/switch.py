"""Switches for Enphase battery control modes and schedule editor day flags."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import EnphaseCoordinator
from .device import battery_device_info, schedule_editor_device_info
from .editor import DAY_ORDER, get_coordinator, get_entry_data

__all__ = ["EnphaseEditorDaySwitch", "EnphaseModeSwitch", "async_setup_entry"]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Enphase mode and editor day switches from a config entry."""
    coordinator = get_coordinator(hass, entry.entry_id)
    data = coordinator.data.get("data", {}) if coordinator.data else {}
    switches = []

    for key in ["cfgControl", "dtgControl", "rbdControl"]:
        if key in data:
            switches.append(EnphaseModeSwitch(coordinator, key))

    for key, _ in DAY_ORDER:
        switches.append(
            EnphaseEditorDaySwitch(entry.entry_id, key, is_new=False)
        )
        switches.append(
            EnphaseEditorDaySwitch(entry.entry_id, key, is_new=True)
        )

    async_add_entities(switches, True)


class EnphaseModeSwitch(CoordinatorEntity, SwitchEntity):
    """Switch representing an Enphase battery control mode."""

    def __init__(self, coordinator: EnphaseCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self.key = key
        self.short_mode = key.replace("Control", "")
        self._attr_name = f"Enphase {self.short_mode.upper()} Mode"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{self.short_mode.lower()}"

    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool:
        """Return True if the control mode is enabled."""
        try:
            return self.coordinator.data["data"][self.key]["enabled"]
        except (KeyError, TypeError):
            return False

    async def async_turn_on(self) -> None:
        """Enable the mode in Enphase Cloud."""
        _LOGGER.info("[Enphase] Turning ON %s", self.short_mode)
        await self.coordinator.hass.async_add_executor_job(
            self.coordinator.client.set_mode, self.key, True
        )
        # Wait 5 s for cloud propagation, then force refresh
        await asyncio.sleep(5)
        await self.coordinator.async_force_refresh()

    async def async_turn_off(self) -> None:
        """Disable the mode in Enphase Cloud."""
        _LOGGER.info("[Enphase] Turning OFF %s", self.short_mode)
        await self.coordinator.hass.async_add_executor_job(
            self.coordinator.client.set_mode, self.key, False
        )
        await asyncio.sleep(5)
        await self.coordinator.async_force_refresh()

    # ------------------------------------------------------------------

    @property
    def device_info(self) -> dict[str, Any]:
        """Attach to Enphase Envoy Cloud device."""
        return battery_device_info(self.coordinator.entry.entry_id)


class EnphaseEditorDaySwitch(SwitchEntity):
    """Switch representing a weekday toggle for schedule editing."""

    def __init__(self, entry_id: str, day_key: str, is_new: bool) -> None:
        self.entry_id = entry_id
        self.day_key = day_key
        self.is_new = is_new
        schedule_label = "New Schedule" if is_new else "Schedule"
        self._attr_name = f"Enphase {schedule_label} {day_key.title()}"
        suffix = "new" if is_new else "edit"
        self._attr_unique_id = f"{entry_id}_{suffix}_{day_key}"

    @property
    def is_on(self) -> bool:
        entry_data = get_entry_data(self.hass, self.entry_id)
        editor_key = "new_editor" if self.is_new else "editor"
        return bool(entry_data[editor_key]["days"].get(self.day_key))

    async def async_turn_on(self) -> None:
        entry_data = get_entry_data(self.hass, self.entry_id)
        editor_key = "new_editor" if self.is_new else "editor"
        entry_data[editor_key]["days"][self.day_key] = True
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        entry_data = get_entry_data(self.hass, self.entry_id)
        editor_key = "new_editor" if self.is_new else "editor"
        entry_data[editor_key]["days"][self.day_key] = False
        self.async_write_ha_state()

    @property
    def device_info(self) -> dict[str, Any]:
        return schedule_editor_device_info(self.entry_id)
