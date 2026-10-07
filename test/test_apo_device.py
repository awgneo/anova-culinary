"""Tests for the oven device: its state, and each control sending the app's command."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.anova_culinary.anova_api.apo.device import AnovaPODevice
from custom_components.anova_culinary.anova_api.apo.models import (
    AnovaPOFanSpeed,
    AnovaPOHeatingElement,
    AnovaPORecipe,
    AnovaPOStage,
    AnovaPOTimerTrigger,
)
from custom_components.anova_culinary.anova_api.exceptions import AnovaValidationError
from fakes import assert_oven_command, fixture


class FakeClient:
    """Records the commands a device sends."""

    connected = True

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def request(self, message: dict[str, Any]) -> dict[str, Any]:
        assert_oven_command(message)
        self.sent.append(message)
        if message["command"] == "CMD_APO_START_LIVE_STREAM":
            return {"status": "ok", "data": {"webRTCPlayback": {"url": "https://whep.example/oven"}}}
        return {"status": "ok"}

    @property
    def commands(self) -> list[tuple[str, Any]]:
        """(command, inner payload) for each sent."""
        return [(m["command"], m["payload"].get("payload")) for m in self.sent]


def oven_state() -> dict[str, Any]:
    """The app's sous vide cook (rear element, steam 100, timer on food detection)."""
    return fixture("apo_state.json")["payload"]["state"]


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def oven(client: FakeClient) -> AnovaPODevice:
    oven = AnovaPODevice(client, "oven-1", "oven_v2", "Left Oven")
    oven.update(oven_state())
    return oven


@pytest.fixture
def idle(client: FakeClient) -> AnovaPODevice:
    state = oven_state()
    state["state"]["mode"] = "idle"
    del state["cook"]
    oven = AnovaPODevice(client, "oven-2", "oven_v2", "Right Oven")
    oven.update(state)
    return oven


def test_state(oven: AnovaPODevice) -> None:
    """The running stage and readings come from the state."""
    assert oven.is_cooking
    assert oven.model == "Anova Precision Oven 2.0"
    assert oven.temperature == 24.96  # the wet bulb, since it's sous vide
    assert oven.probe_temperature is None
    assert oven.lamp_on
    stage = oven.current_stage
    assert stage.sous_vide and stage.temperature == 54.44 and stage.steam == 100
    assert oven.recipe.stages[0].id == stage.id


def test_timer_remaining(oven: AnovaPODevice) -> None:
    """A running timer counts down from when it started."""
    timer = oven.state.nodes.timer
    assert oven.timer_remaining == 300
    timer.mode = "running"
    timer.started_at_timestamp = (datetime.now(UTC) - timedelta(seconds=100)).isoformat()
    assert 198 <= oven.timer_remaining <= 200
    timer.mode = "completed"
    assert oven.timer_remaining == 0


async def test_start_manual(idle: AnovaPODevice, client: FakeClient) -> None:
    """Starting from a temperature is a one-stage manual cook."""
    await idle.start_manual(AnovaPOStage(temperature=200))
    (command, payload), = client.commands
    assert command == "CMD_APO_START"
    assert payload["cookableType"] == "manual"
    assert payload["stages"][0]["do"]["temperatureBulbs"] == {"mode": "dry", "dry": {"setpoint": {"celsius": 200}}}


async def test_start_recipe(idle: AnovaPODevice, client: FakeClient) -> None:
    """A recipe starts with its title and every stage."""
    recipe = AnovaPORecipe(title="Egg Bites", stages=[AnovaPOStage(temperature=200), AnovaPOStage(temperature=180)])
    await idle.start_recipe(recipe)
    (command, payload), = client.commands
    assert (command, payload["title"], payload["cookableType"], len(payload["stages"])) == ("CMD_APO_START", "Egg Bites", "recipe", 2)
    with pytest.raises(AnovaValidationError):
        await idle.start_recipe(AnovaPORecipe())


async def test_controls_need_a_cook(idle: AnovaPODevice) -> None:
    """Every control but the light needs a running cook."""
    with pytest.raises(AnovaValidationError):
        await idle.set_temperature(200)


async def test_set_temperature(oven: AnovaPODevice, client: FakeClient) -> None:
    """The target changes on the stage's bulb, within its range."""
    await oven.set_temperature(60)
    assert client.commands == [("CMD_APO_SET_TEMPERATURE_BULBS", {"mode": "wet", "wet": {"setpoint": {"celsius": 60}}})]
    with pytest.raises(AnovaValidationError):
        await oven.set_temperature(99)


async def test_set_sous_vide(oven: AnovaPODevice, client: FakeClient) -> None:
    """Leaving sous vide keeps the target, on the dry bulb."""
    await oven.set_sous_vide(False)
    assert client.commands == [("CMD_APO_SET_TEMPERATURE_BULBS", {"mode": "dry", "dry": {"setpoint": {"celsius": 54.44}}})]


async def test_set_sous_vide_clamps(oven: AnovaPODevice, client: FakeClient) -> None:
    """Entering sous vide brings a dry target into the wet range."""
    state = oven_state()
    stage = state["cook"]["stages"][0]["do"]
    stage["temperatureBulbs"] = {"mode": "dry", "dry": {"setpoint": {"celsius": 200}}}
    oven.update(state)
    await oven.set_sous_vide(True)
    assert client.commands[-1] == ("CMD_APO_SET_TEMPERATURE_BULBS", {"mode": "wet", "wet": {"setpoint": {"celsius": 98}}})


async def test_set_steam(oven: AnovaPODevice, client: FakeClient) -> None:
    """Steam changes in the mode for the target; 0 turns it off."""
    await oven.set_steam(0)
    assert client.commands == [("CMD_APO_SET_STEAM_GENERATORS", {"mode": "relative-humidity", "relativeHumidity": {"setpoint": 0}})]


async def test_set_fan(oven: AnovaPODevice, client: FakeClient) -> None:
    """Sous vide only allows high; dry heat on the top element allows any speed."""
    with pytest.raises(AnovaValidationError):
        await oven.set_fan(AnovaPOFanSpeed.LOW)
    state = oven_state()
    stage = state["cook"]["stages"][0]["do"]
    stage["temperatureBulbs"] = {"mode": "dry", "dry": {"setpoint": {"celsius": 200}}}
    stage["heatingElements"] = {"top": {"on": True}, "bottom": {"on": False}, "rear": {"on": False}}
    del stage["steamGenerators"]
    oven.update(state)
    await oven.set_fan(AnovaPOFanSpeed.LOW)
    assert client.commands == [("CMD_APO_SET_FAN", {"speed": 33})]


async def test_set_heating_elements_raises_the_fan(oven: AnovaPODevice, client: FakeClient) -> None:
    """Switching to an element combination that needs the fan high raises it first."""
    state = oven_state()
    stage = state["cook"]["stages"][0]["do"]
    stage["temperatureBulbs"] = {"mode": "dry", "dry": {"setpoint": {"celsius": 200}}}
    stage["heatingElements"] = {"top": {"on": True}, "bottom": {"on": False}, "rear": {"on": False}}
    stage["fan"] = {"speed": 33}
    del stage["steamGenerators"]
    oven.update(state)
    await oven.set_heating_elements(AnovaPOHeatingElement.TOP_REAR)
    assert client.commands == [
        ("CMD_APO_SET_FAN", {"speed": 100}),
        ("CMD_APO_SET_HEATING_ELEMENTS", {"top": {"on": True}, "bottom": {"on": False}, "rear": {"on": True}}),
    ]


async def test_set_timer(oven: AnovaPODevice, client: FakeClient) -> None:
    """The timer's length changes alone."""
    await oven.set_timer(1200)
    assert client.commands == [("CMD_APO_SET_TIMER", {"initial": 1200})]


async def test_set_timer_trigger(oven: AnovaPODevice, client: FakeClient) -> None:
    """Changing when the timer starts resends the stages with only the running one changed."""
    await oven.set_timer_trigger(AnovaPOTimerTrigger.IMMEDIATELY)
    (command, payload), = client.commands
    assert command == "CMD_APO_UPDATE_COOK_STAGES"
    (stage,) = payload["stages"]
    assert "entry" not in stage["do"]["timer"]
    assert stage["id"] == oven.state.cook.active_stage_id


async def test_set_probe(oven: AnovaPODevice, client: FakeClient) -> None:
    """A probe target sets; None clears it."""
    await oven.set_probe(57)
    await oven.set_probe(None)
    assert client.commands == [
        ("CMD_APO_SET_PROBE", {"setpoint": {"celsius": 57}}),
        ("CMD_APO_SET_PROBE", {"setpoint": {"celsius": 0}}),
    ]


async def test_lamp_shows_until_confirmed(oven: AnovaPODevice, client: FakeClient) -> None:
    """The light shows its new state until the oven reports it."""
    await oven.set_lamp(False)
    assert client.commands == [("CMD_APO_SET_LAMP", {"on": False})]
    assert not oven.lamp_on
    state = oven_state()
    state["nodes"]["doorLamp"]["on"] = False
    oven.update(state)
    assert not oven.lamp_on


async def test_descale_and_stream(idle: AnovaPODevice, oven: AnovaPODevice, client: FakeClient) -> None:
    """Descaling needs an idle oven; the stream returns its WebRTC URL."""
    with pytest.raises(AnovaValidationError):
        await oven.start_descale()
    await idle.start_descale()
    assert await idle.start_live_stream() == "https://whep.example/oven"
    await idle.stop_live_stream()
    assert [command for command, _ in client.commands] == [
        "CMD_APO_START_DESCALE",
        "CMD_APO_START_LIVE_STREAM",
        "CMD_APO_STOP_LIVE_STREAM",
    ]
