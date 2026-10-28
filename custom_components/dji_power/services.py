"""Service `dji_power.list_bound_devices`: toont de cloud-apparatenlijst (SN, pair_uuid,
pair_key) voor een al geconfigureerde entry. Vervangt het losse `tools/list_pairkeys.py`
binnen Home Assistant: gebruikt het member-token dat al in de config-entry zit (geen
.dji_secrets, geen signing key, geen login-flow — alleen de bestaande, geautoriseerde
RestClient.get_device_list()).

Alleen bruikbaar in cloud-modus: Bluetooth-only entries hebben geen hub.rest.
"""
import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN, MODE_CLOUD
from .core.devices import parse_device_list
from .core.rest import DjiAuthError
from .coordinator import DjiPowerDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_LIST_BOUND_DEVICES = "list_bound_devices"

_SCHEMA = vol.Schema({vol.Required("device_id"): cv.string})


def _coordinator_for_device(hass: HomeAssistant, device_id: str) -> DjiPowerDataUpdateCoordinator:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise HomeAssistantError(f"Onbekend apparaat: {device_id}")
    entries = hass.data.get(DOMAIN, {})
    entry_id = next((eid for eid in device.config_entries if eid in entries), None)
    if entry_id is None:
        raise HomeAssistantError("Dit apparaat heeft geen DJI Power config-entry")
    return entries[entry_id]


async def _async_list_bound_devices(hass: HomeAssistant, call: ServiceCall) -> dict:
    coordinator = _coordinator_for_device(hass, call.data["device_id"])
    if coordinator.mode != MODE_CLOUD:
        raise HomeAssistantError(
            "Alleen beschikbaar in cloud-modus (vereist een member-token; "
            "deze entry gebruikt Bluetooth)"
        )

    def fetch():
        return parse_device_list(coordinator.hub.rest.get_device_list())

    try:
        devices = await hass.async_add_executor_job(fetch)
    except DjiAuthError as err:
        raise HomeAssistantError("Member-token ongeldig of verlopen") from err

    return {
        "devices": [
            {
                "sn": d.sn,
                "name": d.name,
                "online": d.online,
                "pair_uuid": d.pair_uuid,
                "pair_key": d.pair_key,
            }
            for d in devices
        ]
    }


def async_register(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_LIST_BOUND_DEVICES):
        return

    async def handler(call: ServiceCall) -> dict:
        return await _async_list_bound_devices(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_LIST_BOUND_DEVICES, handler,
        schema=_SCHEMA, supports_response=SupportsResponse.ONLY,
    )
