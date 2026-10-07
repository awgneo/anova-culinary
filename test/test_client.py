"""Tests for Anova client: device lists, pairing changes and state routing."""

import pytest

from custom_components.anova_culinary.anova_api.apc import AnovaPCDevice
from custom_components.anova_culinary.anova_api.apo import AnovaPODevice
from custom_components.anova_culinary.anova_api.client import AnovaClient
from fakes import FakeSession, fixture, settle

OVEN = {"cookerId": "oven-1", "type": "oven_v2", "name": "Left Oven", "pairedAt": "2026-01-01T00:00:00Z"}
COOKER = {"cookerId": "cooker-1", "type": "a7", "name": "Sous Vide", "pairedAt": "2026-01-01T00:00:00Z"}


@pytest.fixture
async def client():
    session = FakeSession()
    client = AnovaClient("refresh-token", session)
    # Connect without waiting for a device list; each test pushes its own
    await client._connection.connect()
    yield client, session
    await client.close()


async def test_discovery(client) -> None:
    """Device lists create devices of the latest types only, two ovens included."""
    client, session = client
    changes: list[tuple[str, bool]] = []
    client.register_device_callback(lambda device, added: changes.append((device.id, added)))
    session.socket.push(
        {
            "command": "EVENT_APO_WIFI_LIST",
            "payload": [OVEN, {**OVEN, "cookerId": "oven-2", "name": "Right Oven"}, {**OVEN, "cookerId": "old", "type": "oven_v1"}],
        }
    )
    session.socket.push({"command": "EVENT_APC_WIFI_LIST", "payload": [COOKER, {**COOKER, "cookerId": "old-cooker", "type": "a5"}]})
    await settle()
    assert set(client.devices) == {"oven-1", "oven-2", "cooker-1"}
    assert isinstance(client.devices["oven-2"], AnovaPODevice)
    assert isinstance(client.devices["cooker-1"], AnovaPCDevice)
    assert client.devices["oven-1"].name == "Left Oven"
    assert client.devices["cooker-1"].model == "Anova Precision Cooker 3.0"
    assert ("oven-1", True) in changes


async def test_pairing_changes(client) -> None:
    """Added and removed events, and a new list, update the devices."""
    client, session = client
    session.socket.push({"command": "EVENT_APO_WIFI_LIST", "payload": [OVEN]})
    session.socket.push({"command": "EVENT_APO_WIFI_ADDED", "payload": {**OVEN, "cookerId": "oven-2"}})
    await settle()
    assert set(client.devices) == {"oven-1", "oven-2"}
    session.socket.push({"command": "EVENT_APO_WIFI_REMOVED", "payload": {"cookerId": "oven-1"}})
    await settle()
    assert set(client.devices) == {"oven-2"}
    session.socket.push({"command": "EVENT_APO_WIFI_LIST", "payload": [OVEN]})
    await settle()
    assert set(client.devices) == {"oven-1"}


async def test_state_reaches_its_device(client) -> None:
    """A state event updates only its own device and calls its listeners."""
    client, session = client
    session.socket.push({"command": "EVENT_APO_WIFI_LIST", "payload": [OVEN, {**OVEN, "cookerId": "oven-2"}]})
    await settle()
    calls: list[str] = []
    client.devices["oven-1"].register_callback(lambda: calls.append("oven-1"))
    client.devices["oven-2"].register_callback(lambda: calls.append("oven-2"))
    event = fixture("apo_state.json")
    event["payload"]["cookerId"] = "oven-1"
    session.socket.push(event)
    await settle()
    assert calls == ["oven-1"]
    oven = client.devices["oven-1"]
    assert oven.state.status.mode == "cook"
    assert oven.available
    assert client.devices["oven-2"].state is None


async def test_connection_changes_notify_devices(client) -> None:
    """Dropping the connection makes devices unavailable."""
    client, session = client
    session.socket.push({"command": "EVENT_APO_WIFI_LIST", "payload": [OVEN]})
    event = fixture("apo_state.json")
    event["payload"]["cookerId"] = "oven-1"
    session.socket.push(event)
    await settle()
    oven = client.devices["oven-1"]
    assert oven.available
    await client.close()
    assert not oven.available


async def test_connect_waits_for_the_device_list() -> None:
    """connect() returns once the device list arrives."""
    session = FakeSession()
    client = AnovaClient("refresh-token", session)
    original = session.ws_connect

    async def ws_connect(url, **kwargs):
        socket = await original(url, **kwargs)
        socket.push({"command": "EVENT_APO_WIFI_LIST", "payload": [OVEN]})
        return socket

    session.ws_connect = ws_connect
    await client.connect()
    assert set(client.devices) == {"oven-1"}
    assert client.user_id == "user"
    await client.close()
