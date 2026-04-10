"""Water heater platform for Anova Precision Cookers."""

import uuid
from typing import Any
from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
    STATE_ECO,
    STATE_ELECTRIC,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .anova_lib.client import AnovaClient
from .anova_lib.device import DeviceType
from .anova_lib.apc.models import APCTemperatureUnit


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anova water heater platform."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    
    entities = []
    for device_id, device in client.devices.items():
        if device.type == DeviceType.APC:
            entities.append(AnovaCooker(client, device_id, device.name, device.model))
            
    async_add_entities(entities)


class AnovaCooker(WaterHeaterEntity):
    """Representation of an Anova Precision Cooker."""

    _attr_has_entity_name = True
    _attr_name = None  # Using device name
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )
    _attr_operation_list = [STATE_ELECTRIC, STATE_ECO]  # Eco = Idle/stopped, Electric = Cooking

    def __init__(self, client: AnovaClient, device_id: str, name: str, model: str) -> None:
        """Initialize the water heater."""
        self._client = client
        self._device_id = device_id
        self._attr_unique_id = f"anova_apc_{device_id}"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="Anova",
            model=model,
        )
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self._remove_cb = self._client.register_callback(self._handle_update)
        # Force initial state parsing if we missed it
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
            
        state = self._client.get_apc_state(self._device_id)
        if not state:
            return

        self._attr_current_temperature = state.current_temperature
        self._attr_target_temperature = state.target_temperature
        
        if state.unit == APCTemperatureUnit.C:
            self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        else:
            self._attr_temperature_unit = UnitOfTemperature.FAHRENHEIT

        if state.is_running:
            self._attr_current_operation = STATE_ELECTRIC
        else:
            self._attr_current_operation = STATE_ECO

        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get("temperature")
        if temperature is None:
            return

        cmd = {
            "command": "CMD_APC_START",
            "requestId": str(uuid.uuid4()),
            "payload": {
                "cookerId": self._device_id,
                "type": self._attr_device_info.get("model", "unknown"),
                "targetTemperature": temperature,
                "unit": self._attr_temperature_unit,
                "timer": 3600  # Default 1 hr if modifying via HA natively
            }
        }
        await self._client.send_command(cmd)

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set operation mode."""
        if operation_mode == STATE_ELECTRIC:
            cmd = {
                "command": "CMD_APC_START",
                "requestId": str(uuid.uuid4()),
                "payload": {
                    "cookerId": self._device_id,
                    "type": self._attr_device_info.get("model", "unknown"),
                    "targetTemperature": self._attr_target_temperature or 60,
                    "unit": self._attr_temperature_unit,
                    "timer": 3600
                }
            }
        else:
            cmd = {
                "command": "CMD_APC_STOP",
                "requestId": str(uuid.uuid4()),
                "payload": {
                    "cookerId": self._device_id,
                    "type": self._attr_device_info.get("model", "unknown"),
                }
            }
        await self._client.send_command(cmd)
