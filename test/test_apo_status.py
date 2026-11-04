"""Tests for the stage status: the app's stage states, read from the oven's v2 state."""

import copy
from typing import Any

import pytest

from custom_components.anova_culinary.anova_api.apo.device import AnovaPODevice
from custom_components.anova_culinary.anova_api.apo.state import AnovaPOState
from custom_components.anova_culinary.anova_api.apo.status import AnovaPOStageStatus as Status
from custom_components.anova_culinary.anova_api.apo.status import continue_stage_id, stage_status
from custom_components.anova_culinary.anova_api.exceptions import AnovaValidationError
from fakes import fixture
from test_apo_device import FakeClient

USER_ACTION = {"userAction": {"=": True}}
TIMER_DONE = {"nodes.timer.mode": {"=": "completed"}}


def cooking() -> dict[str, Any]:
    """The app's sous vide cook as captured: preheating (entering) to 54.44 °C, its 5 min timer
    starting when food is detected."""
    return copy.deepcopy(fixture("apo_state.json")["payload"]["state"])


def preheated(state: dict[str, Any]) -> dict[str, Any]:
    """The cavity at its target and the stage past its entry."""
    state["nodes"]["temperatureBulbs"]["wet"]["current"]["celsius"] = 54.44
    state["cook"]["activeStageMode"] = "running"
    return state


def timer(state: dict[str, Any], entry: dict[str, Any] | None = None, mode: str = "idle") -> dict[str, Any]:
    """The stage's timer started by `entry` (immediately without one), in `mode`."""
    stage_timer = state["cook"]["stages"][0]["do"]["timer"]
    stage_timer.pop("entry", None)
    if entry is not None:
        stage_timer["entry"] = {"conditions": entry}
    state["nodes"]["timer"] = {"initial": 300, "mode": mode} if mode != "completed" else {"mode": mode}
    return state


def second_stage(state: dict[str, Any], exit: dict[str, Any]) -> dict[str, Any]:
    """A second stage after the first, which ends on `exit`."""
    first = state["cook"]["stages"][0]
    first["exit"] = {"conditions": {"and": exit}}
    state["cook"]["stages"].append({**copy.deepcopy(first), "id": "stage-2"})
    return state


def probe(state: dict[str, Any], connected: bool, celsius: float | None = None) -> dict[str, Any]:
    """The stage ending on a 60 °C probe target instead of a timer."""
    stage = state["cook"]["stages"][0]
    del stage["do"]["timer"]
    stage["do"]["temperatureProbe"] = {"setpoint": {"celsius": 60}}
    stage["exit"] = {"conditions": {"and": {"nodes.temperatureProbe.current.celsius": {">=": 60}}}}
    node: dict[str, Any] = {"connected": connected}
    if celsius is not None:
        node["current"] = {"celsius": celsius}
    state["nodes"]["temperatureProbe"] = node
    return state


def status(state: dict[str, Any]) -> Status:
    return stage_status(AnovaPOState.from_dict(state))


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (cooking(), Status.PREHEATING),
        (preheated(cooking()), Status.ADD_FOOD),
        (timer(preheated(cooking()), {"and": USER_ACTION}), Status.START_TIMER),
        (timer(preheated(cooking()), {"and": USER_ACTION}, "running"), Status.COOKING),
        (timer(preheated(cooking()), None, "paused"), Status.COOKING),
        (timer(preheated(cooking()), None, "completed"), Status.HOLDING),
        (second_stage(timer(preheated(cooking()), None, "completed"), USER_ACTION), Status.START_NEXT_STAGE),
        (
            second_stage(timer(preheated(cooking()), None, "completed"), {**TIMER_DONE, "nodes.cavityCamera.isEmpty": {"=": True}}),
            Status.REMOVE_FOOD,
        ),
        (second_stage(timer(preheated(cooking()), None, "completed"), TIMER_DONE), Status.COOKING),
        (second_stage(timer(preheated(cooking()), None, "running"), USER_ACTION), Status.COOKING),
        (probe(preheated(cooking()), connected=False), Status.PLUG_IN_PROBE),
        (probe(preheated(cooking()), connected=True, celsius=40), Status.COOKING),
        (probe(preheated(cooking()), connected=True, celsius=60), Status.HOLDING),
    ],
    ids=[
        "preheating",
        "preheated, timer on food",
        "preheated, manual timer",
        "manual timer started",
        "timer paused",
        "timer done, last stage",
        "timer done, next stage manual",
        "timer done, next stage once food is out",
        "timer done, next stage automatic",
        "timer running before a manual stage",
        "probe target, probe out",
        "probe in, below target",
        "probe at target",
    ],
)
def test_status(state: dict[str, Any], expected: Status) -> None:
    """Each of the app's stage states, from the oven's state."""
    assert status(state) == expected


def test_preheat_to_a_probe() -> None:
    """A stage entered once the probe is in (as the app writes a probe stage after a preheat):
    preheating until the cavity is hot, then waiting for the probe."""
    state = probe(cooking(), connected=False)
    state["cook"]["stages"][0]["entry"] = {"conditions": {"and": {"nodes.temperatureProbe.connected": {"=": True}}}}
    assert status(state) == Status.PREHEATING
    state["nodes"]["temperatureBulbs"]["wet"]["current"]["celsius"] = 55
    assert status(state) == Status.PLUG_IN_PROBE


def test_preheat_without_the_ovens_word() -> None:
    """Without activeStageMode, a stage with a preheat is preheating until the cavity reaches the
    target, as the app compares them."""
    state = cooking()
    del state["cook"]["activeStageMode"]
    assert status(state) == Status.PREHEATING
    state["nodes"]["temperatureBulbs"]["wet"]["current"]["celsius"] = 54.5
    assert status(state) == Status.ADD_FOOD


def test_idle_and_descaling() -> None:
    """No cook is idle; descaling is its own."""
    state = cooking()
    state["state"]["mode"] = "idle"
    del state["cook"]
    assert status(state) == Status.IDLE
    state["state"]["mode"] = "descale"
    assert status(state) == Status.DESCALING
    assert stage_status(None) == Status.IDLE


def test_continue_stage() -> None:
    """Continue starts the running stage (its waiting timer) or, once finished, the next."""
    state = cooking()
    stage_id = state["cook"]["stages"][0]["id"]
    assert continue_stage_id(AnovaPOState.from_dict(state)) is None
    assert continue_stage_id(AnovaPOState.from_dict(preheated(cooking()))) == stage_id
    finished = second_stage(timer(preheated(cooking()), None, "completed"), USER_ACTION)
    assert continue_stage_id(AnovaPOState.from_dict(finished)) == "stage-2"


async def test_device_continue() -> None:
    """The oven's Continue sends the app's START_STAGE, and refuses while nothing waits."""
    client = FakeClient()
    oven = AnovaPODevice(client, "oven-1", "oven_v2", "Left Oven")
    oven.update(cooking())
    assert (oven.stage_status, oven.stage_number, oven.stage_count, oven.can_continue) == (Status.PREHEATING, 1, 1, False)
    with pytest.raises(AnovaValidationError):
        await oven.continue_cook()
    oven.update(timer(preheated(cooking()), {"and": USER_ACTION}))
    await oven.continue_cook()
    assert client.commands == [("CMD_APO_START_STAGE", {"stageId": oven.state.cook.active_stage_id})]
