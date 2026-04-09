"""Climate platform for Anova Precision Ovens."""

import uuid
from typing import Any
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .anova_lib.client import AnovaClient
from .anova_lib.models import DeviceType


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anova climate platform."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    
    entities = []
    for device_id, device in client.devices.items():
        if device.type == DeviceType.APO:
            entities.append(AnovaOven(client, device_id, device.name, device.model))
            
    async_add_entities(entities)


class AnovaOven(ClimateEntity):
    """Representation of an Anova Precision Oven."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, client: AnovaClient, device_id: str, name: str, model: str) -> None:
        """Initialize the climate entity."""
        self._client = client
        self._device_id = device_id
        self._model = model
        self._attr_unique_id = f"anova_apo_{device_id}"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="Anova",
            model=model,
        )
        self._attr_current_temperature = 0.0
        self._attr_target_temperature = 0.0
        self._attr_hvac_mode = HVACMode.OFF
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
        if not state:
            return

        # Assuming the raw payload has nodes.temperatureBulbs.dry.current
        # We parse speculatively based on typical structure
        try:
            curr = state.raw_state.get("payload", {}).get("temperatureBulbs", {}).get("dry", {}).get("current", {}).get("celsius")
            targ = state.raw_state.get("payload", {}).get("temperatureBulbs", {}).get("dry", {}).get("setpoint", {}).get("celsius")
            if curr is not None:
                self._attr_current_temperature = curr
            if targ is not None:
                self._attr_target_temperature = targ
        except Exception:
            pass
            
        if state.is_running:
            self._attr_hvac_mode = HVACMode.HEAT
        else:
            self._attr_hvac_mode = HVACMode.OFF

        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
            
        # Simplest start command with new target temp
        cmd = {
            "command": "CMD_APO_START",
            "requestId": str(uuid.uuid4()),
            "payload": {
                "id": self._device_id,
                "type": "CMD_APO_START",
                "payload": {
                    "cookId": str(uuid.uuid4()),
                    "cookerId": self._device_id,
                    "type": self._model,
                    "stages": [{
                        "id": str(uuid.uuid4()),
                        "do": {
                            "type": "cook",
                            "temperatureBulbs": {
                                "mode": "dry",
                                "dry": {"setpoint": {"celsius": temperature}}
                            }
                        }
                    }]
                }
            }
        }
        await self._client.send_command(cmd)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            cmd = {
                "command": "CMD_APO_STOP",
                "requestId": str(uuid.uuid4()),
                "payload": {
                    "id": self._device_id,
                    "type": "CMD_APO_STOP"
                }
            }
            await self._client.send_command(cmd)
        elif hvac_mode == HVACMode.HEAT:
            if self._attr_target_temperature:
                await self.async_set_temperature(temperature=self._attr_target_temperature)
