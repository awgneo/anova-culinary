"""The cavity camera's live stream, played over WebRTC through its WHEP URL.

As the Anova Oven app does (PROTOCOL.md, part 2, §3.5): CMD_APO_START_LIVE_STREAM returns
a Cloudflare WHEP URL and is re-sent every 60 seconds while anyone watches;
CMD_APO_STOP_LIVE_STREAM ends it. Each viewer posts its SDP offer to the URL (WHEP).
The oven streams only while cooking.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import aiohttp
from yarl import URL

from ..exceptions import AnovaConnectionError

if TYPE_CHECKING:
    from .device import AnovaPODevice

_LOGGER = logging.getLogger(__name__)

KEEP_ALIVE = 60
# Like the app's WHEP client, an offer the stream refuses is posted again after a doubling
# delay from 500 ms; one more attempt than the app's three, since our stream often starts
# just as the viewer opens
OFFER_ATTEMPTS = 4
RETRY_DELAY = 0.5
# After the last viewer leaves, the stream keeps running this long, so reopening the view
# reuses it rather than restarting it
STOP_DELAY = 30
# The STUN server the app gives its WebRTC player
STUN_SERVER = "stun:stun.cloudflare.com:3478"


class AnovaPOLiveStream:
    """The oven's stream and its viewers (WHEP sessions)."""

    def __init__(self, device: AnovaPODevice, session: aiohttp.ClientSession) -> None:
        """Initialize."""
        self._device = device
        self._session = session
        self._viewers: dict[str, str | None] = {}  # viewer -> WHEP resource URL
        self._keep_alive: asyncio.Task[None] | None = None
        self._stopping: asyncio.Task[None] | None = None

    async def watch(self, viewer: str, offer_sdp: str) -> str:
        """Starts the stream if needed and returns the SDP answer for a viewer's offer."""
        self._cancel_stop()
        url = await self._device.start_live_stream()
        try:
            answer, resource = await self._connect(url, offer_sdp)
        except AnovaConnectionError:
            # Nobody ended up watching: stop the stream the oven started, after the grace period
            if not self._viewers:
                self._schedule_stop()
            raise
        self._viewers[viewer] = resource
        if self._keep_alive is None:
            self._keep_alive = asyncio.create_task(self._keep_streaming())
        return answer

    async def _connect(self, url: str, offer_sdp: str) -> tuple[str, str | None]:
        """Posts a viewer's offer, retrying as the app does: the answer and the session's resource URL."""
        error = AnovaConnectionError("The camera stream refused the viewer")
        for attempt in range(OFFER_ATTEMPTS):
            if attempt:
                await asyncio.sleep(RETRY_DELAY * 2 ** (attempt - 1))
            try:
                status, answer, resource = await self._offer(url, offer_sdp)
            except AnovaConnectionError as err:
                error = err
                continue
            if status in (200, 201):
                return answer, resource
            error = AnovaConnectionError(f"The camera stream refused the viewer ({status}): {answer}")
            _LOGGER.debug("The camera stream refused the viewer (%s), attempt %d of %d", status, attempt + 1, OFFER_ATTEMPTS)
        raise error

    async def _offer(self, url: str, offer_sdp: str) -> tuple[int, str, str | None]:
        """Posts an SDP offer (WHEP): the status, the answer, and the session's resource URL."""
        try:
            async with self._session.post(
                url, data=offer_sdp, headers={"Content-Type": "application/sdp"}, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                location = response.headers.get("Location")
                resource = str(response.url.join(URL(location))) if location else None
                answer = await response.text()
                _LOGGER.debug("WHEP offer:\n%s\nanswered %s:\n%s", offer_sdp, response.status, answer)
                return response.status, answer, resource
        except aiohttp.ClientError as err:
            raise AnovaConnectionError(f"Couldn't reach the camera stream: {err}") from err

    async def leave(self, viewer: str) -> None:
        """Ends a viewer's session, and the stream after the last one."""
        if viewer not in self._viewers:
            return
        if resource := self._viewers.pop(viewer):
            try:
                async with self._session.delete(resource, timeout=aiohttp.ClientTimeout(total=10)):
                    pass
            except aiohttp.ClientError as err:
                _LOGGER.debug("Couldn't end the camera session: %s", err)
        if not self._viewers:
            self._schedule_stop()

    def _schedule_stop(self) -> None:
        """Stops the stream after STOP_DELAY, unless a viewer comes back."""
        self._cancel_stop()
        self._stopping = asyncio.create_task(self._stop_later())

    def _cancel_stop(self) -> None:
        """Keeps the stream: a viewer arrived during the grace period."""
        if self._stopping is not None:
            self._stopping.cancel()
            self._stopping = None

    async def _stop_later(self) -> None:
        """Stops the stream once STOP_DELAY passes with nobody watching."""
        await asyncio.sleep(STOP_DELAY)
        self._stopping = None
        if self._viewers:
            return
        if self._keep_alive is not None:
            self._keep_alive.cancel()
            self._keep_alive = None
        try:
            await self._device.stop_live_stream()
        except Exception as err:  # noqa: BLE001 - the stream ends on its own without keep-alives
            _LOGGER.debug("Stopping the camera stream failed: %s", err)

    async def _keep_streaming(self) -> None:
        """Re-sends the start every KEEP_ALIVE seconds while anyone watches."""
        while self._viewers:
            await asyncio.sleep(KEEP_ALIVE)
            try:
                await self._device.start_live_stream()
            except Exception as err:  # noqa: BLE001 - keep trying while anyone watches
                _LOGGER.debug("Keeping the camera stream alive failed: %s", err)

