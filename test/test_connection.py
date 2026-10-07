"""Tests for the WebSocket connection: the app's handshake, responses, events and reconnects."""

import asyncio
from unittest.mock import patch

import pytest

from custom_components.anova_culinary.anova_api import connection
from custom_components.anova_culinary.anova_api.auth import AnovaAuth
from custom_components.anova_culinary.anova_api.connection import AnovaConnection
from custom_components.anova_culinary.anova_api.exceptions import (
    AnovaAuthError,
    AnovaCommandError,
    AnovaConnectionError,
    AnovaTimeoutError,
)
from fakes import FakeSession, settle


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
async def events(session: FakeSession):
    """A connected AnovaConnection, and the events it passed on."""
    received: list[dict] = []
    conn = AnovaConnection(session, AnovaAuth(session, "refresh-token"), received.append)
    await conn.connect()
    yield conn, received
    await conn.close()


async def test_connects_like_the_app(session: FakeSession, events) -> None:
    """The URL, subprotocol and headers are the Oven app's."""
    connect = session.connects[0]
    assert connect["url"] == "wss://devices.anovaculinary.io?token=id-token&supportedAccessories=APC,APO&platform=android"
    assert connect["protocols"] == ("ANOVA_V2",)
    assert connect["headers"] == {"Origin": "https://devices.anovaculinary.io", "User-Agent": "okhttp/4.12.0"}


async def test_request_returns_the_response(session: FakeSession, events) -> None:
    """A command resolves with its response's payload, matched on requestId."""
    conn, _ = events
    session.socket.responder = lambda message: {
        "command": "RESPONSE",
        "requestId": message["requestId"],
        "payload": {"status": "ok", "data": {"x": 1}},
    }
    response = await conn.request({"command": "CMD_APO_STOP", "payload": {}})
    assert response == {"status": "ok", "data": {"x": 1}}
    assert session.socket.sent[0]["command"] == "CMD_APO_STOP"


async def test_request_rejected(session: FakeSession, events) -> None:
    """A response that isn't ok raises its error."""
    conn, _ = events
    session.socket.responder = lambda message: {
        "command": "RESPONSE",
        "requestId": message["requestId"],
        "payload": {"status": "error", "error": "oven busy"},
    }
    with pytest.raises(AnovaCommandError, match="oven busy"):
        await conn.request({"command": "CMD_APO_STOP", "payload": {}})


async def test_request_times_out(session: FakeSession, events) -> None:
    """A command without a response times out."""
    conn, _ = events
    session.socket.responder = None
    with pytest.raises(AnovaTimeoutError):
        await conn.request({"command": "CMD_APO_STOP", "payload": {}}, timeout=0.01)


async def test_events_are_passed_on(session: FakeSession, events) -> None:
    """Messages that aren't responses reach the event handler."""
    _, received = events
    session.socket.push({"command": "EVENT_APO_WIFI_LIST", "payload": []})
    await settle()
    assert received == [{"command": "EVENT_APO_WIFI_LIST", "payload": []}]


async def test_reconnects_after_a_drop(session: FakeSession, events) -> None:
    """A dropped socket reconnects after the delay, failing commands in flight."""
    conn, _ = events
    session.socket.responder = None
    pending = asyncio.ensure_future(conn.request({"command": "CMD_APO_STOP", "payload": {}}))
    await settle()
    with patch.object(connection, "RECONNECT_DELAY", 0):
        await session.socket.close()
        with pytest.raises(AnovaConnectionError):
            await pending
        await settle()
    assert len(session.sockets) == 2
    assert conn.connected


async def test_rejected_sign_in(session: FakeSession) -> None:
    """A refused handshake is an auth error."""
    session.refused = 401
    conn = AnovaConnection(session, AnovaAuth(session, "refresh-token"), lambda _: None)
    with pytest.raises(AnovaAuthError):
        await conn.connect()


async def test_not_connected(session: FakeSession) -> None:
    """Commands need a connection."""
    conn = AnovaConnection(session, AnovaAuth(session, "refresh-token"), lambda _: None)
    with pytest.raises(AnovaConnectionError):
        await conn.request({"command": "CMD_APO_STOP"})


async def test_sign_in_revoked_while_reconnecting(session: FakeSession) -> None:
    """A sign-in Anova stops accepting ends reconnecting and is reported once."""
    errors: list[AnovaAuthError] = []
    conn = AnovaConnection(session, AnovaAuth(session, "refresh-token"), lambda _: None, on_auth_error=errors.append)
    await conn.connect()
    session.refused = 401
    with patch.object(connection, "RECONNECT_DELAY", 0):
        await session.socket.close()
        await settle()
    assert len(errors) == 1
    assert not conn.connected
    await conn.close()


async def test_connection_changes_are_reported(session: FakeSession) -> None:
    """Drops and reconnects are reported."""
    changes: list[bool] = []
    conn = AnovaConnection(session, AnovaAuth(session, "refresh-token"), lambda _: None, on_connection=changes.append)
    await conn.connect()
    with patch.object(connection, "RECONNECT_DELAY", 0):
        await session.socket.close()
        await settle()
    assert changes == [True, False, True]
    await conn.close()
