from __future__ import annotations
import logging
from datetime import datetime, timezone
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN
from .device import battery_device_info
from .editor import normalize_schedules, get_coordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Enphase sensors from a config entry."""
    coordinator = get_coordinator(hass, entry.entry_id)
    sensors = [EnphaseBatteryModesSensor(coordinator), EnphaseSchedulesSummarySensor(coordinator)]

    # Add per-mode schedule sensors
    for mode in ["cfg", "dtg", "rbd"]:
        sensors.append(EnphaseScheduleSensor(coordinator, mode))

    async_add_entities(sensors, True)


# ---------------------------------------------------------------------------
# MAIN BATTERY MODES (DIAGNOSTIC SENSOR)
# ---------------------------------------------------------------------------

class EnphaseBatteryModesSensor(CoordinatorEntity, SensorEntity):
    """Diagnostic sensor exposing overall battery control state."""

    _attr_icon = "mdi:battery-heart-variant"
    _attr_name = "Enphase Battery Modes"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_battery_modes"

    @property
    def state(self):
        """Return basic status."""
        return "OK" if self.coordinator.data else "Unavailable"


    @property
    def extra_state_attributes(self):
        """Expose detailed diagnostic data and timing."""
        try:
            data = self.coordinator.data or {}
            d = data.get("data", {}) or {}
            schedules = data.get("schedules", {}) or {}

            #  If real schedules exist, overlay them into cfg/dtg/rbd
            for mode in ["cfg", "dtg", "rbd"]:
                if mode in schedules:
                    details = schedules[mode].get("details", [])
                    if details and isinstance(details, list):
                        # Replace null start/end in cfgControl schedules
                        ctrl = d.get(f"{mode}Control")
                        if ctrl and "schedules" in ctrl:
                            for i, sched in enumerate(ctrl["schedules"]):
                                real = details[i] if i < len(details) else None
                                if real and real.get("startTime"):
                                    sched["startTime"] = real["startTime"]
                                if real and real.get("endTime"):
                                    sched["endTime"] = real["endTime"]

            attrs = {
                "cfg": d.get("cfgControl"),
                "dtg": d.get("dtgControl"),
                "rbd": d.get("rbdControl"),
                "other": {
                    k: v
                    for k, v in d.items()
                    if k not in ("cfgControl", "dtgControl", "rbdControl")
                },
                "last_refresh": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S%z"
                ),
            }

            # Include last successful poll timestamp from coordinator
            if getattr(self.coordinator, "last_update_success_time", None):
                t = self.coordinator.last_update_success_time
                if isinstance(t, datetime):
                    attrs["last_successful_poll"] = t.strftime("%Y-%m-%dT%H:%M:%S%z")

            return attrs
        except Exception as exc:
            _LOGGER.warning("Error parsing battery modes attributes: %s", exc)
            return {"error": str(exc)}

    @property
    def device_info(self):
        """Ensure the sensor is attached to the shared Enphase device."""
        return battery_device_info(self.coordinator.entry.entry_id)


class EnphaseSchedulesSummarySensor(CoordinatorEntity, SensorEntity):
    """Normalized schedule list for editor usage."""

    _attr_name = "Enphase Schedules Summary"
    _attr_icon = "mdi:calendar-multiple"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_schedules_summary"

    @property
    def state(self):
        schedules = normalize_schedules(self.coordinator)
        return str(len(schedules))

    @property
    def extra_state_attributes(self):
        attrs = {
            "schedules": normalize_schedules(self.coordinator),
            "last_refresh": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        if getattr(self.coordinator, "last_update_success_time", None):
            t = self.coordinator.last_update_success_time
            if isinstance(t, datetime):
                attrs["last_successful_poll"] = t.strftime("%Y-%m-%dT%H:%M:%S%z")
        return attrs

    @property
    def device_info(self):
        return battery_device_info(self.coordinator.entry.entry_id)


# ---------------------------------------------------------------------------
# PER-MODE SCHEDULE SENSORS
# ---------------------------------------------------------------------------

class EnphaseScheduleSensor(CoordinatorEntity, SensorEntity):
    """Represents the schedule list for one Enphase control mode."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, mode: str):
        super().__init__(coordinator)
        self.mode = mode  # cfg | dtg | rbd
        self._attr_name = f"Enphase {mode.upper()} Schedule"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{mode}_schedule"

    @property
    def state(self):
        """Readable summary like '21:30–03:30, 05:00–06:00'."""
        scheds = self._schedules()
        if not scheds:
            return "None"
        state_parts = []
        for sched in scheds:
            start = sched.get("startTime", "??")
            end = sched.get("endTime", "??")
            schedule_id = sched.get("scheduleId")
            label = f"#{schedule_id} " if schedule_id is not None else ""
            state_parts.append(f"{label}{start}–{end}")
        return ", ".join(state_parts)

    @property
    def extra_state_attributes(self):
        """Expose full schedule details with IDs."""
        attrs = {"schedules": self._schedules()}
        # Include metadata for clarity
        attrs["last_refresh"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")
        if getattr(self.coordinator, "last_update_success_time", None):
            t = self.coordinator.last_update_success_time
            if isinstance(t, datetime):
                attrs["last_successful_poll"] = t.strftime("%Y-%m-%dT%H:%M:%S%z")
        sched_ids = [s.get("scheduleId") for s in attrs["schedules"] if s.get("scheduleId")]
        if sched_ids:
            attrs["schedule_ids"] = sched_ids
        return attrs

    # ---------------------------------------------------------------------
    # Async-safe schedule fetching with caching
    # ---------------------------------------------------------------------
    async def _async_fetch_schedules_safe(self):
        """Fetch schedules via executor to avoid blocking."""
        try:
            schedules = await self.coordinator.hass.async_add_executor_job(
                self.coordinator.client.get_schedules
            )
            # Cache for reuse across sensors
            self.coordinator.client._last_schedules = schedules
            return schedules
        except Exception as e:
            _LOGGER.warning("Async fetch failed for %s schedules: %s", self.mode, e)
            return {}

    def _schedules(self):
        """Return current schedules for this mode."""
        try:
            data_root = self.coordinator.data or {}
            d = data_root.get("data", {})

            # Case 1: <mode>Control.schedules[]
            block = d.get(f"{self.mode}Control") or {}
            if "schedules" in block:
                return block["schedules"]

            # Case 2: <mode>.details[]
            block2 = d.get(self.mode)
            if block2 and isinstance(block2, dict) and "details" in block2:
                return block2["details"]

            # Case 3: coordinator exposes schedules at the root level
            sched_root = data_root.get("schedules")
            if isinstance(sched_root, dict):
                candidates = []
                if self.mode in sched_root:
                    candidates.append(sched_root[self.mode])
                if "data" in sched_root and isinstance(sched_root["data"], dict):
                    candidates.append(sched_root["data"].get(self.mode))

                for candidate in candidates:
                    if not candidate:
                        continue
                    if isinstance(candidate, dict) and "details" in candidate:
                        return candidate["details"]
                    if isinstance(candidate, list):
                        return candidate

            # Case 4: fallback — use cached schedules
            if hasattr(self.coordinator.client, "_last_schedules"):
                schedules = getattr(self.coordinator.client, "_last_schedules")
            elif data_root.get("schedules_raw"):
                schedules = data_root.get("schedules_raw")
            else:
                # Schedule a background safe fetch
                self.coordinator.hass.async_create_task(self._async_fetch_schedules_safe())
                return []

            if isinstance(schedules, dict):
                if self.mode in schedules:
                    m = schedules[self.mode]
                    if isinstance(m, dict) and "details" in m:
                        return m["details"]
                    if isinstance(m, list):
                        return m
                if "data" in schedules and isinstance(schedules["data"], dict):
                    m = schedules["data"].get(self.mode)
                    if isinstance(m, dict) and "details" in m:
                        return m["details"]
                    if isinstance(m, list):
                        return m
            return []
        except Exception as e:
            _LOGGER.warning("Failed to extract %s schedules: %s", self.mode, e)
            return []

    @property
    def device_info(self):
        """Ensure this sensor attaches to the same device as toggles."""
        return battery_device_info(self.coordinator.entry.entry_id)
