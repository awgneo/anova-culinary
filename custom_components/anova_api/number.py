"""Number platform for Anova Precision Ovens."""

from typing import Any
import uuid

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .anova_lib.client import AnovaClient
from .anova_lib.device import DeviceType
from .anova_lib.apo.models import APOTimer, APOTimerTrigger


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anova number platform."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    
    entities = []
    for device_id, device in client.devices.items():
        if device.type == DeviceType.APO:
            entities.extend([
                AnovaSteamPercentage(client, device_id, device.name, device.model),
                AnovaTimerTarget(client, device_id, device.name, device.model),
            ])
            
    async_add_entities(entities)


class AnovaSteamPercentage(NumberEntity):
    """Steam percentage slider for Anova APO."""

    _attr_has_entity_name = True
    _attr_name = "Steam Percentage"
    _attr_icon = "mdi:weather-partly-rainy"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1

    def __init__(self, client: AnovaClient, device_id: str, name: str, model: str) -> None:
        self._client = client
        self._device_id = device_id
        self._attr_unique_id = f"anova_apo_{device_id}_steam"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)})
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)
        self._handle_update(self._device_id, {})

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str, payload: dict) -> None:
        if device_id != self._device_id: return
        state = self._client.get_apo_state(device_id)
        if not state or not state.cook: return
        
        try:
            curr_stage = state.cook.current_stage
            if curr_stage:
                # If dry mode, steam should be effectively 0 in UI? The transpiler handles setting steam in dry to 0 sometimes.
                self._attr_native_value = curr_stage.steam
                self.async_write_ha_state()
        except: pass

    async def async_set_native_value(self, value: float) -> None:
        cook = self._client.get_current_cook(self._device_id)
        if cook and cook.current_stage:
            cook.current_stage.steam = int(value)
            await self._client.play_cook(self._device_id, cook)


class AnovaTimerTarget(NumberEntity):
    """Timer duration slider in minutes."""

    _attr_has_entity_name = True
    _attr_name = "Timer"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 1440
    _attr_native_step = 1

    def __init__(self, client: AnovaClient, device_id: str, name: str, model: str) -> None:
        self._client = client
        self._device_id = device_id
        self._attr_unique_id = f"anova_apo_{device_id}_timer"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)})
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)
        self._handle_update(self._device_id, {})

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str, payload: dict) -> None:
        if device_id != self._device_id: return
        state = self._client.get_apo_state(device_id)
        if not state or not state.cook: return
        
        try:
            curr_stage = state.cook.current_stage
            if curr_stage and isinstance(curr_stage.advance, APOTimer):
                self._attr_native_value = int(curr_stage.advance.duration / 60.0) # show minutes
                self.async_write_ha_state()
        except: pass

    async def async_set_native_value(self, value: float) -> None:
        cook = self._client.get_current_cook(self._device_id)
        if cook and cook.current_stage:
            # We assume a manual trigger for simple slider adjustments!
            cook.current_stage.advance = APOTimer(duration=int(value * 60), trigger=APOTimerTrigger.MANUALLY)
            await self._client.play_cook(self._device_id, cook)


