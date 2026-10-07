"""The recipe format (models.py) to and from the oven's own stages (StageV2).

A port of the Anova Oven app's converter, transformRawStagesToV2 (PROTOCOL.md, part 2,
§4.4), so a recipe reaches the oven exactly as the app would send it, and a cook started
from the app reads back into the recipe format:

- A timer ends its stage when it completes. When it starts: immediately has no condition;
  when preheated, manually and when food is detected all follow a preheat (a stage entry
  on the bulb's temperature), then wait for that temperature, a user action, or the camera.
- A probe target ends its stage when the probe reaches it; neither runs until stopped.
- A stage's transition is written on the stage before it: manual makes it end on a user
  action, food removed adds the camera seeing the cavity empty.
"""

import copy
from collections.abc import Iterator
from typing import Any

from .commands import generate_id, heating_elements_payload, probe_payload, steam_generators_payload, temperature_bulbs_payload
from .limits import normalize_stage, steam_mode
from .models import (
    AnovaPOFanSpeed,
    AnovaPOHeatingElement,
    AnovaPOProbe,
    AnovaPORecipe,
    AnovaPOStage,
    AnovaPOTimer,
    AnovaPOTimerTrigger,
    AnovaPOTransition,
    to_celsius,
)
from .state import AnovaPOCook

DEFAULT_RACK = 3

# The node paths the app's conditions use
USER_ACTION = "userAction"
CAVITY_EMPTY = "nodes.cavityCamera.isEmpty"
TIMER_MODE = "nodes.timer.mode"
PROBE_CURRENT = "nodes.temperatureProbe.current.celsius"


def bulb_current(mode: str) -> str:
    """The path of a bulb's current temperature."""
    return f"nodes.temperatureBulbs.{mode}.current.celsius"


def preheat_conditions(mode: str, celsius: float) -> dict[str, Any]:
    """The cavity has reached the target."""
    return {"and": {bulb_current(mode): {">=": celsius}}}


def timer_conditions(trigger: AnovaPOTimerTrigger, mode: str, celsius: float) -> dict[str, Any] | None:
    """When a timer starts, as the timer's entry conditions (none for immediately)."""
    if trigger == AnovaPOTimerTrigger.PREHEATED:
        return preheat_conditions(mode, celsius)
    if trigger == AnovaPOTimerTrigger.MANUALLY:
        return {"and": {USER_ACTION: {"=": True}}}
    if trigger == AnovaPOTimerTrigger.FOOD_DETECTED:
        return {"or": {USER_ACTION: {"=": True}, CAVITY_EMPTY: {"=": False}}}
    return None


def stages_to_payload(stages: list[AnovaPOStage]) -> list[dict[str, Any]]:
    """A recipe's stages as the oven's, each first made valid (limits.normalize_stage)."""
    payload = [stage_to_payload(normalize_stage(stage)) for stage in stages]
    for previous, stage in zip(payload, stages[1:]):
        exit_conditions = previous["exit"]["conditions"]
        if stage.transition == AnovaPOTransition.MANUAL:
            exit_conditions["and"] = {USER_ACTION: {"=": True}}
        elif stage.transition == AnovaPOTransition.FOOD_REMOVED:
            exit_conditions["and"][CAVITY_EMPTY] = {"=": True}
    return payload


def stage_to_payload(stage: AnovaPOStage) -> dict[str, Any]:
    """One stage as the oven's (its transition is written by stages_to_payload)."""
    celsius = stage.celsius
    elements = stage.heating_elements
    do: dict[str, Any] = {
        "type": "cook",
        "fan": {"speed": stage.fan.speed},
        "heatingElements": heating_elements_payload(elements.top, elements.bottom, elements.rear),
        "exhaustVent": {"state": "closed"},
        "temperatureBulbs": temperature_bulbs_payload(stage.mode, celsius),
    }
    if stage.steam > 0:
        do["steamGenerators"] = steam_generators_payload(steam_mode(celsius), stage.steam)
    result: dict[str, Any] = {
        "id": stage.id or generate_id(),
        "title": "",
        "rackPosition": stage.rack or DEFAULT_RACK,
        "do": do,
        "exit": {"conditions": {"and": {}}},
    }
    advance = stage.advance
    if isinstance(advance, AnovaPOTimer):
        do["timer"] = {"initial": advance.duration}
        _set_timer_trigger(result, advance.trigger, stage.mode, celsius)
        result["exit"]["conditions"]["and"] = {TIMER_MODE: {"=": "completed"}}
    elif isinstance(advance, AnovaPOProbe):
        target = to_celsius(advance.target, stage.temperature_unit)
        do["temperatureProbe"] = probe_payload(target)
        result["exit"]["conditions"]["and"] = {PROBE_CURRENT: {">=": target}}
    return result


def with_timer_trigger(stage: dict[str, Any], trigger: AnovaPOTimerTrigger) -> dict[str, Any]:
    """An oven stage with its timer started by `trigger` instead, everything else kept."""
    stage = copy.deepcopy(stage)
    bulbs = stage.get("do", {}).get("temperatureBulbs", {})
    mode = bulbs.get("mode", "dry")
    celsius = bulbs.get(mode, {}).get("setpoint", {}).get("celsius", 0.0)
    _set_timer_trigger(stage, trigger, mode, celsius)
    return stage


def _set_timer_trigger(stage: dict[str, Any], trigger: AnovaPOTimerTrigger, mode: str, celsius: float) -> None:
    """Writes the timer's entry conditions, and the preheat every trigger but immediately follows."""
    timer = stage["do"].setdefault("timer", {"initial": 0})
    timer.pop("entry", None)
    timer.pop("startType", None)
    stage.pop("entry", None)
    if (conditions := timer_conditions(trigger, mode, celsius)) is not None:
        timer["entry"] = {"conditions": conditions}
    if trigger != AnovaPOTimerTrigger.IMMEDIATELY:
        stage["entry"] = {"conditions": preheat_conditions(mode, celsius)}


def payload_to_stages(stages: list[dict[str, Any]]) -> list[AnovaPOStage]:
    """The oven's stages in the recipe format (temperatures in Celsius)."""
    result = [stage_from_payload(stage) for stage in stages]
    for previous, stage in zip(stages, result[1:]):
        stage.transition = _transition(previous.get("exit") or {})
    return result


def stage_from_payload(stage: dict[str, Any]) -> AnovaPOStage:
    """One oven stage in the recipe format."""
    do = stage.get("do") or {}
    bulbs = do.get("temperatureBulbs") or {}
    mode = bulbs.get("mode", "dry")
    elements = do.get("heatingElements") or {}
    speed = (do.get("fan") or {}).get("speed", 100)
    timer = do.get("timer")
    probe = (do.get("temperatureProbe") or {}).get("setpoint", {}).get("celsius")
    advance: AnovaPOTimer | AnovaPOProbe | None = None
    if timer is not None:
        advance = AnovaPOTimer(duration=int(timer.get("initial", 0)), trigger=_trigger(timer))
    elif probe:
        advance = AnovaPOProbe(target=probe)
    return AnovaPOStage(
        id=stage.get("id", ""),
        sous_vide=mode == "wet",
        temperature=bulbs.get(mode, {}).get("setpoint", {}).get("celsius", 0.0),
        temperature_unit="C",
        steam=_steam(do.get("steamGenerators") or {}),
        heating_elements=AnovaPOHeatingElement.of(
            *(bool((elements.get(name) or {}).get("on")) for name in ("top", "bottom", "rear"))
        ),
        fan=AnovaPOFanSpeed.of(speed) if isinstance(speed, int | float) else AnovaPOFanSpeed.HIGH,
        advance=advance,
        rack=stage.get("rackPosition"),
    )


def recipe_from_cook(cook: AnovaPOCook) -> AnovaPORecipe:
    """A running cook (the app's or ours) as a recipe."""
    return AnovaPORecipe(title=cook.cook_title or cook.title or "", stages=payload_to_stages(cook.stages))


def _steam(steam: dict[str, Any]) -> int:
    """A stage's steam setpoint (0 without steam)."""
    key = "relativeHumidity" if steam.get("mode") == "relative-humidity" else "steamPercentage"
    return int((steam.get(key) or {}).get("setpoint", 0))


def _trigger(timer: dict[str, Any]) -> AnovaPOTimerTrigger:
    """When a timer starts, from its entry conditions (or the schema's startType)."""
    paths = dict(_conditions(((timer.get("entry") or {}).get("conditions")) or {}))
    if CAVITY_EMPTY in paths or timer.get("startType") == "on-detection":
        return AnovaPOTimerTrigger.FOOD_DETECTED
    if USER_ACTION in paths or timer.get("startType") == "manual":
        return AnovaPOTimerTrigger.MANUALLY
    if any(path.startswith("nodes.temperatureBulbs.") for path in paths) or timer.get("startType") == "when-preheated":
        return AnovaPOTimerTrigger.PREHEATED
    return AnovaPOTimerTrigger.IMMEDIATELY


def _transition(exit: dict[str, Any]) -> AnovaPOTransition:
    """How the next stage begins, from this stage's exit conditions."""
    paths = dict(_conditions(exit.get("conditions") or {}))
    if USER_ACTION in paths:
        return AnovaPOTransition.MANUAL
    if (paths.get(CAVITY_EMPTY) or {}).get("=") is True:
        return AnovaPOTransition.FOOD_REMOVED
    return AnovaPOTransition.AUTOMATIC


def _conditions(conditions: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every (node path, condition) in a condition tree, through its and/or groups."""
    for key, value in conditions.items():
        if key in ("and", "or"):
            yield from _conditions(value or {})
        elif isinstance(value, dict):
            yield key, value
