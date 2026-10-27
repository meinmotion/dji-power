"""Config-flow voor de DJI Power-integratie.

Aanmelden gaat met alleen het member-token: de DJI-cloud geeft daarna per gebonden apparaat het
serienummer én de Bluetooth-koppelsleutel (pair_key). Daarna kies je de verbindingsmodus:

  cloud      via de DJI-cloud (MQTT + REST)
  bluetooth  rechtstreeks met de Power (geen cloud nodig na het aanmelden)

Zonder token kan Bluetooth ook handmatig (serienummer + pair_key). De modus is later te wisselen
via de opties; een verlopen token start de reauth-flow. Bestaande entries (token + SN) blijven
cloud en werken ongewijzigd.
"""
import logging
import re

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .ble import MAC_RE, name_suffix
from .const import (
    CONF_BLE_ADDRESS,
    CONF_KEEP_TOKEN,
    CONF_MEMBER_TOKEN,
    CONF_MODE,
    CONF_PAIR_KEY,
    CONF_PAIR_UUID,
    CONF_SN,
    DOMAIN,
    MODE_BLE,
    MODE_CLOUD,
    entry_value,
)
from .core.devices import BoundDevice, parse_device_list
from .core.rest import DjiAuthError, RestClient

_LOGGER = logging.getLogger(__name__)

PAIR_KEY_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def _fetch_devices(token: str) -> list[BoundDevice]:
    """Blokkerend: apparatenlijst ophalen met alleen het token (SN is hier nog niet nodig)."""
    return parse_device_list(RestClient(token, "").get_device_list())


def _norm_address(address: str) -> str:
    return (address or "").strip().upper()


def _discovered_powers(hass) -> dict[str, str]:
    """Adres -> adverteernaam van alle DJI Power's die HA's Bluetooth nu ziet."""
    return {
        info.address: info.name
        for info in bluetooth.async_discovered_service_info(hass, connectable=True)
        if name_suffix(info.name)
    }


def _address_selector(discovered: dict[str, str]) -> selector.SelectSelector:
    """Keuzelijst van gevonden Power's; een adres typen kan ook (custom_value)."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=a, label=f"{n} ({a})") for a, n in discovered.items()
            ],
            custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _best_address(discovered: dict[str, str], sn: str, preferred: str | None = None) -> str | None:
    """Voorkeursadres, anders het adres waarvan de naam bij het SN past."""
    if preferred:
        return preferred
    suffix = sn[-6:].upper()
    return next((a for a, n in discovered.items() if name_suffix(n) == suffix), None)


class DjiPowerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._token: str | None = None
        self._devices: list[BoundDevice] = []
        self._device: BoundDevice | None = None
        self._suggest_address: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return DjiPowerOptionsFlow()

    # ---- start: token of handmatig ----
    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["token", "manual_ble"])

    async def async_step_token(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_MEMBER_TOKEN].strip()
            try:
                devices = await self.hass.async_add_executor_job(_fetch_devices, token)
            except DjiAuthError:
                errors["base"] = "invalid_auth"
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Apparatenlijst ophalen faalde: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    self._token, self._devices = token, devices
                    if len(devices) == 1:
                        return await self._select(devices[0])
                    return await self.async_step_device()
        return self.async_show_form(
            step_id="token",
            data_schema=vol.Schema({vol.Required(CONF_MEMBER_TOKEN): str}),
            errors=errors,
        )

    async def async_step_device(self, user_input=None) -> ConfigFlowResult:
        by_sn = {d.sn: d for d in self._devices}
        if user_input is not None:
            return await self._select(by_sn[user_input[CONF_SN]])
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {vol.Required(CONF_SN): vol.In({d.sn: d.label for d in self._devices})}
            ),
        )

    async def _select(self, device: BoundDevice) -> ConfigFlowResult:
        await self.async_set_unique_id(device.sn)
        self._abort_if_unique_id_configured()
        self._device = device
        if not device.pair_key:                      # gedeeld apparaat: geen Bluetooth mogelijk
            return await self.async_step_mode_cloud()
        return self.async_show_menu(step_id="mode", menu_options=["mode_cloud", "mode_ble"])

    async def async_step_mode(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="mode", menu_options=["mode_cloud", "mode_ble"])

    async def async_step_mode_cloud(self, user_input=None) -> ConfigFlowResult:
        return self._create(MODE_CLOUD)

    async def async_step_mode_ble(self, user_input=None) -> ConfigFlowResult:
        return await self.async_step_bluetooth_device()

    # ---- handmatig: alleen Bluetooth, zonder token ----
    async def async_step_manual_ble(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            sn = user_input[CONF_SN].strip().upper()
            key = user_input[CONF_PAIR_KEY].strip().lower()
            if not PAIR_KEY_RE.match(key):
                errors[CONF_PAIR_KEY] = "invalid_pair_key"
            else:
                await self.async_set_unique_id(sn)
                self._abort_if_unique_id_configured()
                self._device = BoundDevice(sn=sn, name="DJI Power", pair_key=key)
                self._token = None
                return await self.async_step_bluetooth_device()
        return self.async_show_form(
            step_id="manual_ble",
            data_schema=vol.Schema(
                {vol.Required(CONF_SN): str, vol.Required(CONF_PAIR_KEY): str}
            ),
            errors=errors,
        )

    # ---- Bluetooth-adres kiezen ----
    async def async_step_bluetooth_device(self, user_input=None) -> ConfigFlowResult:
        assert self._device is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            address = _norm_address(user_input[CONF_BLE_ADDRESS])
            if not MAC_RE.match(address):
                errors[CONF_BLE_ADDRESS] = "invalid_address"
            else:
                keep = user_input.get(CONF_KEEP_TOKEN, True)
                return self._create(MODE_BLE, address=address, keep_token=keep)

        discovered = _discovered_powers(self.hass)
        default = _best_address(discovered, self._device.sn, self._suggest_address)
        schema: dict = {
            vol.Required(CONF_BLE_ADDRESS, default=default or vol.UNDEFINED): _address_selector(
                discovered
            )
        }
        if self._token:
            schema[vol.Required(CONF_KEEP_TOKEN, default=True)] = bool
        return self.async_show_form(
            step_id="bluetooth_device",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={"sn": self._device.sn, "found": str(len(discovered))},
        )

    # ---- automatische ontdekking (Power adverteert als 'Power1000Mini-<SN-staart>') ----
    async def async_step_bluetooth(self, discovery_info) -> ConfigFlowResult:
        suffix = name_suffix(discovery_info.name)
        if not suffix:
            return self.async_abort(reason="not_supported")
        for entry in self._async_current_entries():
            if entry.data.get(CONF_SN, "")[-len(suffix):].upper() == suffix:
                return self.async_abort(reason="already_configured")
        await self._async_handle_discovery_without_unique_id()
        self._suggest_address = discovery_info.address
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_user()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders=self.context.get("title_placeholders"),
        )

    # ---- aanmaken ----
    def _create(self, mode: str, address: str | None = None, keep_token: bool = True):
        device = self._device
        data = {CONF_SN: device.sn, CONF_MODE: mode}
        if self._token and (mode == MODE_CLOUD or keep_token):
            data[CONF_MEMBER_TOKEN] = self._token
        if device.pair_key:
            data[CONF_PAIR_KEY] = device.pair_key
        if device.pair_uuid:
            data[CONF_PAIR_UUID] = device.pair_uuid
        if address:
            data[CONF_BLE_ADDRESS] = address
        return self.async_create_entry(title=f"DJI Power {device.sn}", data=data)

    # ---- reauth: token verlopen ----
    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_MEMBER_TOKEN].strip()
            try:
                devices = await self.hass.async_add_executor_job(_fetch_devices, token)
            except DjiAuthError:
                errors["base"] = "invalid_auth"
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Reauth faalde: %s", err)
                errors["base"] = "cannot_connect"
            else:
                match = next((d for d in devices if d.sn == entry.data[CONF_SN]), None)
                if match is None:
                    errors["base"] = "wrong_account"
                else:
                    updates = {CONF_MEMBER_TOKEN: token}
                    if match.pair_key:
                        updates[CONF_PAIR_KEY] = match.pair_key
                    if match.pair_uuid:
                        updates[CONF_PAIR_UUID] = match.pair_uuid
                    return self.async_update_reload_and_abort(entry, data_updates=updates)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_MEMBER_TOKEN): str}),
            errors=errors,
            description_placeholders={"sn": entry.data[CONF_SN]},
        )


class DjiPowerOptionsFlow(OptionsFlow):
    """Wisselen tussen cloud en Bluetooth, en het Bluetooth-adres aanpassen."""

    async def _resolve_pair_key(self, errors: dict) -> tuple[str | None, str | None]:
        """pair_key/pair_uuid uit de entry, of (bij een oude cloud-entry) uit de cloud halen."""
        entry = self.config_entry
        pair_key = entry_value(entry, CONF_PAIR_KEY)
        pair_uuid = entry_value(entry, CONF_PAIR_UUID)
        token = entry_value(entry, CONF_MEMBER_TOKEN)
        if pair_key or not token:
            return pair_key, pair_uuid
        try:
            devices = await self.hass.async_add_executor_job(_fetch_devices, token)
        except DjiAuthError:
            errors["base"] = "invalid_auth"
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("pair_key ophalen faalde: %s", err)
            errors["base"] = "cannot_connect"
        else:
            match = next((d for d in devices if d.sn == entry.data[CONF_SN]), None)
            if match is not None:
                return match.pair_key, match.pair_uuid
        return None, None

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}
        current_mode = entry_value(entry, CONF_MODE, MODE_CLOUD)
        current_addr = entry_value(entry, CONF_BLE_ADDRESS)

        if user_input is not None:
            mode = user_input[CONF_MODE]
            address = _norm_address(user_input.get(CONF_BLE_ADDRESS) or current_addr or "")
            options = {CONF_MODE: mode}
            if mode == MODE_CLOUD and not entry_value(entry, CONF_MEMBER_TOKEN):
                errors["base"] = "no_token"
            elif mode == MODE_BLE:
                pair_key, pair_uuid = await self._resolve_pair_key(errors)
                if not errors:
                    if not pair_key:
                        errors["base"] = "no_pair_key"
                    elif not MAC_RE.match(address):
                        errors[CONF_BLE_ADDRESS] = "invalid_address"
                    else:
                        options.update({CONF_PAIR_KEY: pair_key, CONF_BLE_ADDRESS: address})
                        if pair_uuid:
                            options[CONF_PAIR_UUID] = pair_uuid
            if not errors:
                if mode == MODE_CLOUD and address:
                    options[CONF_BLE_ADDRESS] = address      # onthouden voor later terugwisselen
                return self.async_create_entry(data=options)

        discovered = _discovered_powers(self.hass)
        default_addr = _best_address(discovered, entry.data[CONF_SN], current_addr)
        schema = {
            vol.Required(CONF_MODE, default=current_mode): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[MODE_CLOUD, MODE_BLE],
                    translation_key="mode",
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Optional(CONF_BLE_ADDRESS, default=default_addr or vol.UNDEFINED): _address_selector(
                discovered
            ),
        }
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema), errors=errors
        )
