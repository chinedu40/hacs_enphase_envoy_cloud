"""Constants for Enphase Envoy Cloud Control integration."""

import logging

__all__ = [
    "BASE_URL",
    "BATTERY_URL",
    "CACHE_DIR",
    "CACHE_FILE",
    "CONF_BATTERY_ID",
    "CONF_EMAIL",
    "CONF_PASSWORD",
    "CONF_SITE_ID",
    "CONF_USER_ID",
    "DEFAULT_POLL_INTERVAL",
    "DEVICE_KIND_BATTERY",
    "DEVICE_KIND_SCHEDULE_EDITOR",
    "DOMAIN",
    "JWT_URL",
    "LOGGER",
    "LOGIN_URL",
    "NAME",
    "SCHEDULE_URL",
    "VERSION",
]

DOMAIN = "enphase_envoy_cloud_control"
NAME = "Enphase Envoy Cloud Control"
VERSION = "1.7.0"
DEVICE_KIND_BATTERY = "battery"
DEVICE_KIND_SCHEDULE_EDITOR = "schedule_editor"

# Common Enphase API URLs
BASE_URL = "https://enlighten.enphaseenergy.com"
LOGIN_URL = f"{BASE_URL}/login"
JWT_URL = f"{BASE_URL}/app-api/jwt_token.json"
SCHEDULE_URL = f"{BASE_URL}/service/batteryConfig/api/v1/battery/sites"
BATTERY_URL = f"{BASE_URL}/service/batteryConfig/api/v1/batterySettings"

# Create a shared logger for the integration
LOGGER = logging.getLogger(__package__)

# Config keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_USER_ID = "user_id"
CONF_BATTERY_ID = "battery_id"
CONF_SITE_ID = "site_id"

# Defaults
DEFAULT_POLL_INTERVAL = 30

# Cache path
CACHE_DIR = ".cache"
CACHE_FILE = f"{CACHE_DIR}/auth.json"
