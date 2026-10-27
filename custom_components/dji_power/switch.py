"""Switch-platform (de uitgangspoorten) voor de DJI Power-integratie.

De poortenlijst wordt dynamisch ontdekt (coordinator.ports), zodat de entiteiten zich
aanpassen aan het model (1000/1000 Mini/2000/...).
"""
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .core.model import port_key
from .entity import DjiPowerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DjiPowerPortSwitch(coordinator, ptype, seq, name, icon)
        for ptype, seq, name, icon in coordinator.ports
    )


class DjiPowerPortSwitch(DjiPowerEntity, SwitchEntity):
    def __init__(self, coordinator, ptype: int, seq: int, name: str, icon: str) -> None:
        super().__init__(coordinator)
        self._ptype = ptype
        self._seq = seq
        self._key = port_key(ptype, seq)
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{coordinator.hub.sn}_{self._key}"

    @property
    def is_on(self) -> bool:
        return self._state.get(self._key) == "on"

    async def async_turn_on(self, **kwargs) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.hub.set_port, self._ptype, self._seq, True
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.hub.set_port, self._ptype, self._seq, False
        )
        await self.coordinator.async_request_refresh()
