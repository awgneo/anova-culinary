"""Select platform for Anova APO recipes."""

from typing import Any
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER
from .anova_api.client import AnovaClient
from .anova_api.device import AnovaDevice
from .anova_api.product import AnovaProduct
from .anova_api.apo.models import AnovaPOHeatingElement, AnovaPOFanSpeed, AnovaPOTimerTrigger

import hashlib
import uuid


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anova select platform."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    recipes = hass.data[DOMAIN][entry.entry_id]["recipes"]
    
    entities = []
    for device_id, device in client.devices.items():
        if device.product == AnovaProduct.APO:
            entities.extend([
                AnovaHeatingElementSelect(client, device),
                AnovaFanSelect(client, device),
                AnovaTimerStartsSelect(client, device),
            ])
            
    async_add_entities(entities)

class AnovaHeatingElementSelect(SelectEntity):
    """Heating element selector."""

    _attr_has_entity_name = True
    _attr_name = "Heating Element"
    _attr_icon = "mdi:heating-coil"
    _attr_options = ["Top", "Rear", "Bottom", "Top + Rear", "Bottom + Rear", "Top + Bottom"]

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        self._client = client
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_heating_element"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=self._device.name,
            manufacturer=MANUFACTURER,
            model=self._device.model,
        )
        self._attr_current_option = "Rear"
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)
        self._handle_update(self._device.id)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str) -> None:
        if device_id != self._device.id: return
        state = self._client.get_apo_state(device_id)
        if not state or not state.cook: return
        
        self._attr_available = state.is_running
        
        try:
            curr_stage = state.cook.current_stage
            if curr_stage:
                h = curr_stage.heating_elements
                if h == AnovaPOHeatingElement.TOP_BOTTOM: self._attr_current_option = "Top + Bottom"
                elif h == AnovaPOHeatingElement.TOP_REAR: self._attr_current_option = "Top + Rear"
                elif h == AnovaPOHeatingElement.BOTTOM_REAR: self._attr_current_option = "Bottom + Rear"
                elif h == AnovaPOHeatingElement.BOTTOM: self._attr_current_option = "Bottom"
                elif h == AnovaPOHeatingElement.TOP: self._attr_current_option = "Top"
                else: self._attr_current_option = "Rear"
        except: pass
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        cook = self._client.get_current_cook(self._device.id)
        if not cook or not cook.current_stage: return
        
        h = AnovaPOHeatingElement.REAR
        if option == "Top + Bottom": h = AnovaPOHeatingElement.TOP_BOTTOM
        elif option == "Top + Rear": h = AnovaPOHeatingElement.TOP_REAR
        elif option == "Bottom + Rear": h = AnovaPOHeatingElement.BOTTOM_REAR
        elif option == "Bottom": h = AnovaPOHeatingElement.BOTTOM
        elif option == "Top": h = AnovaPOHeatingElement.TOP

        cook.current_stage.heating_elements = h
        await self._client.play_cook(self._device.id, cook)

class AnovaFanSelect(SelectEntity):
    """Fan speed selector."""

    _attr_has_entity_name = True
    _attr_name = "Fan"
    _attr_icon = "mdi:fan"
    _attr_options = ["Off", "Low", "Medium", "High"]

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        self._client = client
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_fan"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=self._device.name,
            manufacturer=MANUFACTURER,
            model=self._device.model,
        )
        self._attr_current_option = "High"
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)
        self._handle_update(self._device.id)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str) -> None:
        if device_id != self._device.id: return
        state = self._client.get_apo_state(device_id)
        if not state or not state.cook: return
        self._attr_available = state.is_running
        
        try:
            curr_stage = state.cook.current_stage
            if curr_stage:
                f = curr_stage.fan
                if f == AnovaPOFanSpeed.OFF: self._attr_current_option = "Off"
                elif f == AnovaPOFanSpeed.LOW: self._attr_current_option = "Low"
                elif f == AnovaPOFanSpeed.MEDIUM: self._attr_current_option = "Medium"
                else: self._attr_current_option = "High"
        except: pass
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        cook = self._client.get_current_cook(self._device.id)
        if not cook or not cook.current_stage: return
        
        f = AnovaPOFanSpeed.HIGH
        if option == "Off": f = AnovaPOFanSpeed.OFF
        elif option == "Low": f = AnovaPOFanSpeed.LOW
        elif option == "Medium": f = AnovaPOFanSpeed.MEDIUM
        
        cook.current_stage.fan = f
        await self._client.play_cook(self._device.id, cook)


class AnovaTimerStartsSelect(SelectEntity):
    """Timer Trigger logic selector."""

    _attr_has_entity_name = True
    _attr_name = "Timer Starts"
    _attr_icon = "mdi:play-circle-outline"
    _attr_options = ["Immediately", "When Preheated", "Food Detected", "Manually"]

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        self._client = client
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_timer_starts"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=self._device.name,
            manufacturer=MANUFACTURER,
            model=self._device.model,
        )
        self._attr_current_option = "Manually"
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)
        self._handle_update(self._device.id)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str) -> None:
        if device_id != self._device.id: return
        state = self._client.get_apo_state(device_id)
        if not state or not state.cook: return
        self._attr_available = state.is_running
        
        from .anova_api.apo.models import AnovaPOTimer
        try:
            curr_stage = state.cook.current_stage
            if curr_stage:
                if isinstance(curr_stage.advance, AnovaPOTimer):
                    t = curr_stage.advance.trigger
                    if t == AnovaPOTimerTrigger.IMMEDIATELY: self._attr_current_option = "Immediately"
                    elif t == AnovaPOTimerTrigger.PREHEATED: self._attr_current_option = "When Preheated"
                    elif t == AnovaPOTimerTrigger.FOOD_DETECTED: self._attr_current_option = "Food Detected"
                    else: self._attr_current_option = "Manually"
                else:
                    self._attr_current_option = "Manually"
        except: pass
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        cook = self._client.get_current_cook(self._device.id)
        if not cook or not cook.current_stage: return
        
        from .anova_api.apo.models import AnovaPOTimer
        
        t = AnovaPOTimerTrigger.MANUALLY
        if option == "Immediately": t = AnovaPOTimerTrigger.IMMEDIATELY
        elif option == "When Preheated": t = AnovaPOTimerTrigger.PREHEATED
        elif option == "Food Detected": t = AnovaPOTimerTrigger.FOOD_DETECTED
        
        if not isinstance(cook.current_stage.advance, AnovaPOTimer):
            # Safe default fallback if timer was not enabled prior
            cook.current_stage.advance = AnovaPOTimer(duration=0, trigger=t)
        else:
            cook.current_stage.advance.trigger = t
            
        await self._client.play_cook(self._device.id, cook)