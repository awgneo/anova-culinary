"""Tests for third-generation cookers: their state and commands, from the app's schema."""

from typing import Any

import pytest

from custom_components.anova_culinary.anova_api.apc import AnovaPCDevice, AnovaPCTemperatureUnit
from custom_components.anova_culinary.anova_api.exceptions import AnovaValidationError

# A Gen 3 SousVideState, as the app's schema describes it
COOKER_STATE: dict[str, Any] = {
    "version": 1,
    "updatedTimestamp": "2026-10-01T12:00:00Z",
    "state": {"mode": "cook", "temperatureUnit": "F", "processedCommandIds": []},
    "nodes": {
        "waterTemperatureSensor": {"current": {"celsius": 55.2}, "setpoint": {"celsius": 56.5}, "enabled": True},
        "timer": {"mode": "running", "initial": 5400, "startedAtTimestamp": "2026-10-01T11:00:00Z"},
        "lowWater": {"empty": False, "warning": True},
    },
    "cook": {
        "cookId": "c1",
        "activeStageId": "s1",
        "activeStageIndex": 0,
        "activeStageMode": "running",
        "activeStageStartedTimestamp": "2026-10-01T11:00:00Z",
        "startedTimestamp": "2026-10-01T11:00:00Z",
        "stageTransitionPendingUserAction": False,
        "originSource": "android",
        "cookableType": "manual",
    },
    "systemInfo": {
        "deviceId": "cooker-1",
        "firmwareVersion": "1.2.3",
        "hardwareVersion": "a7",
        "releaseTrack": "production",
        "online": True,
        "triacsFailed": False,
        "firmwareUpdatedTimestamp": "2026-01-01T00:00:00Z",
        "lastConnectedTimestamp": "2026-10-01T00:00:00Z",
        "lastDisconnectedTimestamp": "2026-09-30T00:00:00Z",
    },
}


class FakeClient:
    """Records the commands a device sends."""

    connected = True

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def request(self, message: dict[str, Any]) -> dict[str, Any]:
        self.sent.append(message)
        return {"status": "ok"}


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def cooker(client: FakeClient) -> AnovaPCDevice:
    cooker = AnovaPCDevice(client, "cooker-1", "a7")
    cooker.update(COOKER_STATE)
    return cooker


def test_state(cooker: AnovaPCDevice) -> None:
    """Readings come from the state, in Celsius, with the display unit alongside."""
    assert cooker.name == "Anova Precision Cooker 3.0"
    assert cooker.is_cooking and cooker.available
    assert (cooker.temperature, cooker.target_temperature, cooker.unit) == (55.2, 56.5, AnovaPCTemperatureUnit.F)
    assert not cooker.state.is_low_water
    assert cooker.state.cook.cookable_type == "manual"


async def test_commands(cooker: AnovaPCDevice, client: FakeClient) -> None:
    """Commands carry the cooker's id and type, and a second requestId, as the app's do."""
    await cooker.set_target_temperature(140, AnovaPCTemperatureUnit.F)
    await cooker.set_timer(3600)
    await cooker.stop()
    await cooker.start(56.5, AnovaPCTemperatureUnit.C, 5400)
    commands = [message["command"] for message in client.sent]
    assert commands == ["CMD_APC_SET_TARGET_TEMP", "CMD_APC_SET_TIMER", "CMD_APC_STOP", "CMD_APC_START"]
    start = client.sent[-1]["payload"]
    assert {k: v for k, v in start.items() if k != "requestId"} == {
        "cookerId": "cooker-1",
        "type": "a7",
        "targetTemperature": 56.5,
        "unit": "C",
        "timer": 5400,
    }
    assert start["requestId"]


async def test_limits(cooker: AnovaPCDevice) -> None:
    """Targets and timers outside the app's limits raise."""
    with pytest.raises(AnovaValidationError):
        await cooker.start(100, AnovaPCTemperatureUnit.C)
    with pytest.raises(AnovaValidationError):
        await cooker.set_target_temperature(212, AnovaPCTemperatureUnit.F)
    with pytest.raises(AnovaValidationError):
        await cooker.set_timer(359941)
