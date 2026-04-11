"""Tests for the Anova sensors."""

import pytest
from homeassistant.const import ATTR_FRIENDLY_NAME
from custom_components.anova_culinary.const import DOMAIN

@pytest.mark.asyncio
async def test_sensor_states(hass, init_integration):
    """Test sensor telemetry updates from both devices."""
    client = hass.data[DOMAIN][init_integration.entry_id]["client"]
    
    # Send APO telemetry
    apo_state = client.devices["APO-456"].state
    apo_state.raw_state = {
        "payload": {
            "probe": {"current": {"celsius": "54.0"}},
            "timer": {"remaining": "600"}
        }
    }
    
    for cb in client._callbacks:
        cb("APO-456")
    await hass.async_block_till_done()

    # Validate Probe Sensor
    probe_state = hass.states.get("sensor.test_oven_probe_temperature")
    assert probe_state is not None
    assert probe_state.state == "54.0"
    
    # Validate Timer Sensor
    timer_state = hass.states.get("sensor.test_oven_timer_remaining")
    assert timer_state is not None
    assert timer_state.state == "600"
    
    # Send APC telemetry
    apc_state = client.devices["APC-123"].state
    apc_state.raw_state = {
        "payload": {
            "timer": {"remaining": "120"}
        }
    }
    
    for cb in client._callbacks:
        cb("APC-123")
    await hass.async_block_till_done()
    
    apc_timer_state = hass.states.get("sensor.test_cooker_timer_remaining")
    assert apc_timer_state is not None
    assert apc_timer_state.state == "120"
