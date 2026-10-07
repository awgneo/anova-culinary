"""Fakes and fixtures for the anova_api tests: Anova's cloud, without a network."""

import asyncio
import json
from pathlib import Path
from typing import Any

import aiohttp
import jsonschema

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> Any:
    """A JSON fixture."""
    return json.loads((FIXTURES / name).read_text())


def validator(schema: str) -> jsonschema.Draft7Validator:
    """A validator for one of the app's own schemas (test/fixtures/schemas)."""
    return jsonschema.Draft7Validator(fixture(f"schemas/{schema}.schema.json"))


OVEN_COMMAND = validator("IOvenCommand")
OVEN_STATE = validator("OvenStateV2")


def assert_oven_command(message: dict[str, Any]) -> None:
    """Asserts a built command is one the app's schema accepts."""
    errors = [error.message for error in OVEN_COMMAND.iter_errors({**message, "requestId": "test"})]
    assert not errors, errors


class FakeMessage:
    """A WebSocket text frame."""

    def __init__(self, data: str) -> None:
        self.type = aiohttp.WSMsgType.TEXT
        self.data = data


class FakeWebSocket:
    """A WebSocket whose frames tests push and whose sends tests read."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._frames: asyncio.Queue[FakeMessage | None] = asyncio.Queue()
        self.responder: Any = None

    def push(self, message: dict[str, Any]) -> None:
        """Delivers a message from Anova."""
        self._frames.put_nowait(FakeMessage(json.dumps(message)))

    async def send_str(self, text: str) -> None:
        message = json.loads(text)
        self.sent.append(message)
        if self.responder is not None:
            if (response := self.responder(message)) is not None:
                self.push(response)

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._frames.put_nowait(None)

    def exception(self) -> None:
        return None

    def __aiter__(self) -> "FakeWebSocket":
        return self

    async def __anext__(self) -> FakeMessage:
        frame = await self._frames.get()
        if frame is None:
            raise StopAsyncIteration
        return frame


def ok(message: dict[str, Any], data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Anova's response accepting a command."""
    payload: dict[str, Any] = {"status": "ok"}
    if data is not None:
        payload["data"] = data
    return {"command": "RESPONSE", "requestId": message["requestId"], "payload": payload}


class FakeSession:
    """An aiohttp session whose WebSockets are FakeWebSockets and whose sign-in always works."""

    def __init__(self) -> None:
        self.sockets: list[FakeWebSocket] = []
        self.connects: list[dict[str, Any]] = []
        self.responder: Any = ok
        self.refused: int | None = None

    async def ws_connect(self, url: str, **kwargs: Any) -> FakeWebSocket:
        self.connects.append({"url": url, **kwargs})
        if self.refused is not None:
            raise aiohttp.WSServerHandshakeError(None, (), status=self.refused)
        socket = FakeWebSocket()
        socket.responder = self.responder
        self.sockets.append(socket)
        return socket

    @property
    def socket(self) -> FakeWebSocket:
        """The latest WebSocket."""
        return self.sockets[-1]

    def post(self, url: str, **kwargs: Any) -> "FakeResponse":
        return FakeResponse(200, {"id_token": "id-token", "refresh_token": "refresh-token", "expires_in": "3600", "user_id": "user"})


class FakeResponse:
    """An aiohttp response, as a context manager."""

    def __init__(self, status: int, data: Any) -> None:
        self.status = status
        self._data = data

    async def json(self, **kwargs: Any) -> Any:
        return self._data

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


async def settle() -> None:
    """Lets the client's reader handle what was pushed."""
    for _ in range(5):
        await asyncio.sleep(0)
