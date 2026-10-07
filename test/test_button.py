"""Tests for the descale button."""

from homeassistant.const import STATE_UNAVAILABLE


async def test_descale(hass, sent) -> None:
    """Descaling starts on an idle oven; it's unavailable while cooking."""
    assert hass.states.get("button.test_oven_descale").state == STATE_UNAVAILABLE
    await hass.services.async_call("button", "press", {"entity_id": "button.idle_oven_descale"}, blocking=True)
    assert [command for command, _ in sent.commands] == ["CMD_APO_START_DESCALE"]
