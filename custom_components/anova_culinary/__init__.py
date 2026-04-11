"""The Anova API integration."""

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import storage
from homeassistant.helpers.collection import DictStorageCollection, DictStorageCollectionWebsocket
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
import asyncio
import os

from .anova_api.client import AnovaClient
from .const import DOMAIN, CONF_TOKEN, RECIPE_STORAGE_KEY, RECIPE_STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.WATER_HEATER,
    Platform.CLIMATE,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
]


class APORecipeCollection(DictStorageCollection):
    """Zero introspection pure UUID store array mapping."""
    async def _process_create_data(self, data: dict) -> dict:
        return data

    @callback
    def _get_suggested_id(self, info: dict) -> str:
        return info.get("name", "recipe")

    async def _update_data(self, item: dict, update_data: dict) -> dict:
        return {**item, **update_data}


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

    # Setup recipe storage collection
    store = storage.Store(hass, RECIPE_STORAGE_VERSION, RECIPE_STORAGE_KEY)
    collection = APORecipeCollection(store)
    await collection.async_load()
    hass.data[DOMAIN][entry.entry_id]["recipes"] = collection

    # Register native websockets
    ws = DictStorageCollectionWebsocket(
        collection,
        f"{DOMAIN}/recipes",
        "recipe",
        {"name": str, "stages": list},
        {"name": str, "stages": list}
    )
    ws.async_setup(hass)

    # We will serve the panel assets from the www directory
    try:
        domain_hyphen = DOMAIN.replace("_", "-")
        www_dir = os.path.join(os.path.dirname(__file__), "www")
        panel_path = os.path.join(www_dir, "panel.js")
        
        # Always cache break using file modification time
        cache_buster = str(int(os.path.getmtime(panel_path))) if os.path.exists(panel_path) else "1"
        
        await hass.http.async_register_static_paths([
            StaticPathConfig(f"/{domain_hyphen}", www_dir, False)
        ])
        await async_register_panel(
            hass,
            frontend_url_path=domain_hyphen,
            webcomponent_name=domain_hyphen,
            sidebar_title="Anova",
            sidebar_icon="mdi:stove",
            module_url=f"/{domain_hyphen}/panel.js?v={cache_buster}",
            embed_iframe=False,
            require_admin=False,
            config={"domain": DOMAIN}
        )
    except Exception as e:
        _LOGGER.warning("Could not register custom panel: %s", e)



    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        if data := hass.data.get(DOMAIN, {}).pop(entry.entry_id, None):
            client: AnovaClient = data["client"]
            await client.close()
        
        # Note: Unregistering panels built-in to custom_components isn't trivial in HA without 
        # private APIs, but we'll leave it registered since the user won't un-install often.

    return unload_ok
