"""Buttons for cloud refresh and schedule add/save/delete actions."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EnphaseCoordinator
from .device import battery_device_info, schedule_editor_device_info
from .editor import days_list_from_editor, get_coordinator, get_entry_data

__all__ = [
    "EnphaseAddScheduleButton",
    "EnphaseDeleteScheduleButton",
    "EnphaseForceCloudRefreshButton",
    "EnphaseNewScheduleAddButton",
    "EnphaseScheduleDeleteButton",
    "EnphaseScheduleSaveButton",
    "async_setup_entry",
]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Enphase Force Cloud Refresh button."""
    coordinator = get_coordinator(hass, entry.entry_id)
    async_add_entities(
        [
            EnphaseForceCloudRefreshButton(coordinator),
            EnphaseAddScheduleButton(coordinator),
            EnphaseDeleteScheduleButton(coordinator),
            EnphaseScheduleSaveButton(entry.entry_id),
            EnphaseScheduleDeleteButton(entry.entry_id),
            EnphaseNewScheduleAddButton(entry.entry_id),
        ],
        True,
    )

class EnphaseForceCloudRefreshButton(CoordinatorEntity, ButtonEntity):
    """Button to manually force data refresh from the cloud."""

    def __init__(self, coordinator: EnphaseCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "Force Cloud Refresh"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_force_refresh"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return True  # Always available

    async def async_press(self) -> None:
        """Handle button press."""
        _LOGGER.info("[Enphase] Force Cloud Refresh button pressed.")
        try:
            await self.coordinator.async_force_refresh()
            _LOGGER.info("[Enphase] Data refresh completed successfully.")
        except Exception as e:
            _LOGGER.error("[Enphase] Data refresh failed: %s", e)

    @property
    def device_info(self) -> dict[str, Any]:
        """Attach this button to the Enphase device."""
        return battery_device_info(self.coordinator.entry.entry_id)


class EnphaseAddScheduleButton(CoordinatorEntity, ButtonEntity):
    """Button that opens the schedule creation dialog."""

    _attr_name = "Add Schedule"
    _attr_icon = "mdi:calendar-plus"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: EnphaseCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_add_schedule"

    async def async_press(self) -> None:
        """Launch the options flow for adding a schedule."""
        _LOGGER.debug("[Enphase] Add Schedule button pressed.")
        try:
            flow = await self.coordinator.hass.config_entries.options.async_create_flow(
                self.coordinator.entry.entry_id,
                context={"source": "schedule_add_button"},
            )
        except Exception:
            _LOGGER.exception("[Enphase] Failed to start add schedule options flow")
            return
        flow_id = getattr(flow, "flow_id", None)
        _LOGGER.debug(
            "[Enphase] Add schedule options flow created: handler=%s type=%s flow_id=%s",
            flow.handler,
            type(flow).__name__,
            flow_id,
        )
        if "persistent_notification" in self.coordinator.hass.config.components:
            persistent_notification.async_create(
                self.coordinator.hass,
                "✅ Add Schedule flow created. Open the integration options UI to continue.",
                title="Enphase Envoy Cloud Control",
                notification_id=f"{DOMAIN}_schedule_add_flow",
            )

    @property
    def device_info(self) -> dict[str, Any]:
        return battery_device_info(self.coordinator.entry.entry_id)


class EnphaseDeleteScheduleButton(CoordinatorEntity, ButtonEntity):
    """Button that opens the schedule deletion dialog."""

    _attr_name = "Delete Schedule"
    _attr_icon = "mdi:calendar-remove"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: EnphaseCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_delete_schedule"

    async def async_press(self) -> None:
        """Launch the options flow for deleting a schedule."""
        _LOGGER.debug("[Enphase] Delete Schedule button pressed.")
        try:
            flow = await self.coordinator.hass.config_entries.options.async_create_flow(
                self.coordinator.entry.entry_id,
                context={"source": "schedule_delete_button"},
            )
        except Exception:
            _LOGGER.exception("[Enphase] Failed to start delete schedule options flow")
            return
        flow_id = getattr(flow, "flow_id", None)
        _LOGGER.debug(
            "[Enphase] Delete schedule options flow created: handler=%s type=%s flow_id=%s",
            flow.handler,
            type(flow).__name__,
            flow_id,
        )
        if "persistent_notification" in self.coordinator.hass.config.components:
            persistent_notification.async_create(
                self.coordinator.hass,
                "✅ Delete Schedule flow created. Open the integration options UI to continue.",
                title="Enphase Envoy Cloud Control",
                notification_id=f"{DOMAIN}_schedule_delete_flow",
            )

    @property
    def device_info(self) -> dict[str, Any]:
        return battery_device_info(self.coordinator.entry.entry_id)


class EnphaseScheduleSaveButton(ButtonEntity):
    """Button to save edits to an existing schedule."""

    _attr_name = "Schedule Save"
    _attr_icon = "mdi:content-save"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry_id: str) -> None:
        self.entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_schedule_save"

    async def async_press(self) -> None:
        entry_data = get_entry_data(self.hass, self.entry_id)
        editor = entry_data["editor"]
        schedule_id = editor.get("selected_schedule_id")
        if not schedule_id:
            _LOGGER.warning("[Enphase] No schedule selected for update.")
            return
        data = {
            "config_entry_id": self.entry_id,
            "schedule_id": schedule_id,
            "schedule_type": editor.get("schedule_type", "cfg"),
            "start_time": editor.get("start_time", "00:00"),
            "end_time": editor.get("end_time", "00:00"),
            "limit": int(editor.get("limit", 0)),
            "days": days_list_from_editor(editor.get("days", {})),
            "confirm": True,
        }
        await self.hass.services.async_call(
            DOMAIN,
            "update_schedule",
            data,
            blocking=True,
        )

    @property
    def device_info(self) -> dict[str, Any]:
        return schedule_editor_device_info(self.entry_id)


class EnphaseScheduleDeleteButton(ButtonEntity):
    """Button to delete the selected schedule."""

    _attr_name = "Schedule Delete"
    _attr_icon = "mdi:calendar-remove"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry_id: str) -> None:
        self.entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_schedule_delete"

    async def async_press(self) -> None:
        entry_data = get_entry_data(self.hass, self.entry_id)
        schedule_id = entry_data["editor"].get("selected_schedule_id")
        if not schedule_id:
            _LOGGER.warning("[Enphase] No schedule selected for deletion.")
            return
        await self.hass.services.async_call(
            DOMAIN,
            "delete_schedule",
            {
                "config_entry_id": self.entry_id,
                "schedule_id": schedule_id,
                "confirm": True,
            },
            blocking=True,
        )

    @property
    def device_info(self) -> dict[str, Any]:
        return schedule_editor_device_info(self.entry_id)


class EnphaseNewScheduleAddButton(ButtonEntity):
    """Button to add a new schedule from editor state."""

    _attr_name = "New Schedule Add"
    _attr_icon = "mdi:calendar-plus"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry_id: str) -> None:
        self.entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_new_schedule_add"

    async def async_press(self) -> None:
        entry_data = get_entry_data(self.hass, self.entry_id)
        editor = entry_data["new_editor"]
        data = {
            "config_entry_id": self.entry_id,
            "schedule_type": editor.get("schedule_type", "cfg"),
            "start_time": editor.get("start_time", "00:00"),
            "end_time": editor.get("end_time", "00:00"),
            "limit": int(editor.get("limit", 0)),
            "days": days_list_from_editor(editor.get("days", {})),
        }
        await self.hass.services.async_call(
            DOMAIN,
            "add_schedule",
            data,
            blocking=True,
        )

    @property
    def device_info(self) -> dict[str, Any]:
        return schedule_editor_device_info(self.entry_id)
