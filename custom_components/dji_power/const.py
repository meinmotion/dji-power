"""Constanten voor de DJI Power HA-integratie."""
from homeassistant.const import Platform

DOMAIN = "dji_power"

CONF_MEMBER_TOKEN = "member_token"
CONF_SN = "sn"
CONF_MODE = "mode"
CONF_BLE_ADDRESS = "ble_address"
CONF_PAIR_KEY = "pair_key"
CONF_PAIR_UUID = "pair_uuid"
CONF_KEEP_TOKEN = "keep_token"
CONF_MODEL = "model_name"      # bv. "Power 1000 Mini" (uit de cloud-apparatenlijst)

# Verbindingsmodus. Bestaande entries zonder CONF_MODE zijn cloud.
MODE_CLOUD = "cloud"
MODE_BLE = "bluetooth"

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.LIGHT,
    Platform.SWITCH,
]


def entry_value(entry, key, default=None):
    """Waarde uit entry.options (heeft voorrang) of entry.data."""
    return entry.options.get(key, entry.data.get(key, default))
