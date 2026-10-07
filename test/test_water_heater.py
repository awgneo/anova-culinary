"""Tests for the cooker's water heater."""

from homeassistant.components.water_heater import STATE_ECO, STATE_ELECTRIC


async def test_cooker(hass, client, sent) -> None:
    """A cooking cooker is electric; targets and stopping send the app's commands."""
    state = hass.states.get("water_heater.test_cooker")
    assert state.state == STATE_ELECTRIC
    assert state.attributes["current_temperature"] == 55.2
    assert state.attributes["temperature"] == 56.5
    await hass.services.async_call("water_heater", "set_temperature", {"entity_id": "water_heater.test_cooker", "temperature": 60}, blocking=True)
    await hass.services.async_call("water_heater", "set_operation_mode", {"entity_id": "water_heater.test_cooker", "operation_mode": STATE_ECO}, blocking=True)
    assert [command for command, _ in sent.commands] == ["CMD_APC_SET_TARGET_TEMP", "CMD_APC_STOP"]
    assert sent.commands[0][1]["targetTemperature"] == 60
