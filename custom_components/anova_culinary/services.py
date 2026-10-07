"""Actions: play, save and delete recipes, and adjust a timer."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN, SERVICE_SET_VALUE
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .anova_api import AnovaPODevice
from .anova_api.apo import AnovaPORecipe
from .const import DOMAIN
from .helpers import call_device, loaded_devices
from .recipes import DATA_RECIPES

SERVICE_PLAY_RECIPE = "play_recipe"
SERVICE_SAVE_RECIPE = "save_recipe"
SERVICE_DELETE_RECIPE = "delete_recipe"
SERVICE_ADJUST_TIMER = "adjust_timer"


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Registers the actions."""

    async def play_recipe(call: ServiceCall) -> None:
        """Play a recipe on a specific device or multiple devices."""
        recipe_data = hass.data[DATA_RECIPES].data.get(call.data["recipe_id"])
        if recipe_data is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="recipe_not_found")
        recipe = AnovaPORecipe.from_dict(recipe_data)
        ovens = {device.id: device for device in loaded_devices(hass) if isinstance(device, AnovaPODevice)}
        for device_id in call.data["device_id"]:
            if (oven := ovens.get(device_id)) is None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="oven_not_found")
            await call_device(oven.start_recipe(recipe))

    async def save_recipe(call: ServiceCall) -> None:
        """Save a recipe, replacing one with the same name."""
        recipes = hass.data[DATA_RECIPES]
        data = {"name": call.data["name"], "stages": call.data["stages"]}
        if (existing := recipes.find(call.data["name"])) is not None:
            await recipes.async_update_item(existing["id"], data)
        else:
            await recipes.async_create_item(data)

    async def delete_recipe(call: ServiceCall) -> None:
        """Delete a saved recipe by name."""
        recipes = hass.data[DATA_RECIPES]
        if (existing := recipes.find(call.data["name"])) is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="recipe_not_found")
        await recipes.async_delete_item(existing["id"])

    async def adjust_timer(call: ServiceCall) -> None:
        """Adjust the timer by a specific amount of minutes."""
        entity_id = call.data[ATTR_ENTITY_ID]
        if (state := hass.states.get(entity_id)) is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entity_not_found")
        current = float(state.state) if state.state not in ("unknown", "unavailable") else 0.0
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: entity_id, "value": max(0.0, current + call.data["amount"])},
            blocking=True,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_PLAY_RECIPE,
        play_recipe,
        schema=vol.Schema({vol.Required("device_id"): vol.All(cv.ensure_list, [cv.string]), vol.Required("recipe_id"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_RECIPE,
        save_recipe,
        schema=vol.Schema({vol.Required("name"): cv.string, vol.Required("stages"): list}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_RECIPE, delete_recipe, schema=vol.Schema({vol.Required("name"): cv.string})
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADJUST_TIMER,
        adjust_timer,
        schema=vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id, vol.Required("amount"): vol.Coerce(float)}),
    )
