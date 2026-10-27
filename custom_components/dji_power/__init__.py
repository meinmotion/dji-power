"""DJI Power integratie voor Home Assistant (cloud of Bluetooth)."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .ble import make_hub
from .const import (
    CONF_BLE_ADDRESS,
    CONF_MEMBER_TOKEN,
    CONF_MODE,
    CONF_PAIR_KEY,
    CONF_SN,
    DOMAIN,
    MODE_BLE,
    MODE_CLOUD,
    PLATFORMS,
    entry_value,
)
from .coordinator import DjiPowerDataUpdateCoordinator
from .core.hub import DjiPowerHub

_LOGGER = logging.getLogger(__name__)


def _build_hub(hass: HomeAssistant, entry: ConfigEntry, mode: str):
    sn = entry.data[CONF_SN]
    if mode == MODE_BLE:
        address = entry_value(entry, CONF_BLE_ADDRESS)
        pair_key = entry_value(entry, CONF_PAIR_KEY)
        if not address or not pair_key:
            raise ConfigEntryError("Bluetooth-modus vereist een adres en de pair_key")
        return make_hub(hass, address, pair_key, sn)
    token = entry_value(entry, CONF_MEMBER_TOKEN)
    if not token:
        raise ConfigEntryError("Cloud-modus vereist een member-token")
    return DjiPowerHub(member_token=token, sn=sn, subscribe_events=True)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Zet een DJI Power config-entry op. Bestaande entries zonder modus zijn cloud."""
    mode = entry_value(entry, CONF_MODE, MODE_CLOUD)
    hub = _build_hub(hass, entry, mode)
    coordinator = DjiPowerDataUpdateCoordinator(hass, entry, hub, mode)
    await coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    return True


async def _async_reload_on_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Opties gewijzigd (bv. wisselen cloud/Bluetooth): entry herladen."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Ontlaad een config-entry en stop de databron netjes (BLE koppelt los voor de DJI-app)."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: DjiPowerDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
    return unload_ok
