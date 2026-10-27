"""DJI Power integratie voor Home Assistant."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_MEMBER_TOKEN, CONF_SN, DOMAIN, PLATFORMS
from .coordinator import DjiPowerDataUpdateCoordinator
from .core.hub import DjiPowerHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Zet een DJI Power config-entry op."""
    hub = DjiPowerHub(
        member_token=entry.data[CONF_MEMBER_TOKEN],
        sn=entry.data[CONF_SN],
        subscribe_events=True,
    )
    coordinator = DjiPowerDataUpdateCoordinator(hass, hub)
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Ontlaad een config-entry en stop de MQTT-reader netjes."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: DjiPowerDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_stop()
    return unload_ok
