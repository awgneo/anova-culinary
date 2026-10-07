"""Tests for the binary sensors."""

from homeassistant.const import STATE_OFF, STATE_ON


async def test_oven(hass, client, sent) -> None:
    """Door, lights, camera and tanks."""
    oven = client.devices["oven-1"]
    oven.state.nodes.door.closed = False
    oven.state.nodes.cavity_camera.is_empty = False
    oven.state.nodes.water_tank.low = True
    oven.notify()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.test_oven_door_status").state == STATE_ON
    assert hass.states.get("binary_sensor.test_oven_cavity_light").state == STATE_OFF
    assert hass.states.get("binary_sensor.test_oven_camera_status").state == STATE_ON
    assert hass.states.get("binary_sensor.test_oven_water_tank_low").state == STATE_ON
    assert hass.states.get("binary_sensor.test_oven_descale_required").state == STATE_OFF


async def test_cooker(hass, client, sent) -> None:
    """Cooker alarms follow its mode."""
    assert hass.states.get("binary_sensor.test_cooker_water_leak").state == STATE_OFF
    cooker = client.devices["cooker-1"]
    cooker.state.status.mode = "waterLeak"
    cooker.notify()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.test_cooker_water_leak").state == STATE_ON
