"""Tests for the oven and probe climate entities."""

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.exceptions import ServiceValidationError


async def call(hass, service: str, entity_id: str, **data) -> None:
    await hass.services.async_call("climate", service, {"entity_id": entity_id, **data}, blocking=True)


async def test_cooking_oven(hass, sent) -> None:
    """A cooking oven heats, showing its stage's target and the active bulb."""
    state = hass.states.get("climate.test_oven")
    assert state.state == HVACMode.HEAT
    assert state.attributes["current_temperature"] == 25  # 24.96, shown in whole degrees
    assert state.attributes["temperature"] == 54.4
    assert state.attributes["max_temp"] == 98  # sous vide with steam
    await call(hass, "set_temperature", "climate.test_oven", temperature=60)
    await call(hass, "set_hvac_mode", "climate.test_oven", hvac_mode="off")
    assert sent.commands == [
        ("CMD_APO_SET_TEMPERATURE_BULBS", {"mode": "wet", "wet": {"setpoint": {"celsius": 60}}}),
        ("CMD_APO_STOP", {"id": "oven-1", "type": "CMD_APO_STOP"}),
    ]


async def test_out_of_range(hass, sent) -> None:
    """A target the stage's settings don't allow is refused."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "climate", "set_temperature", {"entity_id": "climate.test_oven", "temperature": 99, "hvac_mode": "heat"}, blocking=True
        )


async def test_idle_oven_starts_at_the_remembered_target(hass, sent) -> None:
    """While off, a target is remembered; turning on starts a one-stage cook at it."""
    assert hass.states.get("climate.idle_oven").state == HVACMode.OFF
    await call(hass, "set_temperature", "climate.idle_oven", temperature=200)
    assert sent.commands == []
    assert hass.states.get("climate.idle_oven").attributes["temperature"] == 200
    await call(hass, "turn_on", "climate.idle_oven")
    (command, payload), = sent.commands
    assert command == "CMD_APO_START" and payload["cookableType"] == "manual"
    assert payload["stages"][0]["do"]["temperatureBulbs"]["dry"]["setpoint"]["celsius"] == 200


async def test_probe(hass, client, sent) -> None:
    """The probe is available while cooking with it plugged in, and sets its target."""
    assert hass.states.get("climate.test_oven_probe").state == "unavailable"
    oven = client.devices["oven-1"]
    oven.state.nodes.temperature_probe.connected = True
    oven.notify()
    await hass.async_block_till_done()
    assert hass.states.get("climate.test_oven_probe").state == HVACMode.HEAT
    await call(hass, "set_temperature", "climate.test_oven_probe", temperature=57)
    assert sent.commands == [("CMD_APO_SET_PROBE", {"setpoint": {"celsius": 57}})]
