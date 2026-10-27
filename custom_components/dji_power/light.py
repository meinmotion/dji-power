"""Light-platform (de ingebouwde lamp) voor de DJI Power-integratie.

De lamp heeft drie standen (enum Mya): 1=uit, 2=aan (helderheid pwm_v 10-100%), 3=SOS.
SOS wordt als light-effect aangeboden.
"""
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DjiPowerEntity

EFFECT_NORMAL = "normaal"
EFFECT_SOS = "SOS"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DjiPowerLight(coordinator)])


class DjiPowerLight(DjiPowerEntity, LightEntity):
    _attr_translation_key = "light"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = [EFFECT_NORMAL, EFFECT_SOS]
    _attr_icon = "mdi:lightbulb"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.hub.sn}_light"

    @property
    def is_on(self) -> bool:
        return self._state.get("light_on") == "on"

    @property
    def brightness(self) -> int | None:
        pct = self._state.get("light_pct")
        if pct is None:
            return None
        return round(int(pct) * 255 / 100)

    @property
    def effect(self) -> str | None:
        return self._state.get("light_fx")

    async def async_turn_on(self, **kwargs) -> None:
        coordinator = self.coordinator
        if ATTR_EFFECT in kwargs:
            mode = "sos" if kwargs[ATTR_EFFECT] == EFFECT_SOS else "on"
            await coordinator.async_set_light(mode)
        elif ATTR_BRIGHTNESS in kwargs:
            pct = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
            await coordinator.async_set_light_brightness(pct)
        else:
            await coordinator.async_set_light("on")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_light("off")
        await self.coordinator.async_request_refresh()
