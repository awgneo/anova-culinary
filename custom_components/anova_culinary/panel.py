"""The Anova sidebar panel (www/panel.js) and the websocket commands it uses beyond recipes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.core import HomeAssistant, callback

import voluptuous as vol

from .anova_api.apo import AnovaPOStage, limits
from .anova_api.apo.models import from_celsius
from .const import DOMAIN
from .helpers import loaded_ovens

_LOGGER = logging.getLogger(__name__)

WWW = Path(__file__).parent / "www"
PANEL_URL = DOMAIN.replace("_", "-")


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Serves the panel and registers its websocket commands."""
    websocket_api.async_register_command(hass, ws_ovens)
    websocket_api.async_register_command(hass, ws_cook)
    websocket_api.async_register_command(hass, ws_limits)
    try:
        # Cache-bust with the panel's modification time
        version = int((WWW / "panel.js").stat().st_mtime)
        await hass.http.async_register_static_paths([StaticPathConfig(f"/{PANEL_URL}-assets", str(WWW), False)])
        await async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name=PANEL_URL,
            sidebar_title="Anova",
            sidebar_icon="mdi:toaster-oven",
            module_url=f"/{PANEL_URL}-assets/panel.js?v={version}",
            embed_iframe=False,
            require_admin=False,
            config={"domain": DOMAIN},
        )
    except Exception:
        _LOGGER.exception("Could not register the Anova panel")


@websocket_api.websocket_command({"type": f"{DOMAIN}/ovens"})
@callback
def ws_ovens(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return a list of APO devices."""
    connection.send_result(msg["id"], [{"id": oven.id, "name": oven.name} for oven in loaded_ovens(hass)])


@websocket_api.websocket_command({"type": f"{DOMAIN}/limits", vol.Optional("stage"): dict})
@callback
def ws_limits(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The oven's limits, and for a stage, its temperature range (in its unit) and allowed fans."""
    result: dict[str, Any] = limits.limits()
    if (stage_data := msg.get("stage")) is not None:
        stage = AnovaPOStage.from_dict(stage_data)
        low, high = limits.stage_range(stage)
        result["stage"] = {
            "min": from_celsius(low, stage.temperature_unit),
            "max": from_celsius(high, stage.temperature_unit),
            "fans": [fan.value for fan in limits.allowed_fans(stage.sous_vide, stage.heating_elements, stage.steam)],
        }
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({"type": f"{DOMAIN}/cook"})
@callback
def ws_cook(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Subscribe to the cook running on any oven, as a recipe."""
    ovens = loaded_ovens(hass)

    @callback
    def forward_cook() -> None:
        recipe = next((oven.recipe for oven in ovens if oven.recipe is not None), None)
        connection.send_message(websocket_api.event_message(msg["id"], recipe.to_dict() if recipe else None))

    removers = [oven.register_callback(forward_cook) for oven in ovens]
    connection.subscriptions[msg["id"]] = lambda: [remove() for remove in removers]
    connection.send_result(msg["id"])
    forward_cook()
