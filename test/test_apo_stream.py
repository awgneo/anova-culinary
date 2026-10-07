"""Tests for the camera's live stream: WHEP viewers, the keep-alive, and stopping."""

from typing import Any
from unittest.mock import patch

from yarl import URL

from custom_components.anova_culinary.anova_api.apo import stream
from custom_components.anova_culinary.anova_api.apo.device import AnovaPODevice
from fakes import settle


class WhepResponse:
    """A WHEP endpoint's answer."""

    status = 201
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

    def __init__(self) -> None:
        self.posts: list[tuple[str, str]] = []
        self.deletes: list[str] = []

    def post(self, url: str, data: str, **kwargs: Any) -> WhepResponse:
        self.posts.append((url, data))
        return WhepResponse()

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
    """Each viewer's offer is answered through WHEP; the stream stops after the last leaves."""
    client = StreamClient()
    oven = AnovaPODevice(client, "oven-1", "oven_v2")
    assert await oven.live_stream.watch("a", "v=0 offer a") == "v=0 answer"
    assert await oven.live_stream.watch("b", "v=0 offer b") == "v=0 answer"
    assert client.session.posts == [("https://whep.example/oven", "v=0 offer a"), ("https://whep.example/oven", "v=0 offer b")]
    await oven.live_stream.leave("a")
    assert "CMD_APO_STOP_LIVE_STREAM" not in client.commands
    await oven.live_stream.leave("b")
    assert client.session.deletes == ["https://whep.example/oven/session-1"] * 2
    assert client.commands[-1] == "CMD_APO_STOP_LIVE_STREAM"


async def test_keep_alive() -> None:
    """The start is re-sent while anyone watches, as the app does every minute."""
    client = StreamClient()
    oven = AnovaPODevice(client, "oven-1", "oven_v2")
    with patch.object(stream, "KEEP_ALIVE", 0):
        await oven.live_stream.watch("a", "v=0 offer")
        await settle()
        await oven.live_stream.leave("a")
    assert client.commands.count("CMD_APO_START_LIVE_STREAM") > 1
