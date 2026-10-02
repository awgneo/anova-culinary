"""Tests for the Anova Number component."""

import pytest
from unittest.mock import patch
from custom_components.anova_culinary.const import DOMAIN
from custom_components.anova_culinary.anova_api.apo import AnovaPOCook, AnovaPORecipe, AnovaPOStage

@pytest.mark.asyncio
async def test_number_states_and_commands(hass, init_integration):
    """Test number updates and commands for APO timer."""
    client = hass.data[DOMAIN][init_integration.entry_id]["client"]
    
    cook = AnovaPOCook(
        recipe=AnovaPORecipe(
            stages=[AnovaPOStage(steam=50)]
        ),
        active_stage_index=0
    )
    client.devices["APO-456"].state.cook = cook
    client.devices["APO-456"].state.is_running = True
    
    for cb in client._callbacks:
        cb("APO-456")
    await hass.async_block_till_done()

    # Validate state is extracted perfectly from stage boundaries
    state = hass.states.get("number.test_oven_steam")
    assert state is not None
    assert state.state == "50"
    
    # Mutate the steam slider
    with patch("custom_components.anova_culinary.anova_api.client.AnovaClient.play_cook") as mock_play:
        await hass.services.async_call(
            "number", "set_value", 
            {"entity_id": "number.test_oven_steam", "value": "100"}, 
            blocking=True
        )
        
        mock_play.assert_called_once()
        called_cook = mock_play.call_args[0][1]
        assert called_cook.current_stage.steam == 100
