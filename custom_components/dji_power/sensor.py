"""Sensor-platform voor de DJI Power-integratie."""
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DjiPowerEntity

SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="battery_pct", translation_key="battery", native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY, state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="output_w", translation_key="output", native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="input_w", translation_key="input", native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="temp_c", translation_key="temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="remain_min", translation_key="remaining",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION, state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
    ),
    SensorEntityDescription(
        key="light_pct", translation_key="light_brightness",
        native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightbulb",
    ),
    # Cloud-only (geen BLE-tegenhanger): komt alleen uit het volledige settings-object, niet uit
    # de MQTT device_state-push. Welke gear 'actief' is, is afgeleid via dezelfde sw-enum als
    # power_sw (1=aan); het schrijven van ac_chg_gear is bewust niet geïmplementeerd, zie
    # dji_power/normalize.py en control.set_charge_limit voor de onderbouwing.
    SensorEntityDescription(
        key="ac_charge_power_w", translation_key="ac_charge_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower-import", entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(DjiPowerSensor(coordinator, desc) for desc in SENSORS)


class DjiPowerSensor(DjiPowerEntity, SensorEntity):
    def __init__(self, coordinator, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.hub.sn}_{description.key}"

    @property
    def native_value(self):
        return self._state.get(self.entity_description.key)
