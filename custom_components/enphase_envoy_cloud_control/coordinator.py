"""Data update coordinator for Enphase Envoy Cloud Control.

Polls the Enphase cloud for battery settings and schedules, merges them
into a single data structure, and surfaces authentication failures to the
user via a persistent notification.
"""

from __future__ import annotations

from datetime import timedelta, datetime, timezone
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, LOGGER, DEFAULT_POLL_INTERVAL
from .enphase_client import AuthError, EnphaseClient

__all__ = ["EnphaseCoordinator"]

_LOGGER = LOGGER

AUTH_NOTIFICATION_ID = f"{DOMAIN}_auth_failure"


class EnphaseCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manages periodic updates from the Enphase Cloud."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.client = EnphaseClient(
            email=entry.data.get("email"),
            password=entry.data.get("password"),
            user_id=entry.data.get("user_id"),
            battery_id=entry.data.get("battery_id"),
        )

        # Custom polling interval (default 30s)
        poll_interval = entry.options.get("poll_interval", DEFAULT_POLL_INTERVAL)
        self.update_interval = timedelta(seconds=poll_interval)
        _LOGGER.info("[Enphase] Polling interval set to %ss", poll_interval)

        self.last_refresh: str | None = None
        self.last_successful_poll: datetime | None = None
        self._auth_notified = False

        super().__init__(
            hass,
            _LOGGER,
            name="Enphase Envoy Cloud Control Coordinator",
            update_interval=self.update_interval,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from Enphase Cloud."""
        try:
            _LOGGER.debug("[Enphase] Starting scheduled data update.")
            data = await self.hass.async_add_executor_job(self._fetch)
        except AuthError as err:
            _LOGGER.error("[Enphase] Authentication failed during update: %s", err)
            self._async_notify_auth_failure(err)
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except Exception as err:
            _LOGGER.error("[Enphase] Error updating data: %s", err)
            raise UpdateFailed(err) from err

        self.last_successful_poll = datetime.now(timezone.utc)
        self.last_refresh = self.last_successful_poll.isoformat()
        self._async_dismiss_auth_failure()
        return data

    def _async_notify_auth_failure(self, err: AuthError) -> None:
        """Surface an authentication failure as a persistent notification.

        Deliberately ignores the ``notifications_enabled`` option: that toggle
        gates informational success messages, while an auth failure means the
        integration is dead until the user acts, so it must always be visible.
        """
        if "persistent_notification" not in self.hass.config.components:
            return
        persistent_notification.async_create(
            self.hass,
            (
                "⚠️ Enphase cloud authentication failed and entities are "
                f"unavailable: {err}\n\nCheck your Enphase Enlighten email and "
                "password. The integration will keep retrying automatically."
            ),
            title="Enphase Envoy Cloud Control",
            notification_id=AUTH_NOTIFICATION_ID,
        )
        self._auth_notified = True

    def _async_dismiss_auth_failure(self) -> None:
        """Dismiss the auth-failure notification after a successful update."""
        if not self._auth_notified:
            return
        if "persistent_notification" in self.hass.config.components:
            persistent_notification.async_dismiss(self.hass, AUTH_NOTIFICATION_ID)
        self._auth_notified = False

    def _fetch(self) -> dict[str, Any]:
        """Synchronous fetch — runs inside executor."""
        battery_data = self.client.battery_settings() or {}
        schedules = self.client.get_schedules() or {}

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
        }
        _LOGGER.debug("[Enphase] Data fetch complete. Keys: %s", list(merged.keys()))
        return merged

    async def async_force_refresh(self) -> None:
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
