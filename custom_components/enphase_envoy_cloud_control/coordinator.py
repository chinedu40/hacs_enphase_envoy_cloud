from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, datetime, timezone
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import LOGGER, DEFAULT_POLL_INTERVAL
from .enphase_client import EnphaseClient

_LOGGER = LOGGER


class EnphaseCoordinator(DataUpdateCoordinator):
    """Manages periodic updates from the Enphase Cloud."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.client = EnphaseClient(
            email=entry.data.get("email"),
            password=entry.data.get("password"),
            user_id=entry.data.get("user_id"),
            battery_id=entry.data.get("battery_id"),
        )

        # ✅ Custom polling interval (default 30s)
        poll_interval = entry.options.get("poll_interval", DEFAULT_POLL_INTERVAL)
        self.update_interval = timedelta(seconds=poll_interval)
        _LOGGER.info(f"[Enphase] Polling interval set to {poll_interval}s")

        self.last_refresh = None
        self.last_successful_poll = None

        # Energy stats (today/daily/lifetime) are non-critical and slow. Skip
        # them on the very first refresh so config-entry setup isn't blocked;
        # they fill in on the first scheduled poll instead.
        self._skip_energy = True

        super().__init__(
            hass,
            _LOGGER,
            name="Enphase Envoy Cloud Control Coordinator",
            update_interval=self.update_interval,
        )

    async def _async_update_data(self):
        """Fetch latest data from Enphase Cloud."""
        try:
            _LOGGER.debug("[Enphase] Starting scheduled data update.")
            data = await self.hass.async_add_executor_job(self._fetch)
            self.last_successful_poll = datetime.now(timezone.utc)
            self.last_refresh = self.last_successful_poll.isoformat()
            return data
        except Exception as err:
            _LOGGER.error("[Enphase] Error updating data: %s", err)
            raise UpdateFailed(err)

    @staticmethod
    def _safe_fetch(label, func, *args):
        """Call an energy-stats endpoint, returning {} on failure.

        Keeps non-critical energy fetches from aborting the whole update
        (which would also drop the battery/schedule data).
        """
        try:
            return func(*args) or {}
        except Exception as err:  # noqa: BLE001 - intentionally broad
            _LOGGER.warning("[Enphase] %s fetch failed: %s", label, err)
            return {}

    def _fetch_energy(self):
        """Fetch the three energy endpoints concurrently.

        Each call is independent and blocking, so running them in a small
        thread pool collapses their combined latency to roughly the slowest
        single request. Failures are isolated via _safe_fetch.
        """
        # Use HA's configured local time so the month boundary matches the
        # site's calendar (and the week/year sensor boundaries).
        month_start = dt_util.now().strftime("%Y-%m-01")
        with ThreadPoolExecutor(max_workers=3) as pool:
            today = pool.submit(
                self._safe_fetch, "today stats", self.client.get_today_stats
            )
            daily = pool.submit(
                self._safe_fetch, "daily energy", self.client.get_daily_energy, month_start
            )
            lifetime = pool.submit(
                self._safe_fetch, "lifetime energy", self.client.get_lifetime_energy
            )
            return today.result(), daily.result(), lifetime.result()

    def _fetch(self):
        """Synchronous fetch — runs inside executor."""
        try:
            battery_data = self.client.battery_settings() or {}
            schedules = self.client.get_schedules() or {}

            # Energy stats are non-critical and add several blocking HTTP calls.
            # Skip them on the first refresh so config-entry setup stays fast;
            # afterwards fetch all three concurrently. When skipped, reuse the
            # previously fetched values so sensors don't flap to unavailable.
            if self._skip_energy:
                self._skip_energy = False
                prev = self.data or {}
                today_data = prev.get("today", {}) or {}
                daily_energy_data = prev.get("daily_energy", {}) or {}
                lifetime_energy_data = prev.get("lifetime_energy", {}) or {}
            else:
                today_data, daily_energy_data, lifetime_energy_data = self._fetch_energy()

            # Persist the last schedule payload for entities that reference it
            # outside of the coordinator data structure (legacy behaviour).
            setattr(self.client, "_last_schedules", schedules)

            # Normalise schedule payload to the inner "data" block when present.
            schedule_block = schedules.get("data") if isinstance(schedules, dict) else None
            if not schedule_block:
                schedule_block = schedules if isinstance(schedules, dict) else {}

            inner_data = battery_data.get("data", battery_data)

            # Merge concrete schedule details (start/end, limit, etc.) into the
            # cfg/dtg/rbd control blocks so entities always read fresh values.
            if isinstance(inner_data, dict) and isinstance(schedule_block, dict):
                for mode in ("cfg", "dtg", "rbd"):
                    details = schedule_block.get(mode)
                    if not isinstance(details, dict):
                        continue
                    detail_list = details.get("details")
                    if not isinstance(detail_list, list):
                        continue

                    control_key = f"{mode}Control"
                    control = inner_data.get(control_key)
                    if not isinstance(control, dict):
                        continue
                    schedules_list = control.get("schedules")
                    if not isinstance(schedules_list, list):
                        continue

                    merged_schedules = []
                    for idx, sched in enumerate(schedules_list):
                        merged_sched = dict(sched) if isinstance(sched, dict) else {}
                        detail = detail_list[idx] if idx < len(detail_list) else None
                        if isinstance(detail, dict):
                            for key in ("startTime", "endTime", "scheduleId", "limit", "days"):
                                if detail.get(key) is not None:
                                    merged_sched[key] = detail[key]
                        merged_schedules.append(merged_sched)
                    control["schedules"] = merged_schedules

            merged = {
                "data": inner_data,
                "schedules": schedule_block,
                "schedules_raw": schedules,
                "today": today_data,
                "daily_energy": daily_energy_data,
                "lifetime_energy": lifetime_energy_data,
            }
            _LOGGER.debug("[Enphase] Data fetch complete. Keys: %s", list(merged.keys()))
            return merged
        except Exception as e:
            _LOGGER.warning("[Enphase] Coordinator fetch failed: %s", e)
            raise

    async def async_force_refresh(self):
        """Manually triggered refresh (Force Cloud Refresh button)."""
        _LOGGER.info("[Enphase] Manual cloud refresh requested.")
        await self.async_request_refresh()

    async def async_initialize_auth(self) -> None:
        """Ensure authentication is ready and persist discovered IDs."""
        await self.hass.async_add_executor_job(self.client.load_cache)
        ids = await self.hass.async_add_executor_job(self.client.ensure_authenticated)
        if not ids:
            return

        updated = dict(self.entry.data)
        changed = False
        for key in ("user_id", "battery_id"):
            value = ids.get(key)
            if value and not updated.get(key):
                updated[key] = value
                changed = True

        if changed:
            self.hass.config_entries.async_update_entry(self.entry, data=updated)
