"""Gedeelde entity-basis voor de DJI Power-integratie."""
from homeassistant.helpers.device_info import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DjiPowerDataUpdateCoordinator


class DjiPowerEntity(CoordinatorEntity[DjiPowerDataUpdateCoordinator]):
    """Basis met device-registratie; alle entiteiten delen één device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DjiPowerDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        sn = coordinator.hub.sn
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sn)},
            name="DJI Power",
            manufacturer="DJI",
            model="Power",
            serial_number=sn,
        )

    @property
    def _state(self) -> dict:
        return self.coordinator.data or {}
