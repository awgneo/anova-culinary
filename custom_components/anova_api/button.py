"""Button platform for starting Anova APO recipes."""

import uuid
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    """Set up the Anova button platform."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    recipes = hass.data[DOMAIN][entry.entry_id]["recipes"]
    
    entities = []
    for device_id, device in client.devices.items():
        if device.type == DeviceType.APO:
            entities.append(AnovaStartRecipeButton(client, device_id, device.name, device.model, recipes))
            
    async_add_entities(entities)


class AnovaStartRecipeButton(ButtonEntity):
    """Button to start the selected recipe."""

    _attr_has_entity_name = True
    _attr_name = "Start Selected Recipe"
    _attr_icon = "mdi:play-circle"

    def __init__(self, client: AnovaClient, device_id: str, name: str, model: str, recipes: list) -> None:
        self._client = client
        self._device_id = device_id
        self._model = model
        self._recipes = recipes
        self._attr_unique_id = f"anova_apo_{device_id}_recipe_start_btn"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)})

    async def async_press(self) -> None:
        """Handle the button press."""
        # Find the linked select entity state to know which recipe was chosen
        select_entity_id = f"select.anova_apo_{self._device_id}_recipe_select"
        # The proper entity ID formatting replaces underscores sometimes, but we search by device
        # A simpler way in HA is looking up the state via hass.states 
        # (Though registering services is cleaner, this satisfies the button req)
        
        # To find the true entity ID, look it up in entity registry or construct standard format
        # Typically Domain.EntityName slugified:
        sn = "recipe" 
        target_id = f"select.anova_{self._device_id}_{sn}"
        
        # As a fallback proxy, we will just loop states to find our device ID
        selected_recipe_name = "None"
        for state in self.hass.states.async_all("select"):
            if self._device_id in state.entity_id and "recipe" in state.entity_id:
                selected_recipe_name = state.state
                break
                
        if selected_recipe_name == "None":
            return
            
        recipe = next((r for r in self._recipes if r.get("name") == selected_recipe_name), None)
        if not recipe:
            return
            
        # Dispatch to device
        stages = recipe.get("stages", [])
        if not stages:
            return
            
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
                    "stages": stages
                }
            }
        }
        await self._client.send_command(cmd)
