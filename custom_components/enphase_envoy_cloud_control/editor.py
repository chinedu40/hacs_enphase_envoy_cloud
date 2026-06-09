"""Helpers for schedule editor state and normalization."""

from __future__ import annotations

import re
from datetime import time
from typing import Any

from .const import DOMAIN
from .coordinator import EnphaseCoordinator

__all__ = [
    "DAY_KEY_BY_INDEX",
    "DAY_ORDER",
    "days_list_from_editor",
    "default_day_flags",
    "default_editor_state",
    "default_new_editor_state",
    "editor_days_from_list",
    "get_coordinator",
    "get_entry_data",
    "normalize_schedules",
]

DAY_ORDER: list[tuple[str, int]] = [
    ("mon", 1),
    ("tue", 2),
    ("wed", 3),
    ("thu", 4),
    ("fri", 5),
    ("sat", 6),
    ("sun", 7),
]
DAY_KEY_BY_INDEX = {index: key for key, index in DAY_ORDER}


def default_day_flags() -> dict[str, bool]:
    """Return day flag defaults (all false)."""
    return {key: False for key, _ in DAY_ORDER}


def default_editor_state() -> dict[str, Any]:
    """Return a fresh editor state mapping."""
    return {
        "selected_schedule_id": None,
        "schedule_type": "cfg",
        "start_time": "00:00",
        "end_time": "00:00",
        "limit": 0,
        "days": default_day_flags(),
    }


def default_new_editor_state() -> dict[str, Any]:
    """Return default state for new schedules."""
    return {
        "schedule_type": "cfg",
        "start_time": "00:00",
        "end_time": "00:00",
        "limit": 0,
        "days": default_day_flags(),
    }


def get_entry_data(hass, entry_id: str) -> dict[str, Any]:
    """Return stored entry data."""
    return hass.data[DOMAIN][entry_id]


def get_coordinator(hass, entry_id: str) -> EnphaseCoordinator:
    """Return coordinator from entry data."""
    return get_entry_data(hass, entry_id)["coordinator"]


def editor_days_from_list(days: list[int]) -> dict[str, bool]:
    """Convert list of ints into editor day flags."""
    flags = default_day_flags()
    for day in days:
        key = DAY_KEY_BY_INDEX.get(day)
        if key:
            flags[key] = True
    return flags


def days_list_from_editor(flags: dict[str, bool]) -> list[int]:
    """Convert editor day flags into list of ints."""
    return [index for key, index in DAY_ORDER if flags.get(key)]


def _normalize_time(value: Any) -> str:
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if value is None:
        return "00:00"
    if isinstance(value, (int, float)):
        return f"{int(value):02d}:00"
    value_str = str(value)
    match = re.search(r"(\d{2}:\d{2})", value_str)
    if match:
        return match.group(1)
    return value_str[:5]


def _normalize_days(raw: Any) -> list[int]:
    if not raw:
        return []
    if isinstance(raw, dict):
        return sorted(
            int(key)
            for key, enabled in raw.items()
            if enabled and str(key).isdigit()
        )
    if isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        values = re.split(r"[,\s]+", str(raw))
    days: list[int] = []
    for value in values:
        try:
            day = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= day <= 7:
            days.append(day)
    return sorted(set(days))


def _collect_schedules(coordinator: EnphaseCoordinator, mode: str) -> list[dict[str, Any]]:
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


def normalize_schedules(coordinator: EnphaseCoordinator) -> list[dict[str, Any]]:
    """Return normalized schedules for all modes."""
    normalized: list[dict[str, Any]] = []
    for mode in ("cfg", "dtg", "rbd"):
        for schedule in _collect_schedules(coordinator, mode):
            schedule_id = schedule.get("scheduleId")
            if schedule_id is None:
                continue
            normalized.append(
                {
                    "id": str(schedule_id),
                    "type": str(schedule.get("scheduleType", mode)).lower(),
                    "start": _normalize_time(schedule.get("startTime")),
                    "end": _normalize_time(schedule.get("endTime")),
                    "limit": int(schedule.get("limit") or schedule.get("powerLimit") or 0),
                    "days": _normalize_days(
                        schedule.get("days")
                        or schedule.get("daysOfWeek")
                        or schedule.get("dayOfWeek")
                    ),
                }
            )
    return normalized
