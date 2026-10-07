"""Camera platform for Anova Precision Ovens: the cavity camera's live feed over WebRTC."""

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    WebRTCAnswer,
    WebRTCClientConfiguration,
    WebRTCError,
    WebRTCSendMessage,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from webrtc_models import RTCConfiguration, RTCIceCandidateInit, RTCIceServer

from . import AnovaConfigEntry
from .anova_api import AnovaDevice, AnovaException, AnovaPODevice
from .anova_api.apo.stream import STUN_SERVER
from .entity import AnovaEntity, AnovaEntityDescription, async_setup_device_entities, is_cooking

PARALLEL_UPDATES = 0

# The oven streams only while cooking
CAMERA = AnovaEntityDescription(key="camera", translation_key="camera", available_fn=is_cooking)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Anova camera platform."""

    def entities_for(device: AnovaDevice) -> list[Camera]:
        return [AnovaCamera(device, CAMERA)] if isinstance(device, AnovaPODevice) else []

    async_setup_device_entities(hass, entry, async_add_entities, entities_for)


class AnovaCamera(AnovaEntity[AnovaPODevice], Camera):
    """The oven's cavity camera; it streams only while cooking, with no still images."""

    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, device: AnovaPODevice, description: AnovaEntityDescription) -> None:
        """Initialize the camera."""
        AnovaEntity.__init__(self, device, description)
        Camera.__init__(self)

    @property
    def entity_picture(self) -> str | None:
        """No still image, so the frontend shows the icon rather than a broken picture."""
        return None

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        """The oven offers no still images."""
        return None

    async def async_handle_async_webrtc_offer(
        self, offer_sdp: str, session_id: str, send_message: WebRTCSendMessage
    ) -> None:
        """Answer a viewer's offer through the oven's WHEP stream."""
        try:
            answer = await self.device.live_stream.watch(session_id, offer_sdp)
        except AnovaException as err:
            send_message(WebRTCError("anova_stream_failed", str(err)))
            return
        send_message(WebRTCAnswer(answer))

    async def async_on_webrtc_candidate(self, session_id: str, candidate: RTCIceCandidateInit) -> None:
        """The stream gathers its own candidates; a viewer's trickled ones aren't needed."""

    @callback
    def close_webrtc_session(self, session_id: str) -> None:
        """End a viewer's session."""
        self.hass.async_create_task(self.device.live_stream.leave(session_id))

    @callback
    def _async_get_webrtc_client_configuration(self) -> WebRTCClientConfiguration:
        """Use the STUN server the app's player uses."""
        return WebRTCClientConfiguration(configuration=RTCConfiguration(ice_servers=[RTCIceServer(urls=STUN_SERVER)]))
