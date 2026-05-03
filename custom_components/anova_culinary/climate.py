"""Climate platform for Anova Precision Ovens."""

import uuid
from typing import Any
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
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
    """Set up the Anova climate platform."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    
    entities = []
    for device_id, device in client.devices.items():
        if device.product == AnovaProduct.APO:
            entities.extend([
                AnovaOven(client, device),
                AnovaProbe(client, device),
            ])
            
    async_add_entities(entities)


class AnovaOven(ClimateEntity):
    """Representation of an Anova Precision Oven."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        """Initialize the climate entity."""
        self._client = client
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=device.model,
        )
        self._attr_current_temperature = 0.0
        self._attr_target_temperature = 176.67
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_hvac_action = HVACAction.IDLE
        self._active_mode = "dry"
        self._remove_cb = None

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return 25.0

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        if self._active_mode == "wet":
            return 100.0
        return 250.0

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
            curr_stage = state.cook.current_stage if state.cook else None
            
            if curr_stage:
                self._active_mode = "wet" if curr_stage.sous_vide else "dry"
                
                # Prevent the API from wiping out the target temperature when the oven is idle!
                if curr_stage.temperature >= self.min_temp:
                    self._attr_target_temperature = curr_stage.temperature
                
                if self._active_mode == "wet":
                    self._attr_current_temperature = state.nodes.current_wet_temp
                else:
                    self._attr_current_temperature = state.nodes.current_dry_temp
            else:
                self._active_mode = "dry"
                # Do NOT overwrite _attr_target_temperature to 0.0. Let it retain memory of the last configuration 
                # (or initial __init__ payload) so the unified UI components stay perfectly in place!
                
                self._attr_current_temperature = state.nodes.current_dry_temp
        except Exception:
            pass
            
        if state.is_running:
            self._attr_hvac_mode = HVACMode.HEAT
            self._attr_hvac_action = HVACAction.HEATING
        else:
            self._attr_hvac_mode = HVACMode.OFF
            self._attr_hvac_action = HVACAction.IDLE

        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
            
        self._attr_target_temperature = temperature
        
        # If the oven is currently OFF, we just store the preset locally without turning it on.
        if self._attr_hvac_mode == HVACMode.OFF:
            self.async_write_ha_state()
            return
            
        cook = self._client.get_current_cook(self._device.id)
        if not cook or not cook.current_stage:
            from .anova_api.apo.models import AnovaPOCook, AnovaPORecipe, AnovaPOStage
            cook = AnovaPOCook(recipe=AnovaPORecipe(title="Manual Cook", stages=[AnovaPOStage()]), active_stage_index=0)
            
        cook.current_stage.temperature = temperature
        await self._client.play_cook(self._device.id, cook)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            await self._client.stop_cook(self._device.id)
        elif hvac_mode == HVACMode.HEAT:
            targ = self._attr_target_temperature
            if not targ:  # Catches 0.0 or None
                targ = 176.67  # Default 350 F
                
            cook = self._client.get_current_cook(self._device.id)
            if not cook or not cook.current_stage:
                from .anova_api.apo.models import AnovaPOCook, AnovaPORecipe, AnovaPOStage
                cook = AnovaPOCook(recipe=AnovaPORecipe(title="Manual Cook", stages=[AnovaPOStage()]), active_stage_index=0)
                
            cook.current_stage.temperature = targ
            
            # Send payload directly without nesting commands if we want to ensure it plays
            await self._client.play_cook(self._device.id, cook)
            self._attr_hvac_mode = HVACMode.HEAT
            self._attr_hvac_action = HVACAction.HEATING
            self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        await self.async_set_hvac_mode(HVACMode.OFF)


class AnovaProbe(ClimateEntity):
    """Representation of an Anova Physical Probe target."""

    _attr_has_entity_name = True
    _attr_name = "Probe"
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        """Initialize the climate entity."""
        self._client = client
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_probe_target"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=self._device.name,
            manufacturer=MANUFACTURER,
            model=self._device.model,
        )
        self._attr_current_temperature = 0.0
        self._attr_target_temperature = 55.0
        self._attr_hvac_mode = HVACMode.HEAT
        self._remove_cb = None

    @property
    def min_temp(self) -> float:
        return 1.0

    @property
    def max_temp(self) -> float:
        return 100.0

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)
        self._handle_update(self._device.id)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str) -> None:
        if device_id != self._device.id: return
        state = self._client.get_apo_state(self._device.id)
        if not state: return

        self._attr_available = state.nodes.probe_connected

        try:
            self._attr_current_temperature = state.nodes.current_probe_temp
            if state.cook and state.cook.current_stage:
                from .anova_api.apo.models import AnovaPOProbe
                adv = state.cook.current_stage.advance
                if isinstance(adv, AnovaPOProbe):
                    self._attr_target_temperature = adv.target
        except Exception: pass
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None: return
        
        self._attr_target_temperature = temperature

        cook = self._client.get_current_cook(self._device.id)
        if not cook or not cook.current_stage:
            from .anova_api.apo.models import AnovaPOCook, AnovaPORecipe, AnovaPOStage
            cook = AnovaPOCook(recipe=AnovaPORecipe(title="Manual Cook", stages=[AnovaPOStage()]), active_stage_index=0)
            
        from .anova_api.apo.models import AnovaPOProbe
        cook.current_stage.advance = AnovaPOProbe(target=temperature)
        await self._client.play_cook(self._device.id, cook)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        pass
