"""Tests for the sensors."""

from homeassistant.helpers import entity_registry as er

from conftest import OVEN_ID, oven_state


async def test_states(hass, sent) -> None:
    """Timer, recipe and rack readings."""
    assert hass.states.get("sensor.test_oven_timer_remaining").state == "300"
    assert hass.states.get("sensor.test_oven_recipe").state == "Manual Cook"
    assert hass.states.get("sensor.test_oven_rack_position").state == "unknown"
    assert hass.states.get("sensor.idle_oven_recipe").state == "None"
    assert hass.states.get("sensor.idle_oven_timer_elapsed").state == "0"
    assert int(hass.states.get("sensor.test_oven_timer_elapsed").state) > 0
    assert hass.states.get("sensor.test_cooker_timer_remaining").state == "0"


async def test_diagnostics_disabled_by_default(hass, sent) -> None:
    """Hardware readings exist but start disabled."""
    entry = er.async_get(hass).async_get("sensor.test_oven_rear_heater_power")
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_stage_status(hass, sent, client) -> None:
    """The stage status follows the oven, with the stage number and count."""
    status = hass.states.get("sensor.test_oven_stage_status")
    assert status.state == "preheating"
    assert (status.attributes["stage"], status.attributes["stages"]) == (1, 1)
    assert hass.states.get("sensor.idle_oven_stage_status").state == "idle"
    state = oven_state()
    state["cook"]["activeStageMode"] = "running"
    client.devices[OVEN_ID].update(state)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test_oven_stage_status").state == "add_food"
