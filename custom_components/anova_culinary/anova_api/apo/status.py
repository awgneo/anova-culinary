"""Where the running stage is, as the Anova Oven app shows it (PROTOCOL.md, part 2, §2.1 and §6).

The app names a stage's state in its editor's model, where a preheat is a stage of its own
(`getStageStateById`: preheating, waiting for the user, cooking, holding, ...), from getters
on the oven's v2 state (`CommonOvenStateModel`: `hasPreheatCompleted`, `manualTimerSet`,
`timerComplete`, `probeComplete`, `isStageTransitionPendingUserAction`). The oven runs one v2
stage for both (the preheat is the stage's `entry`), so the same states are read from it here:

- Preheating: the stage's entry (the preheat) isn't met yet (`activeStageMode` "entering").
- Waiting for you: preheated with a timer that starts manually (start the timer) or when food
  is detected (add the food), a probe target without the probe in, or a finished stage whose
  next one starts manually (start it) or once the food is out (take it out).
- Cooking, then holding once the timer or probe target is reached with nothing after it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from .models import AnovaPOTimerTrigger
from .recipe import CAVITY_EMPTY, PROBE_CURRENT, USER_ACTION, condition_paths, timer_trigger
from .state import AnovaPOState

PROBE_CONNECTED = "nodes.temperatureProbe.connected"


class AnovaPOStageStatus(StrEnum):
    """Where an oven's cook is."""

    IDLE = "idle"
    DESCALING = "descaling"
    PREHEATING = "preheating"
    ADD_FOOD = "add_food"
    START_TIMER = "start_timer"
    PLUG_IN_PROBE = "plug_in_probe"
    COOKING = "cooking"
    START_NEXT_STAGE = "start_next_stage"
    REMOVE_FOOD = "remove_food"
    HOLDING = "holding"


# The states a Continue (the app's Start Timer / Start Stage) moves on from
CONTINUES = (AnovaPOStageStatus.START_TIMER, AnovaPOStageStatus.ADD_FOOD, AnovaPOStageStatus.START_NEXT_STAGE)


def stage_status(state: AnovaPOState | None) -> AnovaPOStageStatus:
    """The running stage's status."""
    if state is not None and state.status.mode == "descale":
        return AnovaPOStageStatus.DESCALING
    if state is None or not state.is_cooking or (stage := state.cook.active_stage) is None:
        return AnovaPOStageStatus.IDLE
    nodes = state.nodes
    do = stage.get("do") or {}
    entry = dict(condition_paths((stage.get("entry") or {}).get("conditions") or {}))
    exit = dict(condition_paths((stage.get("exit") or {}).get("conditions") or {}))
    timer = do.get("timer")
    probe_target = _probe_target(stage)
    preheated = _preheated(state)

    if entry and _entering(state, preheated):
        return AnovaPOStageStatus.PLUG_IN_PROBE if PROBE_CONNECTED in entry and preheated else AnovaPOStageStatus.PREHEATING
    probe = nodes.temperature_probe
    timer_complete = timer is not None and (nodes.timer.mode == "completed" or nodes.timer.initial is None)
    probe_complete = bool(probe_target and probe.connected and probe.current and probe.current.celsius >= probe_target)
    if timer_complete or probe_complete:
        if not has_next_stage(state):
            return AnovaPOStageStatus.HOLDING
        if USER_ACTION in exit:
            return AnovaPOStageStatus.START_NEXT_STAGE
        if (exit.get(CAVITY_EMPTY) or {}).get("=") is True:
            return AnovaPOStageStatus.REMOVE_FOOD
        return AnovaPOStageStatus.COOKING
    if timer is not None and nodes.timer.mode == "idle":
        trigger = timer_trigger(timer)
        if trigger == AnovaPOTimerTrigger.MANUALLY:
            return AnovaPOStageStatus.START_TIMER
        if trigger == AnovaPOTimerTrigger.FOOD_DETECTED:
            return AnovaPOStageStatus.ADD_FOOD
    if probe_target and not probe.connected:
        return AnovaPOStageStatus.PLUG_IN_PROBE
    return AnovaPOStageStatus.COOKING


def has_next_stage(state: AnovaPOState) -> bool:
    """Whether a stage follows the running one."""
    cook = state.cook
    return cook is not None and cook.active_stage_index + 1 < len(cook.stages)


def continue_stage_id(state: AnovaPOState | None) -> str | None:
    """The stage a Continue starts, as the app's buttons do: the running one again (which
    starts a timer waiting on the user or on food) or, once it's finished, the next."""
    status = stage_status(state)
    if status not in CONTINUES:
        return None
    cook = state.cook
    if status == AnovaPOStageStatus.START_NEXT_STAGE:
        return cook.stages[cook.active_stage_index + 1].get("id")
    return (cook.active_stage or {}).get("id")


def _entering(state: AnovaPOState, preheated: bool) -> bool:
    """Whether the stage's entry is still pending: the oven says so, or (without its word) the
    cavity hasn't reached the target, as the app compares them."""
    mode = state.cook.active_stage_mode
    return mode == "entering" if mode else not preheated


def _preheated(state: AnovaPOState) -> bool:
    """The app's hasPreheatCompleted: the regulated bulb at or above its target."""
    bulb = state.nodes.temperature_bulbs.active
    current, target = bulb.current.celsius, bulb.setpoint.celsius if bulb.setpoint else None
    return current is not None and target is not None and current >= target


def _probe_target(stage: dict[str, Any]) -> float | None:
    """The stage's probe target: its exit's, or (without one) its probe setpoint."""
    exit = dict(condition_paths((stage.get("exit") or {}).get("conditions") or {}))
    if (target := (exit.get(PROBE_CURRENT) or {}).get(">=")) is not None:
        return target
    return ((stage.get("do") or {}).get("temperatureProbe") or {}).get("setpoint", {}).get("celsius") or None
