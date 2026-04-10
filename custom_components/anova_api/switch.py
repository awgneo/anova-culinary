"""Switch platform for Anova Precision Ovens."""

from typing import Any
import uuid

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .anova_lib.client import AnovaClient
from .anova_lib.device import DeviceType


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anova switch platform."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    
    entities = []
    for device_id, device in client.devices.items():
        if device.type == DeviceType.APO:
            entities.append(AnovaSousVideSwitch(client, device_id, device.name, device.model))
            
    async_add_entities(entities)


class AnovaSousVideSwitch(SwitchEntity):
    """Sous Vide mode switch for Anova Precision Oven."""

    _attr_has_entity_name = True
    _attr_name = "Sous Vide Mode"
    _attr_icon = "mdi:water-boiler"

    def __init__(self, client: AnovaClient, device_id: str, name: str, model: str) -> None:
        """Initialize."""
        self._client = client
        self._device_id = device_id
        self._model = model
        self._attr_unique_id = f"anova_apo_{device_id}_sous_vide"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="Anova",
            model=model,
        )
        self._attr_is_on = False
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self._remove_cb = self._client.register_callback(self._handle_update)
        self._handle_update(self._device_id, {})

    async def async_will_remove_from_hass(self) -> None:
        """Clean up."""
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str, payload: dict) -> None:
        """Handle updated data from the websocket."""
        if device_id != self._device_id:
            return
            
        state = self._client.get_apo_state(self._device_id)
        if not state or not state.cook:
            return

        try:
            curr_stage = state.cook.current_stage
            if curr_stage:
                self._attr_is_on = curr_stage.sous_vide
                self.async_write_ha_state()
        except Exception:
            pass

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        cook = self._client.get_current_cook(self._device_id)
        if cook and cook.current_stage:
            cook.current_stage.sous_vide = True
            await self._client.play_cook(self._device_id, cook)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        cook = self._client.get_current_cook(self._device_id)
        if cook and cook.current_stage:
            cook.current_stage.sous_vide = False
            await self._client.play_cook(self._device_id, cook)
