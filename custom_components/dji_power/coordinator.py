"""Push-coordinator voor de DJI Power-integratie.

Onze databron is een push-stream (DJI-cloud-MQTT, ~1/s device_osd + device_state),
geen poll. Daarom draait de coordinator zonder update_interval: de eerste refresh gaat
via een REST-GET (_async_update_data), en daarna voedt elke MQTT-push
async_set_updated_data.
"""
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .core.hub import DjiPowerHub

_LOGGER = logging.getLogger(__name__)


class DjiPowerDataUpdateCoordinator(DataUpdateCoordinator):
    """Deelt één DJI-cloud-verbinding (hub) over alle entiteiten."""

    def __init__(self, hass: HomeAssistant, hub: DjiPowerHub) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, always_update=False)
        self.hub = hub
        self._unsub = None
        self.ports = []

    async def _async_update_data(self) -> dict:
        """Initiële/fallback-refresh via REST (draait in een executor-thread)."""
        return await self.hass.async_add_executor_job(self._poll)

    def _poll(self) -> dict:
        self.hub.prime_from_settings()
        return dict(self.hub.state)

    @callback
    def _on_push(self, state: dict) -> None:
        """Wordt aangeroepen vanuit de MQTT-thread; marshalt naar de event-loop."""
        self.hass.loop.call_soon_threadsafe(self.async_set_updated_data, dict(state))

    async def async_start(self) -> None:
        """Ontdek poorten, abonneer op de push-stream en start de MQTT-reader."""
        try:
            self.ports = await self.hass.async_add_executor_job(self.hub.discover_ports)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Poort-discovery faalde: %s", err)
            self.ports = []
        self._unsub = self.hub.subscribe(self._on_push)
        await self.hass.async_add_executor_job(self.hub.start)

    async def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        await self.hass.async_add_executor_job(self.hub.stop)
