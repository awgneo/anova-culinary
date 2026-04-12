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
from homeassistant.components import websocket_api
import asyncio
import os

from .anova_api.client import AnovaClient
from .anova_api.product import AnovaProduct
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

@websocket_api.websocket_command(
    {
        "type": f"{DOMAIN}/ovens",
    }
)
@callback
def ws_ovens(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Return a list of APO devices."""
    ovens = []
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if not isinstance(entry_data, dict): continue
        client = entry_data.get("client")
        if not client: continue
        
        for dev in client.devices.values():
            if dev.product == AnovaProduct.APO:
                ovens.append({"id": dev.id, "name": dev.name})
    
    connection.send_result(msg["id"], ovens)
    
    
@websocket_api.websocket_command(
    {
        "type": f"{DOMAIN}/cook",
    }
)
@websocket_api.async_response
async def ws_cook(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Subscribe to active cook changes in real-time."""
    
    @callback
    def forward_cook_state(device_id: str) -> None:
        """Forward state to frontend via websocket."""
        active_recipe = None
        for entry_data in hass.data.get(DOMAIN, {}).values():
            if not isinstance(entry_data, dict): continue
            client = entry_data.get("client")
            if not client: continue
            
            for d_id, device in client.devices.items():
                if device.product == AnovaProduct.APO:
                    state = client.get_apo_state(d_id)
                    if state and state.is_running and state.cook and state.cook.recipe:
                        active_recipe = state.cook.recipe.to_dict()
                        break
            if active_recipe: break
            
        connection.send_message(
            websocket_api.event_message(msg["id"], active_recipe)
        )

    # Attach listener to first available client since Anova accounts span across devices globally.
    first_client = None
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if not isinstance(entry_data, dict): continue
        if client := entry_data.get("client"):
            first_client = client
            break
            
    if not first_client:
        connection.send_error(msg["id"], "not_found", "No Anova client available")
        return
        
    remove_cb = first_client.register_callback(forward_cook_state)
    
    connection.subscriptions[msg["id"]] = remove_cb
    connection.send_result(msg["id"])
    
    # Send initial state explicitly so the UI has immediate data
    forward_cook_state("DISCOVERY")



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
        "recipes": None
    }

    if "recipes" not in hass.data[DOMAIN]:
        # Setup recipe storage collection ONCE globally
        store = storage.Store(hass, RECIPE_STORAGE_VERSION, RECIPE_STORAGE_KEY)
        collection = APORecipeCollection(store)
        await collection.async_load()
        hass.data[DOMAIN]["recipes"] = collection

        # Register native websockets ONCE globally
        ws = DictStorageCollectionWebsocket(
            collection,
            f"{DOMAIN}/recipes",
            "recipe",
            {"name": str, "stages": list},
            {"name": str, "stages": list}
        )
        ws.async_setup(hass)
        
        websocket_api.async_register_command(hass, ws_cook)
        websocket_api.async_register_command(hass, ws_ovens)
        
        import homeassistant.helpers.config_validation as cv

        async def handle_play_recipe(call):
            """Play a recipe on a specific device or multiple devices."""
            device_ids = call.data["device_id"]
            recipe_id = call.data["recipe_id"]
            
            recipe_data = hass.data[DOMAIN]["recipes"].data.get(recipe_id)
            if not recipe_data:
                _LOGGER.error("Recipe %s not found", recipe_id)
                return
                
            from .anova_api.apo.models import AnovaPORecipe
            from .anova_api.apo.transpiler import recipe_to_cook
            
            recipe = AnovaPORecipe.from_dict(recipe_data)
            recipe.id = recipe_id
            
            for target_dev_id in device_ids:
                client = None
                for entry_data in hass.data.get(DOMAIN, {}).values():
                    if isinstance(entry_data, dict) and "client" in entry_data:
                        c = entry_data["client"]
                        if c and target_dev_id in c.devices:
                            client = c
                            break
                            
                if not client:
                    _LOGGER.error("Anova client not found for device %s", target_dev_id)
                    continue
                    
                cook = recipe_to_cook(recipe)
                cook.cook_id = recipe.id
                await client.play_cook(target_dev_id, cook)

        import voluptuous as vol
        hass.services.async_register(
            DOMAIN, "play_recipe", handle_play_recipe,
            schema=vol.Schema({
                vol.Required("device_id"): vol.All(cv.ensure_list, [cv.string]),
                vol.Required("recipe_id"): cv.string
            })
        )

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

    hass.data[DOMAIN][entry.entry_id]["recipes"] = hass.data[DOMAIN]["recipes"]
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
