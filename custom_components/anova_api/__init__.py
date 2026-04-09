"""The Anova API integration."""

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import storage
from homeassistant.components.frontend import async_register_built_in_panel
from homeassistant.components.http import StaticPathConfig
import asyncio
import os

from .anova_lib.client import AnovaClient
from .const import DOMAIN, CONF_TOKEN, RECIPE_STORAGE_KEY, RECIPE_STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.WATER_HEATER,
    Platform.CLIMATE,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Anova API from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    token = entry.data[CONF_TOKEN]
    session = async_get_clientsession(hass)
    
    client = AnovaClient(token=token, session=session)
    
    try:
        success = await client.connect()
        if not success:
            _LOGGER.error("Failed to connect to Anova API")
            return False
            
        # Wait up to 3 seconds for the initial device discovery payloads
        for _ in range(30):
            if client.devices:
                break
            await asyncio.sleep(0.1)
            
    except Exception as err:
        _LOGGER.error("Error connecting to Anova API: %s", err)
        return False

    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "recipes": []
    }

    # Setup recipe storage
    store = storage.Store(hass, RECIPE_STORAGE_VERSION, RECIPE_STORAGE_KEY)
    recipes = await store.async_load()
    if recipes is None:
        recipes = []
    hass.data[DOMAIN][entry.entry_id]["recipes"] = recipes

    # Register the custom frontend panel
    # We will serve the panel assets from the www directory
    try:
        www_dir = os.path.join(os.path.dirname(__file__), "www")
        await hass.http.async_register_static_paths([
            StaticPathConfig("/anova-panel", www_dir, False)
        ])
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="Anova",
            sidebar_icon="mdi:stove",
            frontend_url_path="anova",
            config={
                "name": "anova-panel",
                "embed_iframe": False,
                "trust_external": False,
                "module_url": "/anova-panel/anova-panel.js"
            },
            require_admin=False,
        )
    except Exception as e:
        _LOGGER.warning("Could not register custom panel: %s", e)

    # Register services
    async def handle_save_recipe(call):
        name = call.data["name"]
        stages = call.data["stages"]
        recipes = hass.data[DOMAIN][entry.entry_id]["recipes"]
        
        # update or append
        existing = next((r for r in recipes if r["name"] == name), None)
        if existing:
            existing["stages"] = stages
        else:
            recipes.append({"name": name, "stages": stages})
            
        store = storage.Store(hass, RECIPE_STORAGE_VERSION, RECIPE_STORAGE_KEY)
        await store.async_save(recipes)
        # Notify select entities to update (we rely on simple polling or reload normally, 
        # but dispatch would be better in a full refactor)
        
    async def handle_delete_recipe(call):
        name = call.data["name"]
        recipes = hass.data[DOMAIN][entry.entry_id]["recipes"]
        filtered = [r for r in recipes if r["name"] != name]
        hass.data[DOMAIN][entry.entry_id]["recipes"] = filtered
        
        store = storage.Store(hass, RECIPE_STORAGE_VERSION, RECIPE_STORAGE_KEY)
        await store.async_save(filtered)

    hass.services.async_register(DOMAIN, "save_recipe", handle_save_recipe)
    hass.services.async_register(DOMAIN, "delete_recipe", handle_delete_recipe)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        client: AnovaClient = data["client"]
        await client.close()
        
        # Note: Unregistering panels built-in to custom_components isn't trivial in HA without 
        # private APIs, but we'll leave it registered since the user won't un-install often.

    return unload_ok
