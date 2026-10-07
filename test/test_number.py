"""Tests for the oven's steam and timer numbers, and the adjust_timer action."""

from homeassistant.const import STATE_UNAVAILABLE


async def set_value(hass, entity_id: str, value: float) -> None:
    await hass.services.async_call("number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True)


async def test_states(hass, sent) -> None:
    """Steam and the timer (minutes) come from the running stage."""
    assert hass.states.get("number.test_oven_steam").state == "100"
    assert hass.states.get("number.test_oven_timer").state == "5"
    assert hass.states.get("number.idle_oven_timer").state == STATE_UNAVAILABLE


async def test_commands(hass, sent) -> None:
    """Steam and the timer's length change alone."""
    await set_value(hass, "number.test_oven_steam", 50)
    await set_value(hass, "number.test_oven_timer", 20)
    assert sent.commands == [
        ("CMD_APO_SET_STEAM_GENERATORS", {"mode": "relative-humidity", "relativeHumidity": {"setpoint": 50}}),
        ("CMD_APO_SET_TIMER", {"initial": 1200}),
    ]


async def test_adjust_timer(hass, sent) -> None:
    """adjust_timer adds minutes to the timer entity."""
    await hass.services.async_call(
        "anova_culinary", "adjust_timer", {"entity_id": "number.test_oven_timer", "amount": 10}, blocking=True
    )
    assert sent.commands == [("CMD_APO_SET_TIMER", {"initial": 900})]
