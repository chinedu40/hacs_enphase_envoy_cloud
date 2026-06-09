"""Options flow: polling/notification settings and schedule add/delete forms."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import persistent_notification
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import DEFAULT_POLL_INTERVAL, DOMAIN
from .const import LOGGER as _LOGGER

__all__ = ["EnphaseOptionsFlowHandler"]

SERVICE_ADD_SCHEDULE = "add_schedule"
SERVICE_DELETE_SCHEDULE = "delete_schedule"


class EnphaseOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Enphase Envoy Cloud Control."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._last_error: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the Enphase options."""
        source = self.context.get("source")
        _LOGGER.debug(
            "[Enphase] Options flow init: source=%s user_input=%s",
            source,
            user_input is not None,
        )
        if source == "schedule_add_button":
            return await self.async_step_schedule_add(user_input)
        if source == "schedule_delete_button":
            return await self.async_step_schedule_delete(user_input)

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options_schema = vol.Schema(
            {
                vol.Optional(
                    "poll_interval",
                    default=self._config_entry.options.get(
                        "poll_interval", DEFAULT_POLL_INTERVAL
                    ),
                ): int,
                vol.Optional(
                    "notifications_enabled",
                    default=self._config_entry.options.get(
                        "notifications_enabled", True
                    ),
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            description_placeholders={"interval": DEFAULT_POLL_INTERVAL},
        )

    async def async_step_schedule_add(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Interactive form for adding a schedule via the options flow."""
        _LOGGER.debug(
            "[Enphase] Options flow schedule_add: user_input=%s",
            user_input is not None,
        )
        errors: dict[str, str] = {}
        if user_input is None:
            self._last_error = None

        if user_input is not None:
            if not user_input["days"]:
                errors["days"] = "required"

            if not errors:
                payload = {
                    "config_entry_id": self._config_entry.entry_id,
                    "schedule_type": user_input["schedule_type"],
                    "start_time": user_input["start_time"],
                    "end_time": user_input["end_time"],
                    "limit": user_input["limit"],
                    "days": user_input["days"],
                }
                try:
                    await self.hass.services.async_call(
                        DOMAIN,
                        SERVICE_ADD_SCHEDULE,
                        payload,
                        blocking=True,
                    )
                except HomeAssistantError as err:
                    self._last_error = str(err)
                    errors["base"] = "service_error"
                    persistent_notification.async_create(
                        self.hass,
                        f"⚠️ Failed to add schedule: {self._last_error}",
                        title="Enphase Envoy Cloud Control",
                        notification_id=f"{DOMAIN}_schedule_add_error",
                    )
                else:
                    return self.async_create_entry(
                        title="", data=dict(self._config_entry.options)
                    )

        schedule_type_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value="cfg", label="Charge from Grid (CFG)"),
                    selector.SelectOptionDict(value="dtg", label="Discharge to Grid (DTG)"),
                    selector.SelectOptionDict(value="rbd", label="Restrict Battery Discharge (RBD)"),
                ]
            )
        )
        time_selector = selector.TimeSelector()
        limit_selector = selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=100, step=1, unit_of_measurement="%", mode="box")
        )
        days_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                multiple=True,
                options=[
                    selector.SelectOptionDict(value="1", label="Monday"),
                    selector.SelectOptionDict(value="2", label="Tuesday"),
                    selector.SelectOptionDict(value="3", label="Wednesday"),
                    selector.SelectOptionDict(value="4", label="Thursday"),
                    selector.SelectOptionDict(value="5", label="Friday"),
                    selector.SelectOptionDict(value="6", label="Saturday"),
                    selector.SelectOptionDict(value="7", label="Sunday"),
                ],
            )
        )

        schema = vol.Schema(
            {
                vol.Required("schedule_type"): schedule_type_selector,
                vol.Required("start_time"): time_selector,
                vol.Required("end_time"): time_selector,
                vol.Required("limit", default=80): limit_selector,
                vol.Required("days"): days_selector,
            }
        )

        description_placeholders = {}
        if self._last_error:
            description_placeholders["error"] = self._last_error

        return self.async_show_form(
            step_id="schedule_add",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_schedule_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Interactive form for deleting a schedule via the options flow."""
        _LOGGER.debug(
            "[Enphase] Options flow schedule_delete: user_input=%s",
            user_input is not None,
        )
        errors: dict[str, str] = {}
        if user_input is None:
            self._last_error = None

        options = self._schedule_options()
        if not options:
            persistent_notification.async_create(
                self.hass,
                "⚠️ No schedules available to delete.",
                title="Enphase Envoy Cloud Control",
                notification_id=f"{DOMAIN}_schedule_delete_error",
            )
            return self.async_abort(reason="no_schedules")

        if user_input is not None:
            if not user_input.get("confirm"):
                errors["confirm"] = "required"
            else:
                payload = {
                    "config_entry_id": self._config_entry.entry_id,
                    "schedule_ids": user_input["schedule_ids"],
                    "confirm": True,
                }
                try:
                    await self.hass.services.async_call(
                        DOMAIN,
                        SERVICE_DELETE_SCHEDULE,
                        payload,
                        blocking=True,
                    )
                except HomeAssistantError as err:
                    self._last_error = str(err)
                    errors["base"] = "service_error"
                    persistent_notification.async_create(
                        self.hass,
                        f"⚠️ Failed to delete schedule: {self._last_error}",
                        title="Enphase Envoy Cloud Control",
                        notification_id=f"{DOMAIN}_schedule_delete_error",
                    )
                else:
                    return self.async_create_entry(
                        title="", data=dict(self._config_entry.options)
                    )

        schedule_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(options=options, multiple=True)
        )
        confirm_selector = selector.BooleanSelector()

        schema = vol.Schema(
            {
                vol.Required("schedule_ids"): schedule_selector,
                vol.Required("confirm", default=False): confirm_selector,
            }
        )

        description_placeholders = {}
        if self._last_error:
            description_placeholders["error"] = self._last_error

        return self.async_show_form(
            step_id="schedule_delete",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    def _schedule_options(self) -> list[selector.SelectOptionDict]:
        """Build schedule options for the delete form."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        coordinator = entry_data.get("coordinator") if isinstance(entry_data, dict) else None
        if not coordinator or not getattr(coordinator, "data", None):
            return []

        options: list[selector.SelectOptionDict] = []
        for mode in ("cfg", "dtg", "rbd"):
            schedules = coordinator.data.get("data", {}).get(f"{mode}Control", {})
            sched_list: list | None = None
            if isinstance(schedules, dict):
                maybe = schedules.get("schedules")
                if isinstance(maybe, list):
                    sched_list = maybe

            if sched_list is None:
                fallback = coordinator.data.get("schedules", {})
                if isinstance(fallback, dict):
                    candidate = fallback.get(mode)
                    if isinstance(candidate, dict) and isinstance(
                        candidate.get("details"), list
                    ):
                        sched_list = candidate["details"]
                    elif isinstance(candidate, list):
                        sched_list = candidate
                    else:
                        inner = fallback.get("data", {}).get(mode)
                        if isinstance(inner, dict) and isinstance(
                            inner.get("details"), list
                        ):
                            sched_list = inner["details"]
                        elif isinstance(inner, list):
                            sched_list = inner

            if not isinstance(sched_list, list):
                continue
            for sched in sched_list:
                schedule_id = sched.get("scheduleId")
                if schedule_id is None:
                    continue
                label = f"#{schedule_id} – {mode.upper()} {sched.get('startTime', '??')}–{sched.get('endTime', '??')}"
                options.append(
                    selector.SelectOptionDict(value=str(schedule_id), label=label)
                )
        return options
