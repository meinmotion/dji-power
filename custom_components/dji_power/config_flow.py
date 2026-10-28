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
    CONF_MODEL,
    CONF_PAIR_KEY,
    CONF_PAIR_UUID,
    CONF_SN,
    DOMAIN,
    MODE_BLE,
    MODE_CLOUD,
    entry_value,
)
from .core.devices import BoundDevice, display_model, parse_device_list
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
        if self._token and device.device_type is not None and display_model(device.name):
            data[CONF_MODEL] = display_model(device.name)      # alleen als de naam uit de cloud komt
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
                    stale = {CONF_MEMBER_TOKEN, CONF_PAIR_KEY, CONF_PAIR_UUID}   # opties winnen van data
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates=updates,
                        options={k: v for k, v in entry.options.items() if k not in stale},
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_MEMBER_TOKEN): str}),
            errors=errors,
            description_placeholders={"sn": entry.data[CONF_SN]},
        )


class DjiPowerOptionsFlow(OptionsFlow):
    """Verbindingsmodus, Bluetooth-adres en de cloud-gegevens (token, pair_key) bewerken.

    Het serienummer is de identiteit van het apparaat (alle entiteiten hangen eraan) en is dus
    niet te wijzigen; voor een andere Power voeg je de integratie opnieuw toe. Lege velden laten
    de bewaarde waarde staan. Credentials komen in entry.options (die winnen van entry.data).
    """

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}
        current_mode = entry_value(entry, CONF_MODE, MODE_CLOUD)
        current_addr = entry_value(entry, CONF_BLE_ADDRESS)
        sn = entry.data[CONF_SN]

        if user_input is not None:
            options = dict(entry.options)            # bestaande waarden behouden
            mode = user_input[CONF_MODE]
            address = _norm_address(user_input.get(CONF_BLE_ADDRESS) or current_addr or "")
            new_token = (user_input.get(CONF_MEMBER_TOKEN) or "").strip()
            new_key = (user_input.get(CONF_PAIR_KEY) or "").strip().lower()

            if new_key and not PAIR_KEY_RE.match(new_key):
                errors[CONF_PAIR_KEY] = "invalid_pair_key"
            if new_token and not errors:               # nieuw token: controleren, pair_key verversen
                try:
                    devices = await self.hass.async_add_executor_job(_fetch_devices, new_token)
                except DjiAuthError:
                    errors["base"] = "invalid_auth"
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Token controleren faalde: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    match = next((d for d in devices if d.sn == sn), None)
                    if match is None:
                        errors["base"] = "wrong_account"
                    else:
                        options[CONF_MEMBER_TOKEN] = new_token
                        if display_model(match.name):
                            options[CONF_MODEL] = display_model(match.name)
                        if match.pair_key:
                            options[CONF_PAIR_KEY] = match.pair_key
                        if match.pair_uuid:
                            options[CONF_PAIR_UUID] = match.pair_uuid
            if new_key and not errors:                 # handmatige pair_key wint van de cloud
                options[CONF_PAIR_KEY] = new_key

            token = options.get(CONF_MEMBER_TOKEN) or entry.data.get(CONF_MEMBER_TOKEN)
            pair_key = options.get(CONF_PAIR_KEY) or entry.data.get(CONF_PAIR_KEY)
            if not errors and mode == MODE_BLE and not pair_key and token:
                try:                                   # oude cloud-entry: pair_key alsnog ophalen
                    devices = await self.hass.async_add_executor_job(_fetch_devices, token)
                except DjiAuthError:
                    errors["base"] = "invalid_auth"
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("pair_key ophalen faalde: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    match = next((d for d in devices if d.sn == sn), None)
                    if match and match.pair_key:
                        pair_key = options[CONF_PAIR_KEY] = match.pair_key
                        if match.pair_uuid:
                            options[CONF_PAIR_UUID] = match.pair_uuid
            if not errors:
                if mode == MODE_CLOUD and not token:
                    errors["base"] = "no_token"
                elif mode == MODE_BLE and not pair_key:
                    errors["base"] = "no_pair_key"
                elif mode == MODE_BLE and not MAC_RE.match(address):
                    errors[CONF_BLE_ADDRESS] = "invalid_address"
            if not errors:
                options[CONF_MODE] = mode
                if address:
                    options[CONF_BLE_ADDRESS] = address
                return self.async_create_entry(data=options)

        discovered = _discovered_powers(self.hass)
        default_addr = _best_address(discovered, sn, current_addr)
        has_token = bool(entry_value(entry, CONF_MEMBER_TOKEN))
        has_key = bool(entry_value(entry, CONF_PAIR_KEY))
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
            vol.Optional(CONF_MEMBER_TOKEN): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_PAIR_KEY): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "sn": sn,
                "token_state": "opgeslagen" if has_token else "niet opgeslagen",
                "key_state": "opgeslagen" if has_key else "niet opgeslagen",
            },
        )
