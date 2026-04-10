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
from .anova_api.client import AnovaClient
from .anova_api.device import DeviceType


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
            entities.extend([
                AnovaOven(client, device_id, device.name, device.model),
                AnovaProbe(client, device_id, device.name, device.model),
            ])
            
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
        self._attr_target_temperature = 176.67
        self._attr_hvac_mode = HVACMode.OFF
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
            curr_stage = state.cook.current_stage if state.cook else None
            
            if curr_stage:
                self._active_mode = "wet" if curr_stage.sous_vide else "dry"
                self._attr_target_temperature = curr_stage.temperature
                
                # Default current temp to strictly match display board if possible to accurately mimic UI sync
                if state.nodes.display_board_celsius > 0:
                    self._attr_current_temperature = state.nodes.display_board_celsius
                elif self._active_mode == "wet":
                    self._attr_current_temperature = state.nodes.current_wet_temp
                else:
                    self._attr_current_temperature = state.nodes.current_dry_temp
            else:
                self._active_mode = "dry"
                # Do NOT overwrite _attr_target_temperature to 0.0. Let it retain memory of the last configuration 
                # (or initial __init__ payload) so the unified UI components stay perfectly in place!
                
                if state.nodes.display_board_celsius > 0:
                    self._attr_current_temperature = state.nodes.display_board_celsius
                else:
                    self._attr_current_temperature = state.nodes.current_dry_temp
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
            
        self._attr_target_temperature = temperature
        
        # If the oven is currently OFF, we just store the preset locally without turning it on.
        if self._attr_hvac_mode == HVACMode.OFF:
            self.async_write_ha_state()
            return
            
        cook = self._client.get_current_cook(self._device_id)
        if not cook or not cook.current_stage:
            from .anova_api.apo.models import APOCook, APORecipe, APOStage
            cook = APOCook(recipe=APORecipe(title="Manual Cook", stages=[APOStage()]), active_stage_index=0)
            
        cook.current_stage.temperature = temperature
        await self._client.play_cook(self._device_id, cook)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            await self._client.stop_apo_cook(self._device_id)
        elif hvac_mode == HVACMode.HEAT:
            targ = self._attr_target_temperature
            if not targ:  # Catches 0.0 or None
                targ = 176.67  # Default 350 F
                
            cook = self._client.get_current_cook(self._device_id)
            if not cook or not cook.current_stage:
                from .anova_api.apo.models import APOCook, APORecipe, APOStage
                cook = APOCook(recipe=APORecipe(title="Manual Cook", stages=[APOStage()]), active_stage_index=0)
                
            cook.current_stage.temperature = targ
            
            # Send payload directly without nesting commands if we want to ensure it plays
            await self._client.play_cook(self._device_id, cook)
            self._attr_hvac_mode = HVACMode.HEAT
            self.async_write_ha_state()


class AnovaProbe(ClimateEntity):
    """Representation of an Anova Physical Probe target."""

    _attr_has_entity_name = True
    _attr_name = "Target Probe"
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, client: AnovaClient, device_id: str, name: str, model: str) -> None:
        """Initialize the climate entity."""
        self._client = client
        self._device_id = device_id
        self._model = model
        self._attr_unique_id = f"anova_apo_{device_id}_probe_target"
        
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)})
        self._attr_current_temperature = 0.0
        self._attr_target_temperature = 55.0
        self._attr_hvac_mode = HVACMode.OFF
        self._remove_cb = None

    @property
    def min_temp(self) -> float:
        return 1.0

    @property
    def max_temp(self) -> float:
        return 100.0

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)
        self._handle_update(self._device_id, {})

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str, payload: dict) -> None:
        if device_id != self._device_id: return
        state = self._client.get_apo_state(self._device_id)
        if not state: return

        try:
            self._attr_current_temperature = state.nodes.current_probe_temp
            if state.cook and state.cook.current_stage:
                from .anova_api.apo.models import APOProbe
                adv = state.cook.current_stage.advance
                if isinstance(adv, APOProbe):
                    self._attr_target_temperature = adv.target
                    self._attr_hvac_mode = HVACMode.HEAT
                else:
                    self._attr_hvac_mode = HVACMode.OFF
            else:
                self._attr_hvac_mode = HVACMode.OFF
        except Exception: pass
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None: return
        
        self._attr_target_temperature = temperature
        if self._attr_hvac_mode == HVACMode.OFF:
            self.async_write_ha_state()
            return

        cook = self._client.get_current_cook(self._device_id)
        if not cook or not cook.current_stage:
            from .anova_api.apo.models import APOCook, APORecipe, APOStage
            cook = APOCook(recipe=APORecipe(title="Manual Cook", stages=[APOStage()]), active_stage_index=0)
            
        from .anova_api.apo.models import APOProbe
        cook.current_stage.advance = APOProbe(target=temperature)
        await self._client.play_cook(self._device_id, cook)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        cook = self._client.get_current_cook(self._device_id)
        
        from .anova_api.apo.models import APOProbe
        if hvac_mode == HVACMode.OFF:
            if cook and cook.current_stage and isinstance(cook.current_stage.advance, APOProbe):
                cook.current_stage.advance = None
                await self._client.play_cook(self._device_id, cook)
        elif hvac_mode == HVACMode.HEAT:
            if not cook or not cook.current_stage:
                from .anova_api.apo.models import APOCook, APORecipe, APOStage
                cook = APOCook(recipe=APORecipe(title="Manual Cook", stages=[APOStage()]), active_stage_index=0)
                
            targ = self._attr_target_temperature or 55.0
            cook.current_stage.advance = APOProbe(target=targ)
            await self._client.play_cook(self._device_id, cook)
            
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()
