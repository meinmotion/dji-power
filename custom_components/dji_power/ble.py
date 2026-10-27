"""Home Assistant-kant van de Bluetooth-route.

De protocollaag is HA-onafhankelijk (core/ble_async.AsyncBleHub); hier wordt alleen de verbinding
aangeleverd via HA's eigen Bluetooth-stack, zodat lokale adapters én ESPHome-Bluetooth-proxies
werken en we niet botsen met andere Bluetooth-integraties.
"""
import re

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .core.ble_async import AsyncBleHub

# Adverteernaam, bv. 'Power1000Mini-110QPR': modelnaam + '-' + laatste 6 tekens van het SN.
NAME_RE = re.compile(r"^Power\d{3,4}\w*-(?P<suffix>[0-9A-Za-z]{4,8})$")
MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def name_suffix(name: str | None) -> str | None:
    """Laatste SN-tekens uit een adverteernaam, of None als het geen DJI Power is."""
    m = NAME_RE.match(name or "")
    return m.group("suffix").upper() if m else None


def make_hub(hass: HomeAssistant, address: str, pair_key: str, sn: str,
             on_connect_change=None) -> AsyncBleHub:
    async def connect():
        device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
        if device is None:
            raise ConnectionError(f"{address} is niet in bereik van een Bluetooth-adapter of -proxy")
        return await establish_connection(
            BleakClientWithServiceCache, device, f"DJI Power {sn[-6:]}", max_attempts=3
        )

    return AsyncBleHub(connect, pair_key, sn, on_connect_change=on_connect_change)
