"""Number-platform (instelbare percentages) voor de DJI Power-integratie.

Cloud-only: charge_limit zit niet in het BLE-protocol dat we hebben gereverse-engineerd
(alleen lamp en poorten zijn daar bekend, zie core/ble_protocol.py). In Bluetooth-modus wordt
dit platform dus niet opgezet.
"""
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODE_CLOUD
from .entity import DjiPowerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.mode != MODE_CLOUD:
        return
    async_add_entities([DjiPowerChargeLimit(coordinator)])


class DjiPowerChargeLimit(DjiPowerEntity, NumberEntity):
    """Laadlimiet (%): het device stopt (naar verwachting) met laden boven deze grens.

    Grenzen 50-100% zijn een AANNAME, niet onafhankelijk bevestigd als harde DJI-limiet (wel
    gebruikt als conservatieve default in een vergelijkbaar reverse-engineering-project,
    hiromo/ha-dji-power-bt, dat charge_limit via BLE i.p.v. REST instelt). Zie
    dji_power.control.set_charge_limit voor wat wél en niet met hardware geverifieerd is.
    """

    _attr_translation_key = "charge_limit"
    _attr_native_min_value = 50
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:battery-arrow-up-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.hub.sn}_charge_limit"

    @property
    def native_value(self) -> float | None:
        return self._state.get("charge_limit_pct")

    async def async_set_native_value(self, value: float) -> None:
        await self.hass.async_add_executor_job(self.coordinator.hub.set_charge_limit, int(value))
        await self.coordinator.async_request_refresh()
