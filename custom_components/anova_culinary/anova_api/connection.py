"""The WebSocket to Anova's cloud, opened and kept the way the Anova apps do.

See PROTOCOL.md, part 1, §2: the URL and its query, the ANOVA_V2 subprotocol, a flat
5-second reconnect, and every command answered by a RESPONSE matched on its requestId.
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

import aiohttp

from .auth import AnovaAuth
from .exceptions import AnovaAuthError, AnovaCommandError, AnovaConnectionError, AnovaTimeoutError

_LOGGER = logging.getLogger(__name__)

ANOVA_WS_URL = "wss://devices.anovaculinary.io"
ANOVA_WS_PROTOCOL = "ANOVA_V2"
ANOVA_WS_HEADERS = {
    "Origin": "https://devices.anovaculinary.io",
    "User-Agent": "okhttp/4.12.0",
}
SUPPORTED_ACCESSORIES = "APC,APO"
RECONNECT_DELAY = 5
COMMAND_TIMEOUT = 10
# The apps send no pings; we do, so a silently dropped socket is noticed
HEARTBEAT = 30


class AnovaConnection:
    """One WebSocket: sends commands, awaits their responses, and passes events on."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: AnovaAuth,
        on_event: Callable[[dict[str, Any]], None],
        on_connection: Callable[[bool], None] | None = None,
        on_auth_error: Callable[[AnovaAuthError], None] | None = None,
    ) -> None:
        """Initialize; `on_event` gets every message that isn't a response.

        `on_connection` hears each drop and reconnect; `on_auth_error` hears that Anova no
        longer accepts the sign-in, after which reconnecting stops.
        """
        self._session = session
        self._auth = auth
        self._on_event = on_event
        self._on_connection = on_connection
        self._on_auth_error = on_auth_error
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._closing = False

    @property
    def connected(self) -> bool:
        """Whether the WebSocket is open."""
        return self._ws is not None and not self._ws.closed

    async def connect(self) -> None:
        """Opens the WebSocket and keeps it open until `close()`.

        Raises AnovaAuthError if the sign-in is no longer valid and AnovaConnectionError if
        Anova can't be reached; after this first connection, drops are retried forever.
        """
        self._closing = False
        await self._open()
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        """Closes the WebSocket for good."""
        self._closing = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._fail_pending(AnovaConnectionError("The connection was closed"))

    async def request(self, message: dict[str, Any], timeout: float = COMMAND_TIMEOUT) -> dict[str, Any]:
        """Sends a command and returns its response's payload.

        Raises AnovaConnectionError if not connected, AnovaTimeoutError if no response comes,
        and AnovaCommandError if the device rejects it.
        """
        if not self.connected:
            raise AnovaConnectionError("Not connected to Anova")
        request_id = str(uuid.uuid4())
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            text = json.dumps({**message, "requestId": request_id})
            _LOGGER.debug("Sending %s", text)
            await self._ws.send_str(text)
            async with asyncio.timeout(timeout):
                return await future
        except TimeoutError as err:
            raise AnovaTimeoutError(f"{message.get('command')} got no response in {timeout:g}s") from err
        finally:
            self._pending.pop(request_id, None)

    async def _open(self) -> None:
        """Opens one WebSocket with a fresh token."""
        token = await self._auth.get_valid_token()
        url = f"{ANOVA_WS_URL}?token={token}&supportedAccessories={SUPPORTED_ACCESSORIES}&platform=android"
        try:
            self._ws = await self._session.ws_connect(
                url,
                protocols=(ANOVA_WS_PROTOCOL,),
                headers=ANOVA_WS_HEADERS,
                heartbeat=HEARTBEAT,
                timeout=aiohttp.ClientWSTimeout(ws_close=10),
            )
        except aiohttp.WSServerHandshakeError as err:
            if err.status in (401, 403):
                raise AnovaAuthError("Anova rejected the sign-in token") from err
            raise AnovaConnectionError(f"Anova refused the connection: {err}") from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AnovaConnectionError(f"Couldn't reach Anova: {err}") from err
        _LOGGER.debug("Connected to Anova")
        if self._on_connection:
            self._on_connection(True)

    async def _run(self) -> None:
        """Reads until the socket closes, then reconnects after RECONNECT_DELAY."""
        while not self._closing:
            try:
                await self._read()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Anova connection failed")
            self._fail_pending(AnovaConnectionError("The connection dropped"))
            if self._closing:
                return
            _LOGGER.warning("Lost the connection to Anova; reconnecting")
            if self._on_connection:
                self._on_connection(False)
            await self._reconnect()

    async def _reconnect(self) -> None:
        """Retries every RECONNECT_DELAY until connected or closed."""
        while not self._closing:
            await asyncio.sleep(RECONNECT_DELAY)
            try:
                await self._open()
                _LOGGER.info("Reconnected to Anova")
                return
            except AnovaAuthError as err:
                _LOGGER.warning("Anova no longer accepts the sign-in: %s", err)
                self._closing = True
                if self._on_auth_error:
                    self._on_auth_error(err)
            except AnovaConnectionError as err:
                _LOGGER.debug("Reconnecting to Anova failed: %s", err)

    async def _read(self) -> None:
        """Dispatches messages until the socket closes or the token is about to expire."""
        ws = self._ws
        if ws is None or ws.closed:
            return
        # Reconnect with a fresh token before this one expires
        expiry = asyncio.get_running_loop().call_later(
            max(0.0, self._auth.expires_at - time.time()), lambda: asyncio.ensure_future(ws.close())
        )
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._dispatch(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.debug("Anova WebSocket error: %s", ws.exception())
                    break
        finally:
            expiry.cancel()

    def _dispatch(self, text: str) -> None:
        """Resolves a response, or passes an event on."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            _LOGGER.warning("Anova sent a message that isn't JSON: %s", text)
            return
        _LOGGER.debug("Received %s", text)
        future = self._pending.get(data.get("requestId", ""))
        if future is not None:
            if not future.done():
                payload = data.get("payload") or {}
                if payload.get("status") == "ok":
                    future.set_result(payload)
                else:
                    error = data.get("error") or payload.get("error") or "Unknown error occurred"
                    future.set_exception(AnovaCommandError(str(error)))
            return
        if data.get("command") == "RESPONSE":
            return
        self._on_event(data)

    def _fail_pending(self, error: Exception) -> None:
        """Fails every command still waiting for a response."""
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

