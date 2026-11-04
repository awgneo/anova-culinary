"""Tests for the descale and continue buttons."""

from homeassistant.const import STATE_UNAVAILABLE

from conftest import OVEN_ID, oven_state


async def test_descale(hass, sent) -> None:
    """Descaling starts on an idle oven; it's unavailable while cooking."""
    assert hass.states.get("button.test_oven_descale").state == STATE_UNAVAILABLE
    await hass.services.async_call("button", "press", {"entity_id": "button.idle_oven_descale"}, blocking=True)
    assert [command for command, _ in sent.commands] == ["CMD_APO_START_DESCALE"]


async def test_continue(hass, sent, client) -> None:
    """Continue is unavailable until the cook waits on the user, then starts the stage."""
    assert hass.states.get("button.test_oven_continue").state == STATE_UNAVAILABLE
    state = oven_state()
    state["cook"]["activeStageMode"] = "running"
    client.devices[OVEN_ID].update(state)
    await hass.async_block_till_done()
    await hass.services.async_call("button", "press", {"entity_id": "button.test_oven_continue"}, blocking=True)
    assert sent.commands == [("CMD_APO_START_STAGE", {"stageId": state["cook"]["activeStageId"]})]
