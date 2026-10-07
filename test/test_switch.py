"""Tests for the oven switches."""

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE


async def toggle(hass, service: str, entity_id: str) -> None:
    await hass.services.async_call("switch", service, {"entity_id": entity_id}, blocking=True)


async def test_states(hass, sent) -> None:
    """Sous vide and steam follow the running stage; idle, they're unavailable but the light isn't."""
    assert hass.states.get("switch.test_oven_sous_vide").state == STATE_ON
    assert hass.states.get("switch.test_oven_steam_switch").state == STATE_ON
    assert hass.states.get("switch.test_oven_door_light").state == STATE_ON
    assert hass.states.get("switch.idle_oven_sous_vide").state == STATE_UNAVAILABLE
    assert hass.states.get("switch.idle_oven_steam_switch").state == STATE_UNAVAILABLE
    assert hass.states.get("switch.idle_oven_door_light").state == STATE_ON


async def test_commands(hass, sent) -> None:
    """Each switch sends the app's command; steam comes back at its last setting."""
    await toggle(hass, "turn_off", "switch.test_oven_sous_vide")
    await toggle(hass, "turn_off", "switch.test_oven_steam_switch")
    await toggle(hass, "turn_on", "switch.test_oven_steam_switch")
    await toggle(hass, "turn_off", "switch.test_oven_door_light")
    assert sent.commands == [
        ("CMD_APO_SET_TEMPERATURE_BULBS", {"mode": "dry", "dry": {"setpoint": {"celsius": 54.44}}}),
        ("CMD_APO_SET_STEAM_GENERATORS", {"mode": "relative-humidity", "relativeHumidity": {"setpoint": 0}}),
        ("CMD_APO_SET_STEAM_GENERATORS", {"mode": "relative-humidity", "relativeHumidity": {"setpoint": 100}}),
        ("CMD_APO_SET_LAMP", {"on": False}),
    ]
    assert hass.states.get("switch.test_oven_door_light").state == STATE_OFF
