"""Tests for the Anova Time component."""

import pytest
from datetime import time
from unittest.mock import patch
from homeassistant.components.time import DOMAIN as TIME_DOMAIN
from custom_components.anova_culinary.const import DOMAIN
from custom_components.anova_culinary.anova_api.apo.models import AnovaPOCook, AnovaPORecipe, AnovaPOStage, AnovaPOTimer, AnovaPOTimerTrigger

@pytest.mark.asyncio
async def test_time_states_and_commands(hass, init_integration):
    """Test time updates and commands for APO timer."""
    client = hass.data[DOMAIN][init_integration.entry_id]["client"]
    
    cook = AnovaPOCook(
        recipe=AnovaPORecipe(
            stages=[AnovaPOStage(advance=AnovaPOTimer(duration=5400, trigger=AnovaPOTimerTrigger.MANUALLY))]
        ),
        active_stage_index=0
    )
    client.devices["APO-456"].state.cook = cook
    client.devices["APO-456"].state.is_running = True
    
    for cb in client._callbacks:
        cb("APO-456")
    await hass.async_block_till_done()

    # Validate state is extracted perfectly from stage boundaries (5400 seconds = 01:30:00)
    state = hass.states.get("time.test_oven_timer")
    assert state is not None
    assert state.state == "01:30:00"
    
    # Mutate the time target (02:00:00 = 7200 seconds)
    with patch("custom_components.anova_culinary.anova_api.client.AnovaClient.play_cook") as mock_play:
        await hass.services.async_call(
            TIME_DOMAIN, "set_value", 
            {"entity_id": "time.test_oven_timer", "time": "02:00:00"}, 
            blocking=True
        )
        
        mock_play.assert_called_once()
        called_cook = mock_play.call_args[0][1]
        assert called_cook.current_stage.advance.duration == 7200
