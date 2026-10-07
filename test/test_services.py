"""Tests for the actions, the panel's websocket commands, and diagnostics."""

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.anova_culinary.const import DOMAIN
from custom_components.anova_culinary.diagnostics import async_get_config_entry_diagnostics
from custom_components.anova_culinary.recipes import DATA_RECIPES

EGG_BITES = {
    "name": "Egg Bites",
    "stages": [
        {"sous_vide": True, "temperature": 180, "temperature_unit": "F", "steam": 100, "advance": {"duration": 2100, "trigger": "food_detected"}},
        {"temperature": 350, "temperature_unit": "F", "heating_elements": "top", "advance": {"duration": 720, "trigger": "immediately"}, "transition": "manual"},
    ],
}


async def call(hass, service: str, **data) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_recipes(hass, sent) -> None:
    """Recipes save, replace by name, play on both ovens as new cooks, and delete."""
    await call(hass, "save_recipe", **EGG_BITES)
    await call(hass, "save_recipe", **{**EGG_BITES, "stages": EGG_BITES["stages"][:1]})
    recipes = hass.data[DATA_RECIPES].data
    (recipe_id,) = recipes
    assert len(recipes[recipe_id]["stages"]) == 1
    await call(hass, "save_recipe", **EGG_BITES)
    await call(hass, "play_recipe", device_id=["oven-1", "oven-2"], recipe_id=recipe_id)
    starts = [payload for command, payload in sent.commands if command == "CMD_APO_START"]
    assert [start["title"] for start in starts] == ["Egg Bites", "Egg Bites"]
    assert starts[0]["cookId"] != starts[1]["cookId"]
    assert starts[0]["stages"][0]["exit"]["conditions"] == {"and": {"userAction": {"=": True}}}
    await call(hass, "delete_recipe", name="Egg Bites")
    assert not hass.data[DATA_RECIPES].data


async def test_recipe_errors(hass, sent) -> None:
    """Unknown recipes and ovens are refused."""
    with pytest.raises(ServiceValidationError):
        await call(hass, "play_recipe", device_id=["oven-1"], recipe_id="missing")
    await call(hass, "save_recipe", **EGG_BITES)
    (recipe_id,) = hass.data[DATA_RECIPES].data
    with pytest.raises(ServiceValidationError):
        await call(hass, "play_recipe", device_id=["cooker-1"], recipe_id=recipe_id)
    with pytest.raises(ServiceValidationError):
        await call(hass, "delete_recipe", name="missing")


async def test_panel_commands(hass, hass_ws_client, client, sent) -> None:
    """The panel lists the ovens, gets the limits, and follows the running cook."""
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": f"{DOMAIN}/ovens"})
    assert (await ws.receive_json())["result"] == [{"id": "oven-2", "name": "Idle Oven"}, {"id": "oven-1", "name": "Test Oven"}]
    await ws.send_json({"id": 2, "type": f"{DOMAIN}/limits"})
    assert (await ws.receive_json())["result"]["wet_steam_max"] == 98
    await ws.send_json({"id": 5, "type": f"{DOMAIN}/limits", "stage": {"temperature": 350, "temperature_unit": "F", "heating_elements": "bottom"}})
    assert (await ws.receive_json())["result"]["stage"] == {"min": 77.0, "max": 446.0, "fans": ["high", "medium", "low", "off"]}
    await ws.send_json({"id": 6, "type": f"{DOMAIN}/cook"})
    assert (await ws.receive_json())["success"]
    event = (await ws.receive_json())["event"]
    assert event["name"] == "" and event["stages"][0]["sous_vide"]


async def test_diagnostics(hass, mock_config_entry, sent) -> None:
    """Diagnostics carry each device's state, without the token or ids."""
    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert diagnostics["entry"]["token"] == "**REDACTED**"
    oven = next(device for device in diagnostics["devices"] if device["model"] == "Anova Precision Oven 2.0" and device["state"].get("cook"))
    assert oven["state"]["systemInfo"]["deviceId"] == "**REDACTED**"
    assert oven["state"]["cook"]["cookId"] == "**REDACTED**"
