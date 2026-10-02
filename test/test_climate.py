"""Tests for the Anova Climate component."""

import pytest
from unittest.mock import patch
from homeassistant.components.climate.const import HVACMode
from custom_components.anova_culinary.const import DOMAIN
from custom_components.anova_culinary.anova_api.apo import AnovaPOCook, AnovaPORecipe, AnovaPOStage

@pytest.mark.asyncio
async def test_climate_states_and_commands(hass, init_integration):
    """Test climate UI rendering and commands."""
    client = hass.data[DOMAIN][init_integration.entry_id]["client"]
    
    # 1. Setup local recipe bounds representing 90 Celsius dry mode
    cook = AnovaPOCook(
        recipe=AnovaPORecipe(
            stages=[AnovaPOStage(temperature=90.0, sous_vide=True)]
        ),
        active_stage_index=0
    )
    client.devices["APO-456"].state.cook = cook
    
    # 2. Inject dummy telemetry proxy variables directly
    state = client.devices["APO-456"].state
    state.is_running = True
    state.nodes.current_wet_temp = 140.0
    
    for cb in client._callbacks:
        cb("APO-456")
    await hass.async_block_till_done()

    state = hass.states.get("climate.test_oven")
    assert state is not None
    assert state.state == HVACMode.HEAT
    assert state.attributes["current_temperature"] == 140.0
    assert state.attributes["temperature"] == 90.0
    
    # 3. Simulate target override
    with patch("custom_components.anova_culinary.anova_api.client.AnovaClient.play_cook") as mock_play:
        await hass.services.async_call(
            "climate", "set_temperature", 
            {"entity_id": "climate.test_oven", "temperature": 95.0}, 
            blocking=True
        )
        
        mock_play.assert_called_once()
        called_cook = mock_play.call_args[0][1]
        assert called_cook.current_stage.temperature == 95.0
