"""Tests for the oven's camera entity."""

from unittest.mock import AsyncMock, patch

from homeassistant.components.camera import WebRTCAnswer, WebRTCError
from homeassistant.components.camera.const import DATA_COMPONENT

from custom_components.anova_culinary.anova_api import AnovaConnectionError
from custom_components.anova_culinary.anova_api.apo.stream import AnovaPOLiveStream


async def test_webrtc(hass, sent) -> None:
    """A viewer's offer is answered by the oven's stream; a failure becomes a WebRTC error."""
    camera = hass.data[DATA_COMPONENT].get_entity("camera.test_oven_camera")
    messages = []
    with patch.object(AnovaPOLiveStream, "watch", AsyncMock(return_value="v=0 answer")) as watch:
        await camera.async_handle_async_webrtc_offer("v=0 offer", "session-1", messages.append)
    watch.assert_awaited_once_with("session-1", "v=0 offer")
    with patch.object(AnovaPOLiveStream, "watch", AsyncMock(side_effect=AnovaConnectionError("refused"))):
        await camera.async_handle_async_webrtc_offer("v=0 offer", "session-2", messages.append)
    assert isinstance(messages[0], WebRTCAnswer) and messages[0].answer == "v=0 answer"
    assert isinstance(messages[1], WebRTCError)
    assert camera.async_get_webrtc_client_configuration().configuration.ice_servers[0].urls == "stun:stun.cloudflare.com:3478"
