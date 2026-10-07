"""The cavity camera's live stream, played over WebRTC through its WHEP URL.

As the Anova Oven app does (PROTOCOL.md, part 2, §3.5): CMD_APO_START_LIVE_STREAM returns
a Cloudflare WHEP URL and is re-sent every 60 seconds while anyone watches;
CMD_APO_STOP_LIVE_STREAM ends it. Each viewer posts its SDP offer to the URL (WHEP).
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
# The oven takes a few seconds to start broadcasting after the start command; until it does,
# the WHEP URL answers 409. Like the app's WHEP client, retry with a doubling delay (from
# 500 ms), here for up to BROADCAST_WAIT seconds since the stream starts when a viewer opens.
BROADCAST_WAIT = 20
RETRY_DELAY = 0.5
RETRY_DELAY_MAX = 4.0
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

    async def watch(self, viewer: str, offer_sdp: str) -> str:
        """Starts the stream if needed and returns the SDP answer for a viewer's offer."""
        url = await self._device.start_live_stream()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + BROADCAST_WAIT
        delay = RETRY_DELAY
        try:
            while True:
                status, answer, resource = await self._offer(url, offer_sdp)
                if status in (200, 201):
                    break
                if status != 409 or loop.time() + delay > deadline:
                    raise AnovaConnectionError(f"The camera stream refused the viewer ({status}): {answer}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, RETRY_DELAY_MAX)
        except AnovaConnectionError:
            # Nobody ended up watching: stop the stream the oven started for this viewer
            if not self._viewers:
                await self._device.stop_live_stream()
            raise
        self._viewers[viewer] = resource
        if self._keep_alive is None:
            self._keep_alive = asyncio.create_task(self._keep_streaming())
        return answer

    async def _offer(self, url: str, offer_sdp: str) -> tuple[int, str, str | None]:
        """Posts an SDP offer (WHEP): the status, the answer, and the session's resource URL."""
        try:
            async with self._session.post(
                url, data=offer_sdp, headers={"Content-Type": "application/sdp"}, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                location = response.headers.get("Location")
                resource = str(response.url.join(URL(location))) if location else None
                return response.status, await response.text(), resource
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
            if self._keep_alive is not None:
                self._keep_alive.cancel()
                self._keep_alive = None
            await self._device.stop_live_stream()

    async def _keep_streaming(self) -> None:
        """Re-sends the start every KEEP_ALIVE seconds while anyone watches."""
        while self._viewers:
            await asyncio.sleep(KEEP_ALIVE)
            try:
                await self._device.start_live_stream()
            except Exception as err:  # noqa: BLE001 - keep trying while anyone watches
                _LOGGER.debug("Keeping the camera stream alive failed: %s", err)
