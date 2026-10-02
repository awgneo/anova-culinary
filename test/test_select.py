"""Tests for the Anova Select components."""

import pytest
from unittest.mock import patch
from custom_components.anova_culinary.const import DOMAIN
from custom_components.anova_culinary.anova_api.apo.models import (
    AnovaPOCook, AnovaPORecipe, AnovaPOStage, AnovaPOFanSpeed
)

@pytest.mark.asyncio
async def test_select_states_and_commands(hass, init_integration):
    """Test selector updates and telemetry commands."""
    client = hass.data[DOMAIN][init_integration.entry_id]["client"]
    
    cook = AnovaPOCook(
        recipe=AnovaPORecipe(
            stages=[AnovaPOStage(fan=AnovaPOFanSpeed.OFF)]
        ),
        active_stage_index=0
    )
    client.devices["APO-456"].state.cook = cook
    
    state = client.devices["APO-456"].state
    state.is_running = True
    
    for cb in client._callbacks:
        cb("APO-456")
    await hass.async_block_till_done()

    # Validate state mappings
    state = hass.states.get("select.test_oven_fan")
    assert state is not None
    assert state.state == "Off"
    
    # Mutate Fan Speed
    with patch("custom_components.anova_culinary.anova_api.client.AnovaClient.play_cook") as mock_play:
        await hass.services.async_call(
            "select", "select_option", 
            {"entity_id": "select.test_oven_fan", "option": "High"}, 
            blocking=True
        )
        
        mock_play.assert_called_once()
        called_cook = mock_play.call_args[0][1]
        assert called_cook.current_stage.fan == AnovaPOFanSpeed.HIGH
