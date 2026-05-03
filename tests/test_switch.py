"""Tests for the Anova switches."""

import pytest
from unittest.mock import patch
from homeassistant.const import STATE_ON, STATE_OFF
from custom_components.anova_culinary.const import DOMAIN
from custom_components.anova_culinary.anova_api.apo import AnovaPOCook, AnovaPORecipe, AnovaPOStage

@pytest.mark.asyncio
async def test_switch_states_and_commands(hass, init_integration):
    """Test switch telemetry updates and mutative commands."""
    client = hass.data[DOMAIN][init_integration.entry_id]["client"]
    
    # Provide an active recipe locally so the switch resolves its boundary
    cook = AnovaPOCook(
        recipe=AnovaPORecipe(
            stages=[AnovaPOStage(sous_vide=False)]
        ),
        active_stage_index=0
    )
    client.devices["APO-456"].state.cook = cook
    
    # Fire dummy telemetry to trigger UI reflows
    for cb in client._callbacks:
        cb("APO-456")
    await hass.async_block_till_done()

    # Validate state initializes perfectly to mock bounds
    state = hass.states.get("switch.test_oven_sous_vide")
    assert state is not None
    assert state.state == STATE_OFF
    
    # Validate the toggle mutations compile backwards cleanly
    with patch(
        "custom_components.anova_culinary.anova_api.client.AnovaClient.play_cook"
    ) as mock_play:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.test_oven_sous_vide"}, blocking=True
        )
        
        mock_play.assert_called_once()
        called_device = mock_play.call_args[0][0]
        called_cook = mock_play.call_args[0][1]
        
        assert called_device == "APO-456"
        assert called_cook.current_stage.sous_vide is True
