from __future__ import annotations
import base64
import logging
import os
import json
import re
from datetime import datetime, timezone
from typing import Any
import requests

_LOGGER = logging.getLogger(__name__)
SESSION = requests.Session()

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
CACHE_FILE = os.path.join(CACHE_DIR, "auth.json")


class AuthError(Exception):
    """Authentication or token error."""


class EnphaseClient:
    """Handles Enphase Cloud authentication and API calls."""

    def __init__(self, email: str, password: str, user_id: str | None, battery_id: str | None):
        self.email = email
        self.password = password
        self.user_id = user_id
        self.battery_id = battery_id
        self.jwt_token: str | None = None
        self.xsrf_token: str | None = None
        self.cookies: dict | None = None
        self.jwt_exp: int | None = None
        self._cache_loaded: bool = False

    # -------------------------------------------------------------------------
    # CACHE
    # -------------------------------------------------------------------------

    def _load_cache(self):
        """Load cached JWT/XSRF tokens if present."""
        self._cache_loaded = True
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.jwt_token = data.get("jwt")
                    self.xsrf_token = data.get("xsrf")
                    self.cookies = data.get("cookies")
                    self.jwt_exp = data.get("jwt_exp")
                    if not self.user_id:
                        self.user_id = data.get("user_id")
                    if not self.battery_id:
                        self.battery_id = data.get("battery_id")
                    if isinstance(self.cookies, dict):
                        SESSION.cookies.update(self.cookies)
                    _LOGGER.debug("[Enphase] Loaded cached tokens")
        except Exception as exc:
            _LOGGER.warning("[Enphase] Failed to load cache: %s", exc)

    def _save_cache(self):
        """Persist JWT/XSRF tokens."""
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            data = {
                "jwt": self.jwt_token,
                "xsrf": self.xsrf_token,
                "cookies": requests.utils.dict_from_cookiejar(SESSION.cookies),
                "jwt_exp": self.jwt_exp,
                "user_id": self.user_id,
                "battery_id": self.battery_id,
            }
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
            _LOGGER.debug("[Enphase] Cache saved.")
        except Exception as exc:
            _LOGGER.warning("[Enphase] Failed to save cache: %s", exc)

    # -------------------------------------------------------------------------
    # AUTH
    # -------------------------------------------------------------------------

    def _csrf_login_token(self):
        """Get authenticity_token for login."""
        r = SESSION.get("https://enlighten.enphaseenergy.com/login", timeout=30)
        if not r.ok:
            raise AuthError("Failed to access login page.")
        match = re.search(
            r'name=["\']authenticity_token["\'][^>]*value=["\']([^"\']+)["\']', r.text
        )
        if not match:
            raise AuthError("Could not find authenticity_token on login page.")
        return match.group(1)

    def _login(self):
        """Perform login to retrieve JWT."""
        if not self.email or not self.password:
            raise AuthError("Email and password are required for login.")

        SESSION.cookies.clear()
        authenticity = self._csrf_login_token()
        payload = {
            "utf8": "✓",
            "authenticity_token": authenticity,
            "user[email]": self.email,
            "user[password]": self.password,
        }

        r = SESSION.post(
            "https://enlighten.enphaseenergy.com/login/login",
            data=payload,
            timeout=30,
        )
        if not r.ok:
            raise AuthError("Login failed.")

        jwt_resp = SESSION.get(
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

    def _update_xsrf(self):
        """Fetch new XSRF token using JWT."""
        if not self.battery_id or not self.user_id:
            self._discover_ids()
        if not self.battery_id or not self.user_id:
            raise AuthError("Missing battery/user IDs for XSRF request.")

        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"battery/sites/{self.battery_id}/schedules/isValid"
        )
        headers = {
            "content-type": "application/json",
            "origin": "https://battery-profile-ui.enphaseenergy.com",
            "referer": "https://battery-profile-ui.enphaseenergy.com/",
            "e-auth-token": self.jwt_token,
            "username": str(self.user_id),
        }
        payload = {"scheduleType": "dtg"}
        r = SESSION.post(url, json=payload, headers=headers, timeout=30)
        if "BP-XSRF-Token" in SESSION.cookies:
            self.xsrf_token = SESSION.cookies["BP-XSRF-Token"]
        if not self.xsrf_token and "BP-XSRF-Token" in r.headers.get("Set-Cookie", ""):
            match = re.search(r"BP-XSRF-Token=([^;]+)", r.headers["Set-Cookie"])
            if match:
                self.xsrf_token = match.group(1)
        if not self.xsrf_token:
            raise AuthError("Failed to retrieve XSRF token.")
        SESSION.cookies.set(
            "BP-XSRF-Token",
            self.xsrf_token,
            domain="enlighten.enphaseenergy.com",
            path="/",
        )
        _LOGGER.debug("[Enphase] XSRF token updated.")

    def _ensure_tokens(self, force_refresh=False):
        """Ensure JWT/XSRF tokens are present and valid."""
        if not self._cache_loaded:
            self._load_cache()

        needs_login = force_refresh or not self._jwt_valid()
        if needs_login or not self._cookies_present():
            _LOGGER.info("[Enphase] Refreshing authentication tokens.")
            self._login()
        else:
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
        return bool(SESSION.cookies)

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
        except Exception:
            return ""

    def _discover_ids(self) -> None:
        """Auto-discover numeric battery/site ID and user ID."""
        final_url = SESSION.get(
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
        app_data = SESSION.get(app_url, timeout=30).json()
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
    # DATA
    # -------------------------------------------------------------------------

    def battery_settings(self):
        """Fetch current battery configuration."""
        jwt, xsrf = self._ensure_tokens()
        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"batterySettings/{self.battery_id}?userId={self.user_id}&source=enho"
        )
        headers = {
            "content-type": "application/json",
            "e-auth-token": jwt,
            "x-xsrf-token": xsrf,
            "username": str(self.user_id),
            "cookie": f"BP-XSRF-Token={xsrf}",
        }
        r = SESSION.get(url, headers=headers, timeout=30)
        if r.status_code == 403:
            _LOGGER.warning("[Enphase] 403 Forbidden on battery_settings – refreshing XSRF.")
            jwt, xsrf = self._ensure_tokens(force_refresh=True)
            headers["e-auth-token"] = jwt
            headers["x-xsrf-token"] = xsrf
            r = SESSION.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        _LOGGER.debug("[Enphase] Battery settings fetched.")
        return r.json()

    # -------------------------------------------------------------------------
    # ACTIONS (toggles)
    # -------------------------------------------------------------------------

    def set_mode(self, mode: str, enable: bool, start_time: str | None = None, end_time: str | None = None):
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
        headers = {
            "content-type": "application/json",
            "e-auth-token": jwt,
            "x-xsrf-token": xsrf,
            "username": str(self.user_id),
            "origin": "https://battery-profile-ui.enphaseenergy.com",
            "referer": "https://battery-profile-ui.enphaseenergy.com/",
            "cookie": f"BP-XSRF-Token={xsrf}",
        }

        # Payload mapping for each mode type
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
                payload["dtgControl"]["startTime"] = start_time[:5]
                payload["dtgControl"]["endTime"] = end_time[:5]
        elif short_mode == "rbd":
            payload = {"rbdControl": {"enabled": enable}}
        else:
            raise ValueError(f"Unsupported mode: {short_mode}")

        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"batterySettings/{self.battery_id}?userId={self.user_id}&source=enho"
        )

        _LOGGER.debug(
            "[Enphase] set_mode request: url=%s headers=%s payload=%s",
            url,
            {k: v for k, v in headers.items() if k != "e-auth-token"},
            payload,
        )
        r = SESSION.put(url, json=payload, headers=headers, timeout=30)
        _LOGGER.debug(
            "[Enphase] set_mode response: status=%s body=%s",
            r.status_code,
            r.text,
        )
        if r.status_code == 403:
            _LOGGER.warning("[Enphase] 403 Forbidden on set_mode(%s) – refreshing XSRF and retrying", short_mode)
            jwt, xsrf = self._ensure_tokens(force_refresh=True)
            headers["e-auth-token"] = jwt
            headers["x-xsrf-token"] = xsrf
            r = SESSION.put(url, json=payload, headers=headers, timeout=30)
            _LOGGER.debug(
                "[Enphase] set_mode retry response: status=%s body=%s",
                r.status_code,
                r.text,
            )

        if not r.ok:
            _LOGGER.error("[Enphase] set_mode(%s) failed: %s %s", short_mode, r.status_code, r.text)
            r.raise_for_status()

        _LOGGER.info("[Enphase] Mode '%s' set successfully (HTTP %s)", short_mode, r.status_code)
        return True

    # -------------------------------------------------------------------------
    # SCHEDULE MANAGEMENT
    # -------------------------------------------------------------------------

    def get_schedules(self):
        """Return all schedules for this site/battery."""
        jwt, xsrf = self._ensure_tokens()
        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"battery/sites/{self.battery_id}/schedules"
        )
        headers = {
            "content-type": "application/json",
            "e-auth-token": jwt,
            "x-xsrf-token": xsrf,
            "username": str(self.user_id),
            "origin": "https://battery-profile-ui.enphaseenergy.com",
            "referer": "https://battery-profile-ui.enphaseenergy.com/",
            "cookie": f"BP-XSRF-Token={xsrf}",
        }
        r = SESSION.get(url, headers=headers, timeout=30)
        if r.status_code == 403:
            _LOGGER.warning("[Enphase] 403 on get_schedules – refreshing tokens.")
            jwt, xsrf = self._ensure_tokens(force_refresh=True)
            headers["e-auth-token"] = jwt
            headers["x-xsrf-token"] = xsrf
            r = SESSION.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()

    def add_schedule(
        self,
        schedule_type,
        start_time,
        end_time,
        limit,
        days,
        timezone="UTC",
    ):
        """Add a new schedule entry (mirrors your REST command)."""
        schedule_type = str(schedule_type).upper()
        jwt, xsrf = self._ensure_tokens()
        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"battery/sites/{self.battery_id}/schedules"
        )
        headers = {
            "content-type": "application/json",
            "e-auth-token": jwt,
            "x-xsrf-token": xsrf,
            "username": str(self.user_id),
            "origin": "https://battery-profile-ui.enphaseenergy.com",
            "referer": "https://battery-profile-ui.enphaseenergy.com/",
            "cookie": f"BP-XSRF-Token={xsrf}",
        }
        payload = {
            "timezone": timezone or "UTC",
            "startTime": start_time[:5],
            "endTime": end_time[:5],
            "limit": int(limit),
            "scheduleType": schedule_type,
            "days": [int(d) for d in days],
        }
        _LOGGER.info("[Enphase] Adding schedule: %s", payload)
        _LOGGER.debug(
            "[Enphase] add_schedule request: url=%s headers=%s payload=%s",
            url,
            {k: v for k, v in headers.items() if k != "e-auth-token"},
            payload,
        )
        r = SESSION.post(url, json=payload, headers=headers, timeout=30)
        _LOGGER.debug(
            "[Enphase] add_schedule response: status=%s body=%s",
            r.status_code,
            r.text,
        )
        if r.status_code == 403:
            jwt, xsrf = self._ensure_tokens(force_refresh=True)
            headers["e-auth-token"] = jwt
            headers["x-xsrf-token"] = xsrf
            r = SESSION.post(url, json=payload, headers=headers, timeout=30)
            _LOGGER.debug(
                "[Enphase] add_schedule retry response: status=%s body=%s",
                r.status_code,
                r.text,
            )
        r.raise_for_status()
        _LOGGER.info("[Enphase] Schedule added successfully.")
        return r.json()

    def delete_schedule(self, schedule_id):
        """Delete a schedule by ID (mirrors your REST command)."""
        jwt, xsrf = self._ensure_tokens()
        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"battery/sites/{self.battery_id}/schedules/{schedule_id}/delete"
        )
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
            "content-type": "application/json",
            "e-auth-token": jwt,
            "x-xsrf-token": xsrf,
            "username": str(self.user_id),
            "origin": "https://battery-profile-ui.enphaseenergy.com",
            "referer": "https://battery-profile-ui.enphaseenergy.com/",
            "cookie": f"locale=en; BP-XSRF-Token={xsrf};",
            "user-agent": "curl/8.14.1",
        }
        _LOGGER.info("[Enphase] Deleting schedule ID %s", schedule_id)
        _LOGGER.debug(
            "[Enphase] delete_schedule request: url=%s headers=%s",
            url,
            {k: v for k, v in headers.items() if k != "e-auth-token"},
        )
        r = SESSION.post(url, json={}, headers=headers, timeout=30)
        _LOGGER.debug(
            "[Enphase] delete_schedule response: status=%s body=%s",
            r.status_code,
            r.text,
        )
        if r.status_code == 403:
            jwt, xsrf = self._ensure_tokens(force_refresh=True)
            headers["e-auth-token"] = jwt
            headers["x-xsrf-token"] = xsrf
            r = SESSION.post(url, json={}, headers=headers, timeout=30)
            _LOGGER.debug(
                "[Enphase] delete_schedule retry response: status=%s body=%s",
                r.status_code,
                r.text,
            )
        r.raise_for_status()
        _LOGGER.info("[Enphase] Schedule %s deleted successfully.", schedule_id)
        return True

    def validate_schedule(self, schedule_type="dtg", force_opted=False):
        """Validate schedule feasibility (isValid endpoint)."""
        schedule_type = str(schedule_type).upper()
        jwt, xsrf = self._ensure_tokens()
        url = (
            f"https://enlighten.enphaseenergy.com/service/batteryConfig/api/v1/"
            f"battery/sites/{self.battery_id}/schedules/isValid"
        )
        payload = {"scheduleType": schedule_type}
        if schedule_type == "CFG" and force_opted:
            payload["forceScheduleOpted"] = True
        headers = {
            "content-type": "application/json",
            "e-auth-token": jwt,
            "x-xsrf-token": xsrf,
            "username": str(self.user_id),
            "origin": "https://battery-profile-ui.enphaseenergy.com",
            "referer": "https://battery-profile-ui.enphaseenergy.com/",
            "cookie": f"BP-XSRF-Token={xsrf}",
        }
        _LOGGER.debug(
            "[Enphase] validate_schedule request: url=%s headers=%s payload=%s",
            url,
            {k: v for k, v in headers.items() if k != "e-auth-token"},
            payload,
        )
        r = SESSION.post(url, json=payload, headers=headers, timeout=30)
        _LOGGER.debug(
            "[Enphase] validate_schedule response: status=%s body=%s",
            r.status_code,
            r.text,
        )
        r.raise_for_status()
        return r.json()

    # -------------------------------------------------------------------------
    # UTILS
    # -------------------------------------------------------------------------

    def _now_iso(self):
        """Return current UTC time in ISO format (milliseconds precision)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
