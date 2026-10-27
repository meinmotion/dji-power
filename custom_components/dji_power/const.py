"""Constanten voor de DJI Power HA-integratie."""
from homeassistant.const import Platform

DOMAIN = "dji_power"

CONF_MEMBER_TOKEN = "member_token"
CONF_SN = "sn"

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.LIGHT,
    Platform.SWITCH,
]
