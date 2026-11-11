"""The WebSocket to Anova's cloud, opened and kept the way the Anova apps do.

See PROTOCOL.md, part 1, §2: the URL and its query, the ANOVA_V2 subprotocol, a flat
5-second reconnect, and every command answered by a RESPONSE matched on its requestId.

The socket takes its token only when it opens, so before the token expires the connection rolls
over: it opens a socket with a fresh token, sends on it from then on, and closes the old one once
the commands sent on it have their responses. A rollover isn't a drop: nothing is reported, and
the devices stay available throughout.

Like the apps' command queue, a command sent while the socket is down waits for it to reopen and
is sent then, within the same COMMAND_TIMEOUT that bounds its response: a short drop delays a
command instead of failing it, and a command is never sent later than that.
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
        # Sockets rolled over from, each closing once its commands have their responses
        self._retiring: set[asyncio.Task[None]] = set()
        self._closing = False
        # Set (and replaced) each time the socket opens, drops or closes, waking commands waiting on it
        self._changed = asyncio.Event()

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
        for retiring in list(self._retiring):
            retiring.cancel()
        await asyncio.gather(*self._retiring, return_exceptions=True)
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._fail_pending(AnovaConnectionError("The connection was closed"))
        self._wake()

    async def request(self, message: dict[str, Any], timeout: float = COMMAND_TIMEOUT) -> dict[str, Any]:
        """Sends a command and returns its response's payload.

        A command sent while the socket is reconnecting waits for it, within the same timeout.
        Raises AnovaConnectionError if the socket isn't open in time (or the connection was
        closed), AnovaTimeoutError if no response comes, and AnovaCommandError if the device
        rejects it.
        """
        request_id = str(uuid.uuid4())
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        sent = False
        try:
            async with asyncio.timeout(timeout):
                await self._wait_connected()
                self._pending[request_id] = future
                text = json.dumps({**message, "requestId": request_id})
                _LOGGER.debug("Sending %s", text)
                await self._ws.send_str(text)
                sent = True
                return await future
        except TimeoutError as err:
            if not sent:
                raise AnovaConnectionError(f"Not connected to Anova for {timeout:g}s") from err
            raise AnovaTimeoutError(f"{message.get('command')} got no response in {timeout:g}s") from err
        finally:
            self._pending.pop(request_id, None)

    async def _wait_connected(self) -> None:
        """Waits for the socket to be open; raises AnovaConnectionError once it won't reopen."""
        while not self.connected:
            if self._closing or self._task is None:
                raise AnovaConnectionError("Not connected to Anova")
            await self._changed.wait()

    def _wake(self) -> None:
        """Wakes the commands waiting for the socket to check it again."""
        self._changed.set()
        self._changed = asyncio.Event()

    async def _open(self) -> None:
        """Opens the WebSocket and reports the connection."""
        self._ws = await self._open_socket()
        self._wake()
        _LOGGER.debug("Connected to Anova")
        if self._on_connection:
            self._on_connection(True)

    async def _open_socket(self) -> aiohttp.ClientWebSocketResponse:
        """Opens one WebSocket with a valid token."""
        token = await self._auth.get_valid_token()
        url = f"{ANOVA_WS_URL}?token={token}&supportedAccessories={SUPPORTED_ACCESSORIES}&platform=android"
        try:
            return await self._session.ws_connect(
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

    async def _run(self) -> None:
        """Reads until the socket drops, then reports it and reconnects."""
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
        """Retries at once, then every RECONNECT_DELAY, until connected or closed."""
        delay = 0.0
        while not self._closing:
            await asyncio.sleep(delay)
            delay = RECONNECT_DELAY
            try:
                await self._open()
                _LOGGER.info("Reconnected to Anova")
                return
            except AnovaAuthError as err:
                _LOGGER.warning("Anova no longer accepts the sign-in: %s", err)
                self._closing = True
                self._wake()
                if self._on_auth_error:
                    self._on_auth_error(err)
            except AnovaConnectionError as err:
                _LOGGER.debug("Reconnecting to Anova failed: %s", err)

    async def _read(self) -> None:
        """Reads until the socket closes, rolling over to a fresh token each time the token is about
        to expire. A rollover that fails is tried again every RECONNECT_DELAY on the socket still open."""
        ws = self._ws
        if ws is None or ws.closed:
            return
        reading = asyncio.ensure_future(self._receive(ws))
        try:
            rollover = self._auth.expires_at
            while True:
                done, _ = await asyncio.wait({reading}, timeout=max(0.0, rollover - time.time()))
                if reading in done:
                    reading.result()
                    return
                if await self._roll_over():
                    self._retire(ws, reading)
                    ws = self._ws
                    reading = asyncio.ensure_future(self._receive(ws))
                    rollover = self._auth.expires_at
                else:
                    rollover = time.time() + RECONNECT_DELAY
        except BaseException:
            reading.cancel()
            raise

    async def _receive(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Dispatches one socket's messages until it closes."""
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                self._dispatch(msg.data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                _LOGGER.debug("Anova WebSocket error: %s", ws.exception())
                break

    async def _roll_over(self) -> bool:
        """Opens a socket with a fresh token and sends on it from now on; whether it opened.

        A sign-in Anova no longer accepts closes the open socket, so reconnecting reports it.
        """
        try:
            ws = await self._open_socket()
        except AnovaAuthError as err:
            _LOGGER.debug("Rolling over to a fresh token was refused: %s", err)
            if self._ws is not None:
                await self._ws.close()
            return False
        except AnovaConnectionError as err:
            _LOGGER.debug("Rolling over to a fresh token failed: %s", err)
            return False
        self._ws = ws
        _LOGGER.debug("Rolled over to a fresh token")
        return True

    def _retire(self, ws: aiohttp.ClientWebSocketResponse, reading: asyncio.Task[None]) -> None:
        """Keeps reading a rolled-over socket until the commands sent on it have their responses
        (COMMAND_TIMEOUT at most), then closes it."""
        waiting = [future for future in self._pending.values() if not future.done()]

        async def retire() -> None:
            try:
                if waiting:
                    await asyncio.wait(waiting, timeout=COMMAND_TIMEOUT)
            finally:
                reading.cancel()
                await asyncio.gather(reading, return_exceptions=True)
                await ws.close()

        task = asyncio.create_task(retire())
        self._retiring.add(task)
        task.add_done_callback(self._retiring.discard)

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

