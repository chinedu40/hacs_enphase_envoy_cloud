"""Client for the Enphase Enlighten cloud API.

Handles login (email/password -> JWT + XSRF token), token caching and
refresh, and the battery settings/schedule endpoints used by the
Battery Profile UI. All methods are synchronous and HA-agnostic; Home
Assistant callers must run them in an executor.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

import requests

__all__ = ["AuthError", "EnphaseClient"]

_LOGGER = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
# Legacy single-account cache location (pre per-entry caches).
LEGACY_CACHE_FILE = os.path.join(CACHE_DIR, "auth.json")

BATTERY_PROFILE_ORIGIN = "https://battery-profile-ui.enphaseenergy.com"


class AuthError(Exception):
    """Authentication or token error."""


class EnphaseClient:
    """Handles Enphase Cloud authentication and API calls."""

    def __init__(
        self,
        email: str,
        password: str,
        user_id: str | None,
        battery_id: str | None,
        cache_key: str | None = None,
        persist_cache: bool = True,
    ) -> None:
        self.email = email
        self.password = password
        self.user_id = user_id
        self.battery_id = battery_id
        self.jwt_token: str | None = None
        self.xsrf_token: str | None = None
        self.cookies: dict | None = None
        self.jwt_exp: int | None = None
        # Each client owns its session/cookie jar so multiple config entries
        # (accounts) no longer clobber each other's authentication state.
        self._session = requests.Session()
        self._persist_cache = persist_cache
        if cache_key:
            safe_key = re.sub(r"[^0-9A-Za-z_-]", "_", cache_key)
            self._cache_file = os.path.join(CACHE_DIR, f"auth_{safe_key}.json")
        else:
            self._cache_file = LEGACY_CACHE_FILE

    # -------------------------------------------------------------------------
    # CACHE
    # -------------------------------------------------------------------------

    def load_cache(self) -> None:
        """Load cached JWT/XSRF tokens if present."""
        try:
            cache_path = self._cache_file
            if not os.path.exists(cache_path) and os.path.exists(LEGACY_CACHE_FILE):
                # One-time migration from the pre-multi-account cache file.
                cache_path = LEGACY_CACHE_FILE
            if os.path.exists(cache_path):
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Never adopt another account's cached tokens.
                    cached_email = data.get("email")
                    if cached_email and cached_email != self.email:
                        _LOGGER.debug(
                            "[Enphase] Ignoring cached tokens for other account."
                        )
                        return
                    self.jwt_token = data.get("jwt")
                    self.xsrf_token = data.get("xsrf")
                    self.cookies = data.get("cookies")
                    self.jwt_exp = data.get("jwt_exp")
                    if not self.user_id:
                        self.user_id = data.get("user_id")
                    if not self.battery_id:
                        self.battery_id = data.get("battery_id")
                    if isinstance(self.cookies, dict):
                        self._session.cookies.update(self.cookies)
                    _LOGGER.debug("[Enphase] Loaded cached tokens")
        except (OSError, ValueError, TypeError) as exc:
            _LOGGER.warning("[Enphase] Failed to load cache: %s", exc)

    def _save_cache(self) -> None:
        """Persist JWT/XSRF tokens."""
        if not self._persist_cache:
            return
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            data = {
                "email": self.email,
                "jwt": self.jwt_token,
                "xsrf": self.xsrf_token,
                "cookies": requests.utils.dict_from_cookiejar(self._session.cookies),
                "jwt_exp": self.jwt_exp,
                "user_id": self.user_id,
                "battery_id": self.battery_id,
            }
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
            _LOGGER.debug("[Enphase] Cache saved.")
        except (OSError, TypeError) as exc:
            _LOGGER.warning("[Enphase] Failed to save cache: %s", exc)

    # -------------------------------------------------------------------------
    # AUTH
    # -------------------------------------------------------------------------

    def _csrf_login_token(self) -> str:
        """Get authenticity_token for login."""
        r = self._session.get("https://enlighten.enphaseenergy.com/login", timeout=30)
        if not r.ok:
            raise AuthError("Failed to access login page.")
        match = re.search(
            r'name=["\']authenticity_token["\'][^>]*value=["\']([^"\']+)["\']', r.text
        )
        if not match:
            raise AuthError("Could not find authenticity_token on login page.")
        return match.group(1)

    def _login(self) -> None:
        """Perform login to retrieve JWT."""
        if not self.email or not self.password:
            raise AuthError("Email and password are required for login.")

        _LOGGER.debug("[Enphase] Logging in to Enphase Enlighten as %s", self.email)
        self._session.cookies.clear()
        authenticity = self._csrf_login_token()
        payload = {
            "utf8": "✓",
            "authenticity_token": authenticity,
            "user[email]": self.email,
            "user[password]": self.password,
        }

        r = self._session.post(
            "https://enlighten.enphaseenergy.com/login/login",
            data=payload,
            timeout=30,
        )
        if not r.ok:
            raise AuthError("Login failed.")

        jwt_resp = self._session.get(
            "https://enlighten.enphaseenergy.com/app-api/jwt_token.json", timeout=30
        )
        jwt_json = jwt_resp.json()
        jwt_token = jwt_json.get("token")
        if not jwt_token:
            raise AuthError("JWT not found in response.")

        self.jwt_token = jwt_token
        self.jwt_exp = self._jwt_exp(jwt_token)
        _LOGGER.info("[Enphase] JWT retrieved successfully.")

        self._discover_ids()
        self._update_xsrf()
        self._save_cache()

    def _update_xsrf(self) -> None:
        """Fetch new XSRF token using JWT."""
        if not self.battery_id or not self.user_id:
            self._discover_ids()
        if not self.battery_id or not self.user_id:
            raise AuthError("Missing battery/user IDs for XSRF request.")

        _LOGGER.debug("[Enphase] Requesting new XSRF token.")
        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"battery/sites/{self.battery_id}/schedules/isValid"
        )
        headers = {
            "content-type": "application/json",
            "origin": BATTERY_PROFILE_ORIGIN,
            "referer": f"{BATTERY_PROFILE_ORIGIN}/",
            "e-auth-token": self.jwt_token,
            "username": str(self.user_id),
        }
        payload = {"scheduleType": "dtg"}
        r = self._session.post(url, json=payload, headers=headers, timeout=30)
        if "BP-XSRF-Token" in self._session.cookies:
            self.xsrf_token = self._session.cookies["BP-XSRF-Token"]
        if not self.xsrf_token and "BP-XSRF-Token" in r.headers.get("Set-Cookie", ""):
            match = re.search(r"BP-XSRF-Token=([^;]+)", r.headers["Set-Cookie"])
            if match:
                self.xsrf_token = match.group(1)
        if not self.xsrf_token:
            raise AuthError("Failed to retrieve XSRF token.")
        self._session.cookies.set(
            "BP-XSRF-Token",
            self.xsrf_token,
            domain="enlighten.enphaseenergy.com",
            path="/",
        )
        _LOGGER.debug("[Enphase] XSRF token updated.")

    def _ensure_tokens(self, force_refresh: bool = False) -> tuple[str, str]:
        """Ensure JWT/XSRF tokens are present and valid."""
        needs_login = force_refresh or not self._jwt_valid()
        if needs_login or not self._cookies_present():
            _LOGGER.info(
                "[Enphase] Refreshing authentication tokens (force_refresh=%s).",
                force_refresh,
            )
            self._login()
        else:
            _LOGGER.debug("[Enphase] Reusing cached JWT (exp=%s).", self.jwt_exp)
            if not self.user_id or not self.battery_id:
                self._discover_ids()

        if not self.xsrf_token:
            self._update_xsrf()

        self._save_cache()
        return self.jwt_token, self.xsrf_token

    def ensure_authenticated(self) -> dict[str, str | None]:
        """Ensure authentication and return resolved identifiers."""
        self._ensure_tokens()
        return {"user_id": self.user_id, "battery_id": self.battery_id}

    def _cookies_present(self) -> bool:
        return bool(self._session.cookies)

    def _jwt_valid(self) -> bool:
        if not self.jwt_token:
            return False
        exp = self.jwt_exp or self._jwt_exp(self.jwt_token)
        if not exp:
            return False
        self.jwt_exp = exp
        now = int(datetime.now(timezone.utc).timestamp())
        return exp > (now + 3600)

    def _jwt_exp(self, jwt: str) -> int | None:
        payload = self._jwt_payload_json(jwt)
        exp = payload.get("exp") if isinstance(payload, dict) else None
        if isinstance(exp, int):
            return exp
        return None

    def _jwt_payload_json(self, jwt: str) -> dict[str, Any]:
        try:
            payload = jwt.split(".")[1]
        except IndexError:
            return {}
        decoded = self._b64url_decode(payload)
        if not decoded:
            return {}
        try:
            return json.loads(decoded)
        except json.JSONDecodeError:
            return {}

    def _b64url_decode(self, data: str) -> str:
        data = data.replace("_", "/").replace("-", "+")
        pad = (4 - len(data) % 4) % 4
        data = data + ("=" * pad)
        try:
            return base64.b64decode(data).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return ""

    def _discover_ids(self) -> None:
        """Auto-discover numeric battery/site ID and user ID."""
        final_url = self._session.get(
            "https://enlighten.enphaseenergy.com/",
            timeout=30,
            allow_redirects=True,
        ).url

        match = re.search(r"/(web|pv/systems|systems)/([0-9]+)", final_url)
        site_id = match.group(2) if match else None
        if not site_id:
            raise AuthError(f"Could not extract site/battery id from URL: {final_url}")

        app_url = (
            "https://enlighten.enphaseenergy.com/app-api/"
            f"{site_id}/data.json?app=1&device_status=non_retired&is_mobile=0"
        )
        app_data = self._session.get(app_url, timeout=30).json()
        app_block = app_data.get("app", {})
        user_id = (
            app_block.get("userId")
            or app_block.get("user_id")
            or app_block.get("user", {}).get("id")
        )

        if not user_id or not str(user_id).isdigit():
            raise AuthError("Could not extract numeric user ID from app data.")

        if not self.battery_id:
            self.battery_id = str(site_id)
        if not self.user_id:
            self.user_id = str(user_id)

        _LOGGER.info(
            "[Enphase] Discovered IDs (user_id=%s, battery_id=%s)",
            self.user_id,
            self.battery_id,
        )

    # -------------------------------------------------------------------------
    # REQUEST HELPERS
    # -------------------------------------------------------------------------

    def _build_headers(
        self,
        jwt: str,
        xsrf: str,
        *,
        include_origin: bool = True,
        delete_variant: bool = False,
    ) -> dict[str, str]:
        """Build the standard API headers.

        ``include_origin=False`` matches the batterySettings GET variant (no
        origin/referer). ``delete_variant=True`` matches the schedule delete
        endpoint, which additionally needs accept/user-agent headers and a
        ``locale=en`` cookie prefix.
        """
        headers: dict[str, str] = {
            "content-type": "application/json",
            "e-auth-token": jwt,
            "x-xsrf-token": xsrf,
            "username": str(self.user_id),
        }
        if delete_variant:
            headers["accept"] = "application/json, text/plain, */*"
            headers["accept-language"] = "en-GB,en-US;q=0.9,en;q=0.8"
            headers["user-agent"] = "curl/8.14.1"
        if include_origin or delete_variant:
            headers["origin"] = BATTERY_PROFILE_ORIGIN
            headers["referer"] = f"{BATTERY_PROFILE_ORIGIN}/"
        headers["cookie"] = (
            f"locale=en; BP-XSRF-Token={xsrf};"
            if delete_variant
            else f"BP-XSRF-Token={xsrf}"
        )
        return headers

    def _request_with_retry(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        *,
        json_payload: Any | None = None,
        context: str = "request",
        retry_on_403: bool = True,
    ) -> requests.Response:
        """Send an API request, refreshing tokens and retrying once on 403.

        Does NOT call ``raise_for_status()`` — callers decide how to handle
        non-403 errors.
        """
        _LOGGER.debug(
            "[Enphase] %s request: url=%s headers=%s payload=%s",
            context,
            url,
            {k: v for k, v in headers.items() if k != "e-auth-token"},
            json_payload,
        )
        kwargs: dict[str, Any] = {"headers": headers, "timeout": 30}
        if json_payload is not None:
            kwargs["json"] = json_payload
        r = self._session.request(method, url, **kwargs)
        _LOGGER.debug(
            "[Enphase] %s response: status=%s body=%s",
            context,
            r.status_code,
            r.text,
        )
        if r.status_code == 403 and retry_on_403:
            _LOGGER.warning(
                "[Enphase] 403 on %s – refreshing tokens and retrying.", context
            )
            jwt, xsrf = self._ensure_tokens(force_refresh=True)
            # Only the token headers are refreshed; the cookie header is left
            # as-is on purpose — the session cookie jar carries the fresh
            # BP-XSRF-Token (matches the original per-method retry behaviour).
            headers["e-auth-token"] = jwt
            headers["x-xsrf-token"] = xsrf
            r = self._session.request(method, url, **kwargs)
            _LOGGER.debug(
                "[Enphase] %s retry response: status=%s body=%s",
                context,
                r.status_code,
                r.text,
            )
        return r

    # -------------------------------------------------------------------------
    # DATA
    # -------------------------------------------------------------------------

    def battery_settings(self) -> dict[str, Any]:
        """Fetch current battery configuration."""
        jwt, xsrf = self._ensure_tokens()
        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"batterySettings/{self.battery_id}?userId={self.user_id}&source=enho"
        )
        headers = self._build_headers(jwt, xsrf, include_origin=False)
        r = self._request_with_retry("GET", url, headers, context="battery_settings")
        r.raise_for_status()
        _LOGGER.debug("[Enphase] Battery settings fetched.")
        return r.json()

    # -------------------------------------------------------------------------
    # ACTIONS (toggles)
    # -------------------------------------------------------------------------

    def set_mode(
        self,
        mode: str,
        enable: bool,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> bool:
        """
        Toggle Enphase battery control modes via the cloud API.

        Accepts either short names (cfg/dtg/rbd) or full keys (cfgControl/dtgControl/rbdControl).
        """
        valid_modes = ["cfg", "dtg", "rbd", "cfgControl", "dtgControl", "rbdControl"]
        if mode not in valid_modes:
            raise ValueError(f"Invalid mode: {mode}")

        # Normalise key
        short_mode = mode.replace("Control", "")
        _LOGGER.info("[Enphase] Setting mode '%s' -> %s", short_mode, enable)

        jwt, xsrf = self._ensure_tokens()
        headers = self._build_headers(jwt, xsrf)

        # Payload mapping for each mode type
        payload: dict[str, Any]
        if short_mode == "cfg":
            payload = {
                "chargeFromGrid": enable,
                "acceptedItcDisclaimer": self._now_iso(),
            }
        elif short_mode == "dtg":
            payload = {
                "dtgControl": {
                    "enabled": enable,
                    "scheduleSupported": True,
                }
            }
            if start_time and end_time:
                payload["dtgControl"]["startTime"] = self._time_to_minutes(start_time)
                payload["dtgControl"]["endTime"] = self._time_to_minutes(end_time)
        elif short_mode == "rbd":
            payload = {"rbdControl": {"enabled": enable}}
        else:
            raise ValueError(f"Unsupported mode: {short_mode}")

        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"batterySettings/{self.battery_id}?userId={self.user_id}&source=enho"
        )

        r = self._request_with_retry(
            "PUT",
            url,
            headers,
            json_payload=payload,
            context=f"set_mode({short_mode})",
        )

        if not r.ok:
            _LOGGER.error(
                "[Enphase] set_mode(%s) failed: %s %s",
                short_mode,
                r.status_code,
                r.text,
            )
            r.raise_for_status()

        _LOGGER.info(
            "[Enphase] Mode '%s' set successfully (HTTP %s)", short_mode, r.status_code
        )
        return True

    # -------------------------------------------------------------------------
    # SCHEDULE MANAGEMENT
    # -------------------------------------------------------------------------

    def get_schedules(self) -> dict[str, Any]:
        """Return all schedules for this site/battery."""
        jwt, xsrf = self._ensure_tokens()
        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"battery/sites/{self.battery_id}/schedules"
        )
        headers = self._build_headers(jwt, xsrf)
        r = self._request_with_retry("GET", url, headers, context="get_schedules")
        r.raise_for_status()
        return r.json()

    def add_schedule(
        self,
        schedule_type: str,
        start_time: str,
        end_time: str,
        limit: int | str,
        days: Sequence[int | str],
        timezone: str = "UTC",
    ) -> dict[str, Any]:
        """Add a new schedule entry (mirrors your REST command)."""
        schedule_type = str(schedule_type).upper()
        jwt, xsrf = self._ensure_tokens()
        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"battery/sites/{self.battery_id}/schedules"
        )
        headers = self._build_headers(jwt, xsrf)
        payload = {
            "timezone": timezone or "UTC",
            "startTime": start_time[:5],
            "endTime": end_time[:5],
            "limit": int(limit),
            "scheduleType": schedule_type,
            "days": [int(d) for d in days],
        }
        _LOGGER.info("[Enphase] Adding schedule: %s", payload)
        r = self._request_with_retry(
            "POST", url, headers, json_payload=payload, context="add_schedule"
        )
        r.raise_for_status()
        _LOGGER.info("[Enphase] Schedule added successfully.")
        return r.json()

    def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a schedule by ID (mirrors your REST command)."""
        jwt, xsrf = self._ensure_tokens()
        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"battery/sites/{self.battery_id}/schedules/{schedule_id}/delete"
        )
        headers = self._build_headers(jwt, xsrf, delete_variant=True)
        _LOGGER.info("[Enphase] Deleting schedule ID %s", schedule_id)
        r = self._request_with_retry(
            "POST", url, headers, json_payload={}, context="delete_schedule"
        )
        r.raise_for_status()
        _LOGGER.info("[Enphase] Schedule %s deleted successfully.", schedule_id)
        return True

    def validate_schedule(
        self, schedule_type: str = "dtg", force_opted: bool = False
    ) -> dict[str, Any]:
        """Validate schedule feasibility (isValid endpoint)."""
        schedule_type = str(schedule_type).upper()
        jwt, xsrf = self._ensure_tokens()
        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"battery/sites/{self.battery_id}/schedules/isValid"
        )
        payload: dict[str, Any] = {"scheduleType": schedule_type}
        if schedule_type == "CFG" and force_opted:
            payload["forceScheduleOpted"] = True
        headers = self._build_headers(jwt, xsrf)
        # NOTE: no 403 retry here — the isValid endpoint is itself part of the
        # XSRF refresh flow (see _update_xsrf), matching original behaviour.
        r = self._request_with_retry(
            "POST",
            url,
            headers,
            json_payload=payload,
            context="validate_schedule",
            retry_on_403=False,
        )
        r.raise_for_status()
        return r.json()

    # -------------------------------------------------------------------------
    # UTILS
    # -------------------------------------------------------------------------

    def _now_iso(self) -> str:
        """Return current UTC time in ISO format (milliseconds precision)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def _time_to_minutes(self, time_value: str | int) -> int:
        """Convert HH:MM strings into minutes since midnight."""
        if isinstance(time_value, int):
            return time_value
        match = re.match(r"^(\d{1,2}):(\d{2})$", str(time_value).strip())
        if not match:
            raise ValueError(f"Invalid time value: {time_value}")
        hours = int(match.group(1))
        minutes = int(match.group(2))
        return hours * 60 + minutes
