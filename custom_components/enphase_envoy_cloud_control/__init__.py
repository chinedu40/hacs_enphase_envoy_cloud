"""Enphase Envoy Cloud Control integration setup."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.event import async_call_later

from .const import DEFAULT_POLL_INTERVAL, DOMAIN
from .coordinator import EnphaseCoordinator
from .editor import _collect_schedules, default_editor_state, default_new_editor_state
from .enphase_client import AuthError

__all__ = ["async_setup_entry", "async_unload_entry"]

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "switch", "button", "select", "time", "number"]
SERVICES_REGISTERED = "_services_registered"

SERVICE_FORCE_REFRESH = "force_refresh"
SERVICE_ADD_SCHEDULE = "add_schedule"
SERVICE_UPDATE_SCHEDULE = "update_schedule"
SERVICE_DELETE_SCHEDULE = "delete_schedule"
SERVICE_VALIDATE_SCHEDULE = "validate_schedule"

FORCE_REFRESH_SCHEMA = vol.Schema({vol.Optional("config_entry_id"): cv.string})

ADD_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("schedule_type"): vol.All(cv.string, vol.Lower, vol.In(["cfg", "dtg", "rbd"])),
        vol.Required("start_time"): cv.time,
        vol.Required("end_time"): cv.time,
        vol.Required("limit"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Required("days"): vol.All(
            cv.ensure_list,
            [vol.All(vol.Coerce(int), vol.Range(min=1, max=7))],
        ),
    }
)

UPDATE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("schedule_id"): cv.string,
        vol.Required("schedule_type"): vol.All(cv.string, vol.Lower, vol.In(["cfg", "dtg", "rbd"])),
        vol.Required("start_time"): cv.time,
        vol.Required("end_time"): cv.time,
        vol.Required("limit"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Required("days"): vol.All(
            cv.ensure_list,
            [vol.All(vol.Coerce(int), vol.Range(min=1, max=7))],
        ),
        vol.Required("confirm"): cv.boolean,
    }
)

_SCHEDULE_ID_REGEX = r"^[0-9a-fA-F-]{6,}$"


def _normalize_schedule_ids(raw: Any) -> list[str]:
    schedule_ids: list[str] = []
    if raw is None:
        return schedule_ids

    if isinstance(raw, (list, tuple, set)):
        candidates = [str(val) for val in raw]
    else:
        candidates = [str(raw)]

    for candidate in candidates:
        if not candidate:
            continue
        extracted_ids = re.findall(r"[0-9a-fA-F-]{6,}", candidate)
        if extracted_ids:
            schedule_ids.extend(extracted_ids)
            continue
        schedule_ids.extend(
            [part for part in re.split(r"[,\s]+", candidate) if part]
        )

    schedule_ids = [sched_id.strip().strip("'\"") for sched_id in schedule_ids]
    return [sched_id for sched_id in schedule_ids if sched_id]

DELETE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Optional("schedule_id"): cv.string,
        vol.Optional("schedule_ids"): cv.ensure_list,
        vol.Required("confirm"): cv.boolean,
    }
)

VALIDATE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("schedule_type"): vol.All(cv.string, vol.Lower, vol.In(["cfg", "dtg", "rbd"])),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Enphase Envoy Cloud Control from a config entry."""
    _LOGGER.info("Setting up Enphase Envoy Cloud Control integration.")

    coordinator = EnphaseCoordinator(hass, entry)
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[entry.entry_id] = {
        "coordinator": coordinator,
        "editor": default_editor_state(),
        "new_editor": default_new_editor_state(),
    }

    if not domain_data.get(SERVICES_REGISTERED):
        _register_services(hass)
        domain_data[SERVICES_REGISTERED] = True

    entry.async_on_unload(entry.add_update_listener(_async_handle_options_update))

    try:
        await coordinator.async_initialize_auth()
    except AuthError as err:
        raise ConfigEntryNotReady(f"Enphase authentication failed: {err}") from err
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("[Enphase] Forwarded platforms: %s", PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Enphase integration when entry is removed."""
    _LOGGER.info("Unloading Enphase Envoy Cloud Control integration.")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data = hass.data.get(DOMAIN, {})
        domain_data.pop(entry.entry_id, None)
        _LOGGER.debug("[Enphase] Integration data cleared from memory.")

        # Remove services when the final entry is unloaded
        if not _coordinators(domain_data):
            for service in (
                SERVICE_FORCE_REFRESH,
                SERVICE_ADD_SCHEDULE,
                SERVICE_UPDATE_SCHEDULE,
                SERVICE_DELETE_SCHEDULE,
                SERVICE_VALIDATE_SCHEDULE,
            ):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
            domain_data.pop(SERVICES_REGISTERED, None)

    return unload_ok


async def _async_handle_options_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply updated options (e.g. polling interval) to the coordinator."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    coordinator = entry_data.get("coordinator") if isinstance(entry_data, dict) else None
    if not coordinator:
        _LOGGER.debug("[Enphase] Options updated but coordinator not initialised yet.")
        return

    poll_interval = entry.options.get("poll_interval", DEFAULT_POLL_INTERVAL)
    try:
        poll_interval = int(poll_interval)
    except (TypeError, ValueError):
        _LOGGER.warning(
            "[Enphase] Invalid poll interval '%s' in options; falling back to default.",
            poll_interval,
        )
        poll_interval = DEFAULT_POLL_INTERVAL

    coordinator.update_interval = timedelta(seconds=poll_interval)
    _LOGGER.info("[Enphase] Polling interval updated to %ss via options.", poll_interval)

    # Trigger a refresh so the new interval is respected immediately.
    await coordinator.async_request_refresh()


def _coordinators(domain_data: dict[str, Any]) -> dict[str, EnphaseCoordinator]:
    """Return mapping of active coordinators only."""
    return {
        entry_id: data["coordinator"]
        for entry_id, data in domain_data.items()
        if isinstance(data, dict) and isinstance(data.get("coordinator"), EnphaseCoordinator)
    }


def _get_coordinator_from_call(hass: HomeAssistant, call: ServiceCall) -> EnphaseCoordinator:
    """Resolve which coordinator should handle a service call."""
    domain_data = hass.data.get(DOMAIN, {})
    coordinators = _coordinators(domain_data)

    config_entry_id = call.data.get("config_entry_id")
    if config_entry_id and config_entry_id in coordinators:
        return coordinators[config_entry_id]

    device_ids = call.data.get("device_id")
    if device_ids:
        device_reg = dr.async_get(hass)
        for device_id in cv.ensure_list(device_ids):
            device = device_reg.async_get(device_id)
            if not device:
                continue
            for domain, entry_id in device.identifiers:
                if domain == DOMAIN and entry_id in coordinators:
                    return coordinators[entry_id]

    if len(coordinators) == 1:
        return next(iter(coordinators.values()))

    raise HomeAssistantError(
        "Multiple Enphase entries detected – specify config_entry_id or target device."
    )


def _register_services(hass: HomeAssistant) -> None:
    """Register Home Assistant services for schedule management."""

    async def async_force_refresh_service(call: ServiceCall) -> None:
        coordinator = _get_coordinator_from_call(hass, call)
        _LOGGER.debug("[Enphase] Manual force refresh service called.")
        try:
            await coordinator.async_force_refresh()
            _LOGGER.info("[Enphase] Cloud data refreshed via service.")
        except Exception as exc:
            _LOGGER.error("[Enphase] Manual refresh failed: %s", exc)
            raise HomeAssistantError(str(exc)) from exc

    async def async_add_schedule_service(call: ServiceCall) -> None:
        coordinator = _get_coordinator_from_call(hass, call)
        data = call.data

        schedule_type: str = str(data["schedule_type"]).lower()
        start_time = data["start_time"]
        end_time = data["end_time"]
        limit = int(data["limit"])
        days = sorted({int(day) for day in cv.ensure_list(data["days"])})

        # Input validation lives here (not in the voluptuous schema) so the
        # user gets a clear, actionable error message in the UI.
        if not days:
            raise HomeAssistantError("Select at least one day for the schedule.")

        start_str = start_time.strftime("%H:%M")
        end_str = end_time.strftime("%H:%M")
        if start_str == end_str:
            raise HomeAssistantError("Start time and end time must differ for a schedule.")

        timezone = hass.config.time_zone or "UTC"

        try:
            validation = await hass.async_add_executor_job(
                coordinator.client.validate_schedule,
                schedule_type,
                schedule_type == "cfg",
            )
        except Exception as exc:
            _LOGGER.error("[Enphase] Schedule validation failed: %s", exc)
            raise HomeAssistantError(f"Validation failed: {exc}") from exc

        if isinstance(validation, dict) and not validation.get("valid", True):
            raise HomeAssistantError(
                validation.get("message", "Schedule rejected by validation endpoint.")
            )

        try:
            await hass.async_add_executor_job(
                coordinator.client.add_schedule,
                schedule_type,
                start_str,
                end_str,
                limit,
                days,
                timezone,
            )
        except Exception as exc:
            _LOGGER.error("[Enphase] Failed to add schedule: %s", exc)
            raise HomeAssistantError(f"Failed to add schedule: {exc}") from exc

        await asyncio.sleep(2)

        try:
            await hass.async_add_executor_job(
                coordinator.client.set_mode,
                schedule_type,
                True,
                start_str if schedule_type == "dtg" else None,
                end_str if schedule_type == "dtg" else None,
            )
        except Exception as exc:
            _LOGGER.error(
                "[Enphase] Schedule added but failed to apply %s settings: %s",
                schedule_type,
                exc,
            )
            raise HomeAssistantError(
                f"Schedule added but failed to apply {schedule_type.upper()} settings: {exc}"
            ) from exc

        if "persistent_notification" in hass.config.components:
            # Check if notifications are enabled in options
            notifications_enabled = coordinator.entry.options.get(
                "notifications_enabled", True
            )
            if notifications_enabled:
                persistent_notification.async_create(
                    hass,
                (
                    "✅ Schedule added successfully for "
                    f"{schedule_type.upper()} ({start_str}–{end_str})."
                ),
                title="Enphase Envoy Cloud Control",
                notification_id=f"{DOMAIN}_schedule_add",
                )

        async_call_later(
            hass,
            5,
            lambda _: _schedule_post_action_refresh(hass, coordinator),
        )

    async def async_update_schedule_service(call: ServiceCall) -> None:
        coordinator = _get_coordinator_from_call(hass, call)
        data = call.data

        if not data.get("confirm"):
            raise HomeAssistantError("Confirmation required to update a schedule.")

        schedule_id = str(data["schedule_id"])
        schedule_type: str = str(data["schedule_type"]).lower()
        start_str = data["start_time"].strftime("%H:%M")
        end_str = data["end_time"].strftime("%H:%M")
        limit = int(data["limit"])
        days = sorted({int(day) for day in cv.ensure_list(data["days"])})

        if start_str == end_str:
            raise HomeAssistantError("Start time and end time must differ for a schedule.")
        if not days:
            raise HomeAssistantError("Select at least one day for the schedule.")

        timezone = hass.config.time_zone or "UTC"

        try:
            validation = await hass.async_add_executor_job(
                coordinator.client.validate_schedule,
                schedule_type,
                schedule_type == "cfg",
            )
        except Exception as exc:
            _LOGGER.error("[Enphase] Schedule validation failed: %s", exc)
            raise HomeAssistantError(f"Validation failed: {exc}") from exc

        if isinstance(validation, dict) and not validation.get("valid", True):
            raise HomeAssistantError(
                validation.get("message", "Schedule rejected by validation endpoint.")
            )

        try:
            await hass.async_add_executor_job(
                coordinator.client.delete_schedule,
                schedule_id,
            )
        except Exception as exc:
            _LOGGER.error("[Enphase] Failed to delete schedule %s: %s", schedule_id, exc)
            raise HomeAssistantError(
                f"Failed to delete schedule {schedule_id}: {exc}"
            ) from exc

        try:
            await hass.async_add_executor_job(
                coordinator.client.add_schedule,
                schedule_type,
                start_str,
                end_str,
                limit,
                days,
                timezone,
            )
        except Exception as exc:
            _LOGGER.error("[Enphase] Failed to add schedule: %s", exc)
            raise HomeAssistantError(f"Failed to add schedule: {exc}") from exc

        await asyncio.sleep(2)

        try:
            await hass.async_add_executor_job(
                coordinator.client.set_mode,
                schedule_type,
                True,
                start_str if schedule_type == "dtg" else None,
                end_str if schedule_type == "dtg" else None,
            )
        except Exception as exc:
            _LOGGER.error(
                "[Enphase] Schedule updated but failed to apply %s settings: %s",
                schedule_type,
                exc,
            )
            raise HomeAssistantError(
                f"Schedule updated but failed to apply {schedule_type.upper()} settings: {exc}"
            ) from exc

        async_call_later(
            hass,
            5,
            lambda _: _schedule_post_action_refresh(hass, coordinator),
        )

    async def async_delete_schedule_service(call: ServiceCall) -> None:
        coordinator = _get_coordinator_from_call(hass, call)
        if call.data.get("schedule_ids"):
            schedule_ids = _normalize_schedule_ids(call.data["schedule_ids"])
        elif call.data.get("schedule_id"):
            schedule_ids = _normalize_schedule_ids(call.data["schedule_id"])
        else:
            raise HomeAssistantError("Provide schedule_id or schedule_ids to delete.")
        if not schedule_ids:
            raise HomeAssistantError("Provide at least one schedule ID to delete.")

        schedule_modes: dict[str, str] = {}
        for mode in ("cfg", "dtg", "rbd"):
            for sched in _collect_schedules(coordinator, mode):
                schedule_id = sched.get("scheduleId")
                if schedule_id is None:
                    continue
                schedule_modes[str(schedule_id)] = mode

        schedule_id_pattern = re.compile(_SCHEDULE_ID_REGEX)
        invalid_ids = [sched_id for sched_id in schedule_ids if not schedule_id_pattern.match(sched_id)]
        if invalid_ids:
            raise HomeAssistantError(
                f"Invalid schedule ID(s): {', '.join(invalid_ids)}"
            )
        confirm = call.data.get("confirm")
        if not confirm:
            raise HomeAssistantError("Confirmation required to delete a schedule.")

        known_ids = {
            str(sched.get("scheduleId"))
            for sensor in ("cfg", "dtg", "rbd")
            for sched in _collect_schedules(coordinator, sensor)
            if sched.get("scheduleId") is not None
        }

        if known_ids:
            unknown_ids = [sched_id for sched_id in schedule_ids if sched_id not in known_ids]
            if unknown_ids:
                raise HomeAssistantError(
                    f"Schedule ID(s) not found in current data: {', '.join(unknown_ids)}"
                )

        for schedule_id in schedule_ids:
            try:
                await hass.async_add_executor_job(
                    coordinator.client.delete_schedule, schedule_id
                )
            except Exception as exc:
                _LOGGER.error("[Enphase] Failed to delete schedule %s: %s", schedule_id, exc)
                raise HomeAssistantError(
                    f"Failed to delete schedule {schedule_id}: {exc}"
                ) from exc

        affected_modes = {
            schedule_modes[sched_id]
            for sched_id in schedule_ids
            if sched_id in schedule_modes
        }
        for mode in sorted(affected_modes):
            settings = _mode_settings_from_data(coordinator, mode)
            if not settings:
                _LOGGER.debug(
                    "[Enphase] Skipping post-delete mode update for %s; no settings found.",
                    mode,
                )
                continue
            if mode in ("cfg", "dtg"):
                try:
                    await hass.async_add_executor_job(
                        coordinator.client.validate_schedule,
                        mode,
                        mode == "cfg",
                    )
                except Exception as exc:
                    _LOGGER.error(
                        "[Enphase] Failed to validate %s schedule after delete: %s",
                        mode,
                        exc,
                    )
                    raise HomeAssistantError(
                        f"Failed to validate {mode} schedule after delete: {exc}"
                    ) from exc
                await asyncio.sleep(3)
            try:
                await hass.async_add_executor_job(
                    coordinator.client.set_mode,
                    mode,
                    settings["enabled"],
                    settings.get("start_time"),
                    settings.get("end_time"),
                )
            except Exception as exc:
                _LOGGER.error(
                    "[Enphase] Failed to update %s settings after delete: %s",
                    mode,
                    exc,
                )
                raise HomeAssistantError(
                    f"Failed to update {mode} settings after delete: {exc}"
                ) from exc

        if "persistent_notification" in hass.config.components:
            # Check if notifications are enabled in options
            notifications_enabled = coordinator.entry.options.get(
                "notifications_enabled", True
            )
            if notifications_enabled:
                persistent_notification.async_create(
                    hass,
                    f"🗑️ Schedule(s) deleted successfully: {', '.join(schedule_ids)}.",
                    title="Enphase Envoy Cloud Control",
                    notification_id=f"{DOMAIN}_schedule_delete",
                )

        async_call_later(
            hass,
            5,
            lambda _: _schedule_post_action_refresh(hass, coordinator),
        )

    async def async_validate_schedule_service(call: ServiceCall) -> None:
        coordinator = _get_coordinator_from_call(hass, call)
        schedule_type = str(call.data["schedule_type"]).lower()

        try:
            result = await hass.async_add_executor_job(
                coordinator.client.validate_schedule,
                schedule_type,
                schedule_type == "cfg",
            )
        except Exception as exc:
            _LOGGER.error("[Enphase] Validation check failed: %s", exc)
            raise HomeAssistantError(f"Validation failed: {exc}") from exc

        message = "✅ Schedule validation succeeded."
        if isinstance(result, dict):
            valid = result.get("valid", True)
            detail = result.get("message") or result.get("status")
            if not valid:
                message = f"⚠️ Schedule invalid: {detail or 'Unknown error'}"
            elif detail:
                message = f"✅ Schedule valid: {detail}"

        if "persistent_notification" in hass.config.components:
            # Check if notifications are enabled in options
            notifications_enabled = coordinator.entry.options.get(
                "notifications_enabled", True
            )
            if notifications_enabled:
                persistent_notification.async_create(
                    hass,
                    message,
                    title="Enphase Envoy Cloud Control",
                    notification_id=f"{DOMAIN}_schedule_validate",
                )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_REFRESH,
        async_force_refresh_service,
        schema=FORCE_REFRESH_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_SCHEDULE, async_add_schedule_service, schema=ADD_SCHEDULE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_SCHEDULE,
        async_update_schedule_service,
        schema=UPDATE_SCHEDULE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_SCHEDULE,
        async_delete_schedule_service,
        schema=DELETE_SCHEDULE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_VALIDATE_SCHEDULE,
        async_validate_schedule_service,
        schema=VALIDATE_SCHEDULE_SCHEMA,
    )


async def _post_action_refresh(coordinator: EnphaseCoordinator) -> None:
    """Trigger a refresh after schedule changes."""
    try:
        await coordinator.async_request_refresh()
    except Exception as exc:  # pragma: no cover - defensive log
        _LOGGER.warning("[Enphase] Post-action refresh failed: %s", exc)


def _schedule_post_action_refresh(
    hass: HomeAssistant, coordinator: EnphaseCoordinator
) -> None:
    """Schedule a post-action refresh from any thread safely."""
    hass.loop.call_soon_threadsafe(
        hass.async_create_task, _post_action_refresh(coordinator)
    )


def _mode_settings_from_data(
    coordinator: EnphaseCoordinator, mode: str
) -> dict[str, Any]:
    data_root = coordinator.data or {}
    control = data_root.get("data", {}).get(f"{mode}Control", {})
    if not isinstance(control, dict):
        return {}

    if mode == "cfg":
        enabled = control.get("chargeFromGrid")
    else:
        enabled = control.get("enabled")

    if enabled is None:
        return {}

    settings: dict[str, Any] = {"enabled": bool(enabled)}
    if mode == "dtg":
        settings["start_time"] = control.get("startTime")
        settings["end_time"] = control.get("endTime")
    return settings
