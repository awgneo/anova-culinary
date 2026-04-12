"""Switch platform for Anova Precision Ovens."""

from typing import Any
import uuid

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER
from .anova_api.client import AnovaClient
from .anova_api.device import AnovaDevice
from .anova_api.product import AnovaProduct


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anova switch platform."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    
    entities = []
    for device_id, device in client.devices.items():
        if device.product == AnovaProduct.APO:
            entities.extend([
                AnovaSousVideSwitch(client, device),
                AnovaDoorLampSwitch(client, device)
            ])
            
    async_add_entities(entities)


class AnovaSousVideSwitch(SwitchEntity):
    """Sous Vide mode switch for Anova Precision Oven."""

    _attr_has_entity_name = True
    _attr_name = "Sous Vide Mode"
    _attr_icon = "mdi:water-boiler"

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        """Initialize."""
        self._client = client
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_sous_vide"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=device.model,
        )
        self._attr_is_on = False
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
        """Handle updated data from the websocket."""
        if device_id != self._device.id:
            return
            
        state = self._client.get_apo_state(self._device.id)
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
        cook = self._client.get_current_cook(self._device.id)
        if cook and cook.current_stage:
            cook.current_stage.sous_vide = True
            await self._client.play_cook(self._device.id, cook)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        cook = self._client.get_current_cook(self._device.id)
        if cook and cook.current_stage:
            cook.current_stage.sous_vide = False
            await self._client.play_cook(self._device.id, cook)

class AnovaDoorLampSwitch(SwitchEntity):
    """Door Lamp switch for Anova Precision Oven."""

    _attr_has_entity_name = True
    _attr_name = "Door Lamp"

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        """Initialize."""
        self._client = client
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_door_lamp"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=device.model,
        )
        self._attr_is_on = False
        self._remove_cb = None
        self._expected_state = None
        self._expected_state_time = 0.0

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
        """Handle updated data from the websocket."""
        if device_id != self._device.id:
            return
            
        state = self._client.get_apo_state(self._device.id)
        if not state:
            return
            
        # Debounce to prevent UI ghosting: ignore contradicting telemetry for 3 seconds after a command
        import time
        if self._expected_state is not None and (time.time() - self._expected_state_time) < 3.0:
            if state.nodes.door_lamp_on != self._expected_state:
                # The hardware state hasn't caught up yet, maintain our optimistic expected state
                self._attr_is_on = self._expected_state
            else:
                # Hardware caught up early, clear the expectation
                self._expected_state = None
                self._attr_is_on = state.nodes.door_lamp_on
        else:
            self._expected_state = None
            self._attr_is_on = state.nodes.door_lamp_on
            
        self._attr_icon = "mdi:lightbulb-on" if self._attr_is_on else "mdi:lightbulb-off"
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the door lamp on."""
        import time
        self._expected_state = True
        self._expected_state_time = time.time()
        self._attr_is_on = True
        self.async_write_ha_state()
        
        from .anova_api.apo.commands import build_set_lamp_command
        cmd = build_set_lamp_command(self._device, True)
        await self._client.send_command(cmd)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the door lamp off."""
        import time
        self._expected_state = False
        self._expected_state_time = time.time()
        self._attr_is_on = False
        self.async_write_ha_state()
        
        from .anova_api.apo.commands import build_set_lamp_command
        cmd = build_set_lamp_command(self._device, False)
        await self._client.send_command(cmd)
