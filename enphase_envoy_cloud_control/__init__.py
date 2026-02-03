"""Enphase Envoy Cloud Control integration setup."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.event import async_call_later

from .const import DEFAULT_POLL_INTERVAL, DOMAIN
from .coordinator import EnphaseCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "switch", "button"]
SERVICES_REGISTERED = "_services_registered"

SERVICE_FORCE_REFRESH = "force_refresh"
SERVICE_ADD_SCHEDULE = "add_schedule"
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

DELETE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("schedule_id"): vol.All(cv.string, vol.Match(r"^\d+$")),
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
    domain_data[entry.entry_id] = coordinator

    if not domain_data.get(SERVICES_REGISTERED):
        _register_services(hass)
        domain_data[SERVICES_REGISTERED] = True

    entry.async_on_unload(entry.add_update_listener(_async_handle_options_update))

    await coordinator.async_initialize_auth()
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
                SERVICE_DELETE_SCHEDULE,
                SERVICE_VALIDATE_SCHEDULE,
            ):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
            domain_data.pop(SERVICES_REGISTERED, None)

    return unload_ok


async def _async_handle_options_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply updated options (e.g. polling interval) to the coordinator."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
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
        entry_id: coord
        for entry_id, coord in domain_data.items()
        if isinstance(coord, EnphaseCoordinator)
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

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "message": (
                    "✅ Schedule added successfully for "
                    f"{schedule_type.upper()} ({start_str}–{end_str})."
                ),
                "title": "Enphase Envoy Cloud Control",
                "notification_id": f"{DOMAIN}_schedule_add",
            },
        )

        async_call_later(
            hass,
            5,
            lambda _: hass.async_create_task(_post_action_refresh(coordinator)),
        )

    async def async_delete_schedule_service(call: ServiceCall) -> None:
        coordinator = _get_coordinator_from_call(hass, call)
        schedule_id = call.data["schedule_id"].strip()
        confirm = call.data.get("confirm")
        if not confirm:
            raise HomeAssistantError("Confirmation required to delete a schedule.")

        known_ids = {
            str(sched.get("scheduleId"))
            for sensor in ("cfg", "dtg", "rbd")
            for sched in _collect_schedules(coordinator, sensor)
            if sched.get("scheduleId") is not None
        }

        if known_ids and schedule_id not in known_ids:
            raise HomeAssistantError("Schedule ID not found in current data.")

        try:
            await hass.async_add_executor_job(
                coordinator.client.delete_schedule, schedule_id
            )
        except Exception as exc:
            _LOGGER.error("[Enphase] Failed to delete schedule %s: %s", schedule_id, exc)
            raise HomeAssistantError(f"Failed to delete schedule: {exc}") from exc

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "message": f"🗑️ Schedule {schedule_id} deleted successfully.",
                "title": "Enphase Envoy Cloud Control",
                "notification_id": f"{DOMAIN}_schedule_delete",
            },
        )

        async_call_later(
            hass,
            5,
            lambda _: hass.async_create_task(_post_action_refresh(coordinator)),
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

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "message": message,
                "title": "Enphase Envoy Cloud Control",
                "notification_id": f"{DOMAIN}_schedule_validate",
            },
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


def _collect_schedules(coordinator: EnphaseCoordinator, mode: str) -> list[dict[str, Any]]:
    """Collect cached schedules for the given mode."""
    data_root = coordinator.data or {}
    schedule_block = data_root.get("data", {}).get(f"{mode}Control", {})
    schedules = schedule_block.get("schedules")
    if isinstance(schedules, list):
        return schedules

    fallback = data_root.get("schedules", {})
    if isinstance(fallback, dict):
        candidate = fallback.get(mode)
        if isinstance(candidate, dict) and isinstance(candidate.get("details"), list):
            return candidate["details"]
        if isinstance(candidate, list):
            return candidate
        inner = fallback.get("data", {}).get(mode)
        if isinstance(inner, dict) and isinstance(inner.get("details"), list):
            return inner["details"]
        if isinstance(inner, list):
            return inner

    cached = getattr(coordinator.client, "_last_schedules", None)
    if isinstance(cached, dict):
        candidate = cached.get(mode)
        if isinstance(candidate, dict) and isinstance(candidate.get("details"), list):
            return candidate["details"]
        if isinstance(candidate, list):
            return candidate

    return []
