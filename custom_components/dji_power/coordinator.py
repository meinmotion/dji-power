"""Push-coordinator voor de DJI Power-integratie.

Onze databron is een push-stream, geen poll: ofwel de DJI-cloud-MQTT (~1/s device_osd +
device_state, via DjiPowerHub), ofwel een directe Bluetooth-verbinding (AsyncBleHub, ~1/s
telemetrie). De coordinator draait daarom zonder update_interval en verbergt het verschil voor
de entiteiten: die lezen `data` en sturen via async_set_light/async_set_port.

Cloud: de eerste refresh gaat via een REST-GET (_async_update_data), daarna voedt elke
MQTT-push async_set_updated_data. Bluetooth: de hub draait als achtergrondtaak en de eerste
push levert de initiële data.
"""
import asyncio
import contextlib
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_MODEL, CONF_PAIR_UUID, DOMAIN, MODE_BLE, MODE_CLOUD, entry_value
from .core.devices import display_model, model_from_adv_name, parse_device_list
from .core.rest import DjiAuthError

_LOGGER = logging.getLogger(__name__)

BLE_FIRST_DATA_TIMEOUT = 25      # s: wachten op de eerste push na het verbinden
BLE_STOP_TIMEOUT = 5             # s: wachten tot de BLE-taak netjes afsluit


class DjiPowerDataUpdateCoordinator(DataUpdateCoordinator):
    """Deelt één databron (cloud-hub of BLE-hub) over alle entiteiten."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub, mode: str) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry, always_update=False)
        self.hub = hub
        self.mode = mode
        self.ports = []
        self.device_model: str | None = None      # voor de device-info; None = "Power"
        self._applied_fw: str | None = None
        self._unsub = None
        self._ble_task: asyncio.Task | None = None
        if mode == MODE_CLOUD:
            hub.reader.on_auth_error = self._on_auth_error
        else:
            hub.on_connect_change = self._on_connect_change

    # ---- beschikbaarheid ----
    @property
    def is_connected(self) -> bool:
        """Cloud: gedrag ongewijzigd (altijd beschikbaar). Bluetooth: alleen met live verbinding."""
        return True if self.mode == MODE_CLOUD else bool(self.hub.connected)

    # ---- cloud-REST (initiële/fallback-refresh) ----
    async def _async_update_data(self) -> dict:
        if self.mode == MODE_BLE:
            return dict(self.hub.state)
        try:
            return await self.hass.async_add_executor_job(self._poll)
        except DjiAuthError as err:
            raise ConfigEntryAuthFailed("DJI member-token ongeldig of verlopen") from err

    def _poll(self) -> dict:
        self.hub.prime_from_settings()
        return dict(self.hub.state)

    # ---- push ----
    @callback
    def _on_push(self, state: dict) -> None:
        """Aangeroepen vanuit de MQTT-thread of BLE-callback; marshalt naar de event-loop."""
        self.hass.loop.call_soon_threadsafe(self._apply_push, dict(state))

    @callback
    def _apply_push(self, state: dict) -> None:
        self.async_set_updated_data(state)
        self._sync_firmware(state)

    @callback
    def _sync_firmware(self, state: dict) -> None:
        """De firmwareversie kan na het aanmaken van de entiteiten pas binnenkomen (Bluetooth)."""
        fw = state.get("fw_version")
        if not fw or fw == self._applied_fw:
            return
        device = dr.async_get(self.hass).async_get_device(identifiers={(DOMAIN, self.hub.sn)})
        if device is not None:
            dr.async_get(self.hass).async_update_device(device.id, sw_version=fw)
            self._applied_fw = fw

    @callback
    def _on_connect_change(self, _connected: bool) -> None:
        self.hass.loop.call_soon_threadsafe(self.async_update_listeners)

    @callback
    def _on_auth_error(self) -> None:
        """Token verlopen terwijl we draaien (MQTT-thread): start de reauth-flow."""
        self.hass.loop.call_soon_threadsafe(self.config_entry.async_start_reauth, self.hass)

    # ---- levenscyclus ----
    async def async_setup(self) -> None:
        """Eerste data + start van de push-stream. Gooit ConfigEntry{AuthFailed,NotReady}."""
        if self.mode == MODE_BLE:
            await self._start_ble()
        else:
            await self.async_config_entry_first_refresh()
            await self._start_cloud()

    async def _resolve_model(self) -> None:
        """Modelnaam voor de device-info: opgeslagen waarde, anders cloud-lijst, anders adv-naam."""
        model = entry_value(self.config_entry, CONF_MODEL)
        if not model and self.mode == MODE_CLOUD:
            def fetch():
                try:
                    return parse_device_list(self.hub.rest.get_device_list())
                except Exception:  # noqa: BLE001
                    return []
            for dev in await self.hass.async_add_executor_job(fetch):
                if dev.sn == self.hub.sn:
                    model = display_model(dev.name)
        if not model:
            model = model_from_adv_name(entry_value(self.config_entry, CONF_PAIR_UUID))
        self.device_model = model

    async def _start_cloud(self) -> None:
        await self._resolve_model()
        try:
            self.ports = await self.hass.async_add_executor_job(self.hub.discover_ports)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Poort-discovery faalde: %s", err)
            self.ports = []
        self._unsub = self.hub.subscribe(self._on_push)
        await self.hass.async_add_executor_job(self.hub.start)

    async def _start_ble(self) -> None:
        await self._resolve_model()
        first = asyncio.Event()

        def on_first(_state):
            self.hass.loop.call_soon_threadsafe(first.set)

        unsub_first = self.hub.subscribe(on_first)
        self._unsub = self.hub.subscribe(self._on_push)
        self._ble_task = self.config_entry.async_create_background_task(
            self.hass, self.hub.run(), f"{DOMAIN}_ble_{self.hub.sn}"
        )
        try:
            await asyncio.wait_for(first.wait(), BLE_FIRST_DATA_TIMEOUT)
        except asyncio.TimeoutError:
            await self.async_stop()
            raise ConfigEntryNotReady(
                "Geen Bluetooth-data van de Power. Staat hij aan, binnen bereik van een adapter of "
                "proxy en is de DJI-app niet verbonden?"
            ) from None
        finally:
            unsub_first()
        self.ports = self.hub.discover_ports()
        self._apply_push(dict(self.hub.state))

    async def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        if self.mode == MODE_BLE:
            await self.hub.stop()
            if self._ble_task is not None:
                with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    await asyncio.wait_for(self._ble_task, BLE_STOP_TIMEOUT)
                self._ble_task = None
        else:
            await self.hass.async_add_executor_job(self.hub.stop)

    # ---- besturing (zelfde aanroep voor cloud en Bluetooth) ----
    async def async_set_light(self, mode: str) -> None:
        if self.mode == MODE_BLE:
            await self.hub.set_light(mode)
        else:
            await self.hass.async_add_executor_job(self.hub.set_light, mode)

    async def async_set_light_brightness(self, pct: int) -> None:
        if self.mode == MODE_BLE:
            await self.hub.set_light_brightness(pct)
        else:
            await self.hass.async_add_executor_job(self.hub.set_light_brightness, pct)

    async def async_set_port(self, ptype: int, seq: int, on: bool) -> None:
        if self.mode == MODE_BLE:
            await self.hub.set_port(ptype, seq, on)
        else:
            await self.hass.async_add_executor_job(self.hub.set_port, ptype, seq, on)
