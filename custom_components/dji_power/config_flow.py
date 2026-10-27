"""Config-flow voor de DJI Power-integratie."""
import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_MEMBER_TOKEN, CONF_SN, DOMAIN
from .core.rest import RestClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MEMBER_TOKEN): str,
        vol.Required(CONF_SN): str,
    }
)


class DjiPowerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Vraagt member-token + serienummer en valideert via de cloud-REST-API."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            sn = user_input[CONF_SN].strip()
            token = user_input[CONF_MEMBER_TOKEN].strip()
            await self.async_set_unique_id(sn)
            self._abort_if_unique_id_configured()

            client = RestClient(token, sn)
            try:
                await self.hass.async_add_executor_job(client.get_settings)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Validatie faalde: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"DJI Power {sn}",
                    data={CONF_MEMBER_TOKEN: token, CONF_SN: sn},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
