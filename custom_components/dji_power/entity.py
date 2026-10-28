"""Gedeelde entity-basis voor de DJI Power-integratie."""
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DjiPowerDataUpdateCoordinator


class DjiPowerEntity(CoordinatorEntity[DjiPowerDataUpdateCoordinator]):
    """Basis met device-registratie; alle entiteiten delen één device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DjiPowerDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        sn = coordinator.hub.sn
        info = DeviceInfo(
            identifiers={(DOMAIN, sn)},
            name="DJI Power",
            manufacturer="DJI",
            model=coordinator.device_model or "Power",
            serial_number=sn,
        )
        fw = (coordinator.data or {}).get("fw_version")
        if fw:                       # alleen meegeven als bekend: None zou een bestaande waarde wissen
            info["sw_version"] = fw
        self._attr_device_info = info

    @property
    def available(self) -> bool:
        """Bluetooth: onbeschikbaar zonder live verbinding. Cloud: ongewijzigd."""
        return super().available and self.coordinator.is_connected

    @property
    def _state(self) -> dict:
        return self.coordinator.data or {}
