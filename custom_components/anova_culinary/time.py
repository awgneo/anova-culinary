"""Time platform for Anova Precision Ovens."""

from datetime import time
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER
from .anova_api.client import AnovaClient
from .anova_api.device import AnovaDevice
from .anova_api.product import AnovaProduct
from .anova_api.apo.models import AnovaPOTimer, AnovaPOTimerTrigger

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anova time platform."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    
    entities = []
    for device_id, device in client.devices.items():
        if device.product == AnovaProduct.APO:
            entities.append(AnovaTimerTime(client, device))
            
    async_add_entities(entities)

class AnovaTimerTime(TimeEntity):
    """Timer target setter for Anova APO."""

    _attr_has_entity_name = True
    _attr_name = "Timer"
    _attr_icon = "mdi:timer-outline"

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        """Initialize."""
        self._client = client
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_timer_time"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=device.model,
        )
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self._remove_cb = self._client.register_callback(self._handle_update)
        self._handle_update(self._device.id)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up."""
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
            if curr_stage and isinstance(curr_stage.advance, AnovaPOTimer):
                duration_s = curr_stage.advance.duration
                h = duration_s // 3600
                m = (duration_s % 3600) // 60
                s = duration_s % 60
                
                if h > 23:
                    h = 23
                    m = 59
                    s = 59
                    
                self._attr_native_value = time(hour=int(h), minute=int(m), second=int(s))
            else:
                self._attr_native_value = None
        except: pass
        self.async_write_ha_state()

    async def async_set_value(self, value: time) -> None:
        """Update the timer."""
        cook = self._client.get_current_cook(self._device.id)
        if cook and cook.current_stage:
            total_s = (value.hour * 3600) + (value.minute * 60) + value.second
            cook.current_stage.advance = AnovaPOTimer(duration=total_s, trigger=AnovaPOTimerTrigger.MANUALLY)
            await self._client.play_cook(self._device.id, cook)
