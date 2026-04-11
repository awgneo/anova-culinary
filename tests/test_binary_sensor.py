"""Tests for the Anova Binary Sensors."""

import pytest
from homeassistant.const import STATE_ON, STATE_OFF
from custom_components.anova_culinary.const import DOMAIN

@pytest.mark.asyncio
async def test_binary_sensor_states(hass, init_integration):
    """Test boolean door, lamp, and camera bounds."""
    client = hass.data[DOMAIN][init_integration.entry_id]["client"]
    
    state = client.devices["APO-456"].state
    state.nodes.door_closed = False
    state.nodes.door_lamp_on = True
    state.nodes.cavity_lamp_on = False
    state.nodes.cavity_camera_is_empty = False
    
    for cb in client._callbacks:
        cb("APO-456")
    await hass.async_block_till_done()

    # Assert state parses logic exactly
    state = hass.states.get("binary_sensor.test_oven_oven_door")
    assert state.state == STATE_ON
    
    state = hass.states.get("binary_sensor.test_oven_door_lamp")
    assert state.state == STATE_ON
    
    state = hass.states.get("binary_sensor.test_oven_cavity_lamp")
    assert state.state == STATE_OFF
    
    state = hass.states.get("binary_sensor.test_oven_camera_status")
    assert state.state == STATE_ON
