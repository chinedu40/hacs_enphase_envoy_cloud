"""Select entities for schedule editing."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EnphaseCoordinator
from .device import schedule_editor_device_info
from .editor import (
    editor_days_from_list,
    get_coordinator,
    get_entry_data,
    normalize_schedules,
)

__all__ = ["EnphaseNewScheduleTypeSelect", "EnphaseScheduleSelect", "async_setup_entry"]

_LOGGER = logging.getLogger(__name__)

DAY_LABELS = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up schedule select entities."""
    coordinator = get_coordinator(hass, entry.entry_id)
    async_add_entities(
        [
            EnphaseScheduleSelect(coordinator, entry.entry_id),
            EnphaseNewScheduleTypeSelect(entry.entry_id),
        ],
        True,
    )


class EnphaseScheduleSelect(SelectEntity):
    """Select the active schedule to edit.

    Options are human-readable labels (type, time range, days, limit); the
    underlying schedule UUID is kept in the editor state and exposed via the
    ``schedule_id`` attribute.
    """

    _attr_name = "Enphase Schedule Selected"
    _attr_icon = "mdi:calendar-edit"

    def __init__(self, coordinator: EnphaseCoordinator, entry_id: str) -> None:
        self.coordinator = coordinator
        self.entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_schedule_selected"

    @staticmethod
    def _label_for(schedule: dict[str, Any]) -> str:
        """Build a readable label like 'CFG 02:00–06:00 · Mon, Tue · 80%'."""
        days = schedule.get("days") or []
        day_str = ", ".join(DAY_LABELS[d] for d in days if d in DAY_LABELS) or "no days"
        return (
            f"{str(schedule.get('type', '?')).upper()} "
            f"{schedule.get('start', '??')}–{schedule.get('end', '??')} "
            f"· {day_str} · {schedule.get('limit', 0)}%"
        )

    def _labelled_schedules(self) -> list[tuple[str, dict[str, Any]]]:
        """Return (label, schedule) pairs with duplicate labels disambiguated."""
        pairs: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        for schedule in normalize_schedules(self.coordinator):
            label = self._label_for(schedule)
            if label in seen:
                label = f"{label} · #{str(schedule['id'])[:8]}"
            seen.add(label)
            pairs.append((label, schedule))
        return pairs

    @property
    def options(self) -> list[str]:
        return [label for label, _ in self._labelled_schedules()]

    @property
    def current_option(self) -> str | None:
        editor = get_entry_data(self.hass, self.entry_id)["editor"]
        selected_id = editor.get("selected_schedule_id")
        if not selected_id:
            return None
        return next(
            (
                label
                for label, schedule in self._labelled_schedules()
                if schedule["id"] == selected_id
            ),
            None,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        editor = get_entry_data(self.hass, self.entry_id)["editor"]
        return {"schedule_id": editor.get("selected_schedule_id")}

    async def async_select_option(self, option: str) -> None:
        match: dict[str, Any] | None = None
        for label, schedule in self._labelled_schedules():
            # Match by display label, but also accept a raw schedule ID so
            # existing automations/scripts that pass UUIDs keep working.
            if option in (label, schedule["id"]):
                match = schedule
                break
        if match is None:
            _LOGGER.warning("[Enphase] Unknown schedule selected: %s", option)
            return
        editor = get_entry_data(self.hass, self.entry_id)["editor"]
        editor["selected_schedule_id"] = match["id"]
        editor["schedule_type"] = match.get("type", "cfg")
        editor["start_time"] = match.get("start", "00:00")
        editor["end_time"] = match.get("end", "00:00")
        editor["limit"] = int(match.get("limit", 0))
        editor["days"] = editor_days_from_list(match.get("days", []))
        self.async_write_ha_state()

    @property
    def device_info(self) -> dict[str, Any]:
        return schedule_editor_device_info(self.entry_id)


class EnphaseNewScheduleTypeSelect(SelectEntity):
    """Select schedule type for a new schedule."""

    _attr_name = "Enphase New Schedule Type"
    _attr_icon = "mdi:calendar-plus"

    def __init__(self, entry_id: str) -> None:
        self.entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_new_schedule_type"
        self._attr_options = ["cfg", "dtg", "rbd"]

    @property
    def options(self) -> list[str]:
        return list(self._attr_options)

    @property
    def current_option(self) -> str | None:
        entry_data = get_entry_data(self.hass, self.entry_id)
        return entry_data["new_editor"].get("schedule_type", "cfg")

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            _LOGGER.warning("[Enphase] Invalid schedule type selected: %s", option)
            return
        entry_data = get_entry_data(self.hass, self.entry_id)
        entry_data["new_editor"]["schedule_type"] = option
        self.async_write_ha_state()

    @property
    def device_info(self) -> dict[str, Any]:
        return schedule_editor_device_info(self.entry_id)
