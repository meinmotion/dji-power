"""Binary-sensor-platform (laadt-status) voor de DJI Power-integratie."""
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DjiPowerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DjiPowerChargingSensor(coordinator)])


class DjiPowerChargingSensor(DjiPowerEntity, BinarySensorEntity):
    _attr_translation_key = "charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.hub.sn}_charging"

    @property
    def is_on(self) -> bool:
        return self._state.get("charging") == "on"
