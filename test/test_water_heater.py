"""Tests for the Anova water heater component."""

import pytest
from unittest.mock import patch
from homeassistant.components.water_heater import STATE_ECO, STATE_ELECTRIC
from custom_components.anova_culinary.const import DOMAIN

@pytest.mark.asyncio
async def test_water_heater_states_and_commands(hass, init_integration):
    """Test water heater telemetry and action commands for APC."""
    client = hass.data[DOMAIN][init_integration.entry_id]["client"]
    
    # Inject telemetry indicating an actively running cooker at 55.4C
    from custom_components.anova_culinary.anova_api.apc.models import AnovaPCTemperatureUnit
    
    apc_state = client.devices["APC-123"].state
    apc_state.is_running = True
    apc_state.target_temperature = 55.4
    apc_state.current_temperature = 55.3
    apc_state.unit = AnovaPCTemperatureUnit.C
    
    for cb in client._callbacks:
        cb("APC-123")
    await hass.async_block_till_done()

    # Validate platform bounds
    state = hass.states.get("water_heater.test_cooker")
    assert state is not None
    assert state.state == STATE_ELECTRIC
    assert state.attributes["current_temperature"] == 55.3
    assert state.attributes["temperature"] == 55.4
    
    # Mutate the configuration map
    with patch("custom_components.anova_culinary.anova_api.client.AnovaClient.play_cook") as mock_play:
        await hass.services.async_call(
            "water_heater", "set_temperature", 
            {"entity_id": "water_heater.test_cooker", "temperature": 60.0}, 
            blocking=True
        )
        
        mock_play.assert_called_once()
        called_cook = mock_play.call_args[0][1]
        assert called_cook.target_temperature == 60.0
