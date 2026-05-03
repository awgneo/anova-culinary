"""Tests for the Anova Humidifier component."""

import pytest
from unittest.mock import patch
from custom_components.anova_culinary.const import DOMAIN
from custom_components.anova_culinary.anova_api.apo import AnovaPOCook, AnovaPORecipe, AnovaPOStage

@pytest.mark.asyncio
async def test_humidifier_states_and_commands(hass, init_integration):
    """Test humidifier updates and commands for APO steam control."""
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
    state = hass.states.get("humidifier.test_oven_steam")
    assert state is not None
    assert state.state == "on"
    assert state.attributes.get("humidity") == 50
    
    # Mutate the steam slider
    with patch("custom_components.anova_culinary.anova_api.client.AnovaClient.play_cook") as mock_play:
        await hass.services.async_call(
            "humidifier", "set_humidity", 
            {"entity_id": "humidifier.test_oven_steam", "humidity": 100}, 
            blocking=True
        )
        
        mock_play.assert_called_once()
        called_cook = mock_play.call_args[0][1]
        assert called_cook.current_stage.steam == 100

    # Turn off the steam
    with patch("custom_components.anova_culinary.anova_api.client.AnovaClient.play_cook") as mock_play:
        await hass.services.async_call(
            "humidifier", "turn_off", 
            {"entity_id": "humidifier.test_oven_steam"}, 
            blocking=True
        )
        
        mock_play.assert_called_once()
        called_cook = mock_play.call_args[0][1]
        assert called_cook.current_stage.steam == 0

    # Turn on the steam
    client.devices["APO-456"].state.cook.current_stage.steam = 0
    with patch("custom_components.anova_culinary.anova_api.client.AnovaClient.play_cook") as mock_play:
        await hass.services.async_call(
            "humidifier", "turn_on", 
            {"entity_id": "humidifier.test_oven_steam"}, 
            blocking=True
        )
        
        mock_play.assert_called_once()
        called_cook = mock_play.call_args[0][1]
        assert called_cook.current_stage.steam == 100
