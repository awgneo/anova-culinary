"""Tests for the oven selects: their labelled options, and the app's commands behind them."""

import pytest
from homeassistant.exceptions import ServiceValidationError


async def select(hass, entity_id: str, option: str) -> None:
    await hass.services.async_call("select", "select_option", {"entity_id": entity_id, "option": option}, blocking=True)


async def test_states(hass, sent) -> None:
    """The running stage's settings, under their labels."""
    assert hass.states.get("select.test_oven_heating_element").state == "Rear"
    assert hass.states.get("select.test_oven_fan").state == "High"
    assert hass.states.get("select.test_oven_timer_starts").state == "Food Detected"
    assert hass.states.get("select.test_oven_fan").attributes["options"] == ["Off", "Low", "Medium", "High"]


async def test_commands(hass, sent) -> None:
    """Elements and the timer start send the app's commands; sous vide keeps the fan high."""
    await select(hass, "select.test_oven_heating_element", "Top + Rear")
    await select(hass, "select.test_oven_timer_starts", "Immediately")
    assert sent.commands[0] == ("CMD_APO_SET_HEATING_ELEMENTS", {"top": {"on": True}, "bottom": {"on": False}, "rear": {"on": True}})
    command, payload = sent.commands[1]
    assert command == "CMD_APO_UPDATE_COOK_STAGES"
    assert "entry" not in payload["stages"][0]["do"]["timer"]
    with pytest.raises(ServiceValidationError):
        await select(hass, "select.test_oven_fan", "Low")
