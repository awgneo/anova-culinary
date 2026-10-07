"""Tests for the camera's live stream: WHEP viewers, the keep-alive, and stopping."""

from typing import Any
from unittest.mock import patch

from yarl import URL

import pytest

from custom_components.anova_culinary.anova_api.apo import stream
from custom_components.anova_culinary.anova_api.apo.device import AnovaPODevice
from custom_components.anova_culinary.anova_api.exceptions import AnovaConnectionError
from fakes import settle


class WhepResponse:
    """A WHEP endpoint's answer."""

    def __init__(self, status: int = 201) -> None:
        self.status = status

    url = URL("https://whep.example/oven")
    headers = {"Location": "/oven/session-1"}

    async def text(self) -> str:
        return "v=0 answer"

    async def __aenter__(self) -> "WhepResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


class WhepSession:
    """Records the offers posted and sessions deleted."""

    def __init__(self, refusals: int = 0) -> None:
        self.posts: list[tuple[str, str]] = []
        self.deletes: list[str] = []
        self.refusals = refusals

    def post(self, url: str, data: str, **kwargs: Any) -> WhepResponse:
        self.posts.append((url, data))
        return WhepResponse(500 if len(self.posts) <= self.refusals else 201)

    def delete(self, url: str, **kwargs: Any) -> WhepResponse:
        self.deletes.append(url)
        return WhepResponse()


class StreamClient:
    """Answers the oven's stream commands."""

    connected = True

    def __init__(self) -> None:
        self.session = WhepSession()
        self.commands: list[str] = []

    async def request(self, message: dict[str, Any]) -> dict[str, Any]:
        self.commands.append(message["command"])
        return {"status": "ok", "data": {"webRTCPlayback": {"url": "https://whep.example/oven"}}}


async def test_viewers() -> None:
    """Each viewer's offer is answered through WHEP; the stream stops a while after the last leaves."""
    client = StreamClient()
    oven = AnovaPODevice(client, "oven-1", "oven_v2")
    assert await oven.live_stream.watch("a", "v=0 offer a") == "v=0 answer"
    assert await oven.live_stream.watch("b", "v=0 offer b") == "v=0 answer"
    assert client.session.posts == [("https://whep.example/oven", "v=0 offer a"), ("https://whep.example/oven", "v=0 offer b")]
    with patch.object(stream, "STOP_DELAY", 0):
        await oven.live_stream.leave("a")
        await settle()
        assert "CMD_APO_STOP_LIVE_STREAM" not in client.commands
        await oven.live_stream.leave("b")
        await settle()
    assert client.session.deletes == ["https://whep.example/oven/session-1"] * 2
    assert client.commands[-1] == "CMD_APO_STOP_LIVE_STREAM"


async def test_reopening_reuses_the_stream() -> None:
    """A viewer back within the grace period keeps the stream running: no stop and restart."""
    client = StreamClient()
    oven = AnovaPODevice(client, "oven-1", "oven_v2")
    await oven.live_stream.watch("a", "v=0 offer")
    await oven.live_stream.leave("a")
    await settle()
    await oven.live_stream.watch("b", "v=0 offer")
    await settle()
    assert "CMD_APO_STOP_LIVE_STREAM" not in client.commands
    with patch.object(stream, "STOP_DELAY", 0):
        await oven.live_stream.leave("b")
        await settle()
    assert client.commands[-1] == "CMD_APO_STOP_LIVE_STREAM"


async def test_keep_alive() -> None:
    """The start is re-sent while anyone watches, as the app does every minute."""
    client = StreamClient()
    oven = AnovaPODevice(client, "oven-1", "oven_v2")
    with patch.object(stream, "KEEP_ALIVE", 0), patch.object(stream, "STOP_DELAY", 0):
        await oven.live_stream.watch("a", "v=0 offer")
        await settle()
        await oven.live_stream.leave("a")
        await settle()
    assert client.commands.count("CMD_APO_START_LIVE_STREAM") > 1


async def test_refusals_are_retried() -> None:
    """A refused offer is posted again, as the app's client does."""
    client = StreamClient()
    client.session = WhepSession(refusals=2)
    oven = AnovaPODevice(client, "oven-1", "oven_v2")
    with patch.object(stream, "RETRY_DELAY", 0):
        assert await oven.live_stream.watch("a", "v=0 offer") == "v=0 answer"
    assert len(client.session.posts) == 3
    with patch.object(stream, "STOP_DELAY", 0):
        await oven.live_stream.leave("a")
        await settle()


async def test_refused_viewer_stops_the_stream() -> None:
    """A viewer refused on every attempt is an error, and the stream it started stops."""
    client = StreamClient()
    client.session = WhepSession(refusals=10**9)
    oven = AnovaPODevice(client, "oven-1", "oven_v2")
    with patch.object(stream, "RETRY_DELAY", 0), patch.object(stream, "STOP_DELAY", 0):
        with pytest.raises(AnovaConnectionError, match="500"):
            await oven.live_stream.watch("a", "v=0 offer")
        await settle()
    assert len(client.session.posts) == stream.OFFER_ATTEMPTS
    assert client.commands == ["CMD_APO_START_LIVE_STREAM", "CMD_APO_STOP_LIVE_STREAM"]
