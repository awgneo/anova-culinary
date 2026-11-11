"""Tests for the WebSocket connection: the app's handshake, responses, events and reconnects."""

import asyncio
from unittest.mock import patch

import pytest

from custom_components.anova_culinary.anova_api import auth, connection
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


# A token lifetime that makes the first token roll over almost at once
SHORT_LIVED = 3600 - 0.05


async def rolled_over() -> None:
    """Waits out a short-lived token's rollover."""
    await asyncio.sleep(0.1)
    await settle()


async def test_first_reconnect_is_immediate(session: FakeSession, events) -> None:
    """A drop is retried at once; RECONNECT_DELAY only spaces the retries after."""
    conn, _ = events
    with patch.object(connection, "RECONNECT_DELAY", 60):
        await session.socket.close()
        await settle()
    assert len(session.sockets) == 2
    assert conn.connected


async def test_rolls_over_before_the_token_expires(session: FakeSession) -> None:
    """A fresh token gets a new socket, the old one closes, and no drop is reported."""
    changes: list[bool] = []
    conn = AnovaConnection(session, AnovaAuth(session, "refresh-token"), lambda _: None, on_connection=changes.append)
    with patch.object(auth, "REFRESH_MARGIN", SHORT_LIVED):
        await conn.connect()
    await rolled_over()
    first, second = session.sockets
    assert first.closed
    assert not second.closed
    assert conn.connected
    assert changes == [True]
    await conn.request({"command": "CMD_APO_STOP", "payload": {}})
    assert [message["command"] for message in second.sent] == ["CMD_APO_STOP"]
    assert first.sent == []
    await conn.close()


async def test_rollover_answers_commands_in_flight(session: FakeSession) -> None:
    """A command sent before a rollover is answered on its own socket, which closes after."""
    conn = AnovaConnection(session, AnovaAuth(session, "refresh-token"), lambda _: None)
    with patch.object(auth, "REFRESH_MARGIN", SHORT_LIVED):
        await conn.connect()
    first = session.socket
    first.responder = None
    pending = asyncio.ensure_future(conn.request({"command": "CMD_APO_STOP", "payload": {}}))
    await settle()
    await rolled_over()
    assert len(session.sockets) == 2
    assert not first.closed
    first.push({"command": "RESPONSE", "requestId": first.sent[0]["requestId"], "payload": {"status": "ok"}})
    assert await pending == {"status": "ok"}
    await settle()
    assert first.closed
    assert conn.connected
    await conn.close()


async def test_failed_rollover_keeps_the_socket(session: FakeSession) -> None:
    """A rollover that can't open a socket keeps the open one and tries again."""
    changes: list[bool] = []
    conn = AnovaConnection(session, AnovaAuth(session, "refresh-token"), lambda _: None, on_connection=changes.append)
    with patch.object(auth, "REFRESH_MARGIN", SHORT_LIVED):
        await conn.connect()
    with patch.object(connection, "RECONNECT_DELAY", 0.05):
        session.unreachable = True
        await rolled_over()
        assert len(session.sockets) == 1
        assert conn.connected
        session.unreachable = False
        await rolled_over()
    first, second = session.sockets
    assert first.closed
    assert not second.closed
    assert changes == [True]
    await conn.close()


async def test_sign_in_revoked_at_rollover(session: FakeSession) -> None:
    """A sign-in refused at rollover drops the connection and is reported once."""
    changes: list[bool] = []
    errors: list[AnovaAuthError] = []
    conn = AnovaConnection(
        session,
        AnovaAuth(session, "refresh-token"),
        lambda _: None,
        on_connection=changes.append,
        on_auth_error=errors.append,
    )
    with patch.object(auth, "REFRESH_MARGIN", SHORT_LIVED):
        await conn.connect()
        session.refused = 401
        await rolled_over()
    assert not conn.connected
    assert changes == [True, False]
    assert len(errors) == 1
    await conn.close()


async def test_close_during_rollover_closes_every_socket(session: FakeSession) -> None:
    """Closing while a rolled-over socket still waits on a command closes it too."""
    conn = AnovaConnection(session, AnovaAuth(session, "refresh-token"), lambda _: None)
    with patch.object(auth, "REFRESH_MARGIN", SHORT_LIVED):
        await conn.connect()
    session.socket.responder = None
    pending = asyncio.ensure_future(conn.request({"command": "CMD_APO_STOP", "payload": {}}))
    await settle()
    await rolled_over()
    await conn.close()
    assert all(socket.closed for socket in session.sockets)
    with pytest.raises(AnovaConnectionError):
        await pending
