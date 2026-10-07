"""Tests for the recipe converter: the recipe format to and from the oven's stages, as the app encodes them."""

import pytest

from custom_components.anova_culinary.anova_api.apo import commands
from custom_components.anova_culinary.anova_api.apo.models import (
    AnovaPOFanSpeed,
    AnovaPOHeatingElement,
    AnovaPOProbe,
    AnovaPORecipe,
    AnovaPOStage,
    AnovaPOTimer,
    AnovaPOTimerTrigger,
    AnovaPOTransition,
)
from custom_components.anova_culinary.anova_api.apo.recipe import (
    payload_to_stages,
    recipe_from_cook,
    stages_to_payload,
    with_timer_trigger,
)
from custom_components.anova_culinary.anova_api.apo.state import AnovaPOState
from fakes import assert_oven_command, fixture


def app_cook() -> AnovaPOState:
    """A cook the Anova Oven app started (sous vide, timer on food detection)."""
    return AnovaPOState.from_dict(fixture("apo_state.json")["payload"]["state"])


def test_stored_recipes_load_unchanged() -> None:
    """A recipe saved before transitions and racks existed loads as it always did."""
    recipe = AnovaPORecipe.from_dict(
        {
            "name": "Easy Steamed Breakfast Egg Bites",
            "stages": [
                {
                    "id": "s1",
                    "sous_vide": True,
                    "temperature": 180,
                    "temperature_unit": "F",
                    "steam": 100,
                    "heating_elements": "rear",
                    "fan": "high",
                    "advance": {"duration": 2100, "trigger": "food_detected"},
                },
                {"id": "s2", "temperature": 350, "temperature_unit": "F", "heating_elements": "top", "advance": None},
            ],
        }
    )
    assert recipe.title == "Easy Steamed Breakfast Egg Bites"
    assert recipe.stages[0].advance == AnovaPOTimer(2100, AnovaPOTimerTrigger.FOOD_DETECTED)
    assert recipe.stages[1].transition == AnovaPOTransition.AUTOMATIC
    assert recipe.stages[1].rack is None
    assert recipe.to_dict()["name"] == "Easy Steamed Breakfast Egg Bites"


def test_app_cook_reads_back() -> None:
    """A cook from the app reads into the recipe format."""
    recipe = recipe_from_cook(app_cook().cook)
    (stage,) = recipe.stages
    assert stage.sous_vide
    assert stage.temperature == 54.44
    assert stage.steam == 100
    assert stage.heating_elements == AnovaPOHeatingElement.REAR
    assert stage.fan == AnovaPOFanSpeed.HIGH
    assert stage.advance == AnovaPOTimer(300, AnovaPOTimerTrigger.FOOD_DETECTED)


def test_app_cook_encodes_as_the_app_did() -> None:
    """Reading the app's stage and writing it back gives the app's conditions."""
    original = app_cook().cook.stages[0]
    (encoded,) = stages_to_payload(payload_to_stages([original]))
    assert encoded["entry"] == original["entry"]
    assert encoded["do"]["timer"] == original["do"]["timer"]
    assert encoded["exit"] == original["exit"]
    assert encoded["do"]["temperatureBulbs"] == original["do"]["temperatureBulbs"]
    assert encoded["do"]["steamGenerators"] == original["do"]["steamGenerators"]


@pytest.mark.parametrize(
    ("trigger", "timer_entry", "preheat"),
    [
        (AnovaPOTimerTrigger.IMMEDIATELY, None, False),
        (AnovaPOTimerTrigger.PREHEATED, {"and": {"nodes.temperatureBulbs.dry.current.celsius": {">=": 200}}}, True),
        (AnovaPOTimerTrigger.MANUALLY, {"and": {"userAction": {"=": True}}}, True),
        (
            AnovaPOTimerTrigger.FOOD_DETECTED,
            {"or": {"userAction": {"=": True}, "nodes.cavityCamera.isEmpty": {"=": False}}},
            True,
        ),
    ],
)
def test_timer_triggers(trigger, timer_entry, preheat) -> None:
    """Each timer start is encoded as the app encodes it, and reads back."""
    stage = AnovaPOStage(temperature=200, advance=AnovaPOTimer(600, trigger))
    (encoded,) = stages_to_payload([stage])
    assert encoded["do"]["timer"].get("entry", {}).get("conditions") == timer_entry
    assert ("entry" in encoded) == preheat
    assert encoded["exit"]["conditions"] == {"and": {"nodes.timer.mode": {"=": "completed"}}}
    assert payload_to_stages([encoded])[0].advance == AnovaPOTimer(600, trigger)


def test_probe_and_neither() -> None:
    """A probe target ends its stage at the target; neither runs until stopped."""
    probe, open_ended = stages_to_payload(
        [AnovaPOStage(temperature=200, advance=AnovaPOProbe(60)), AnovaPOStage(temperature=100)]
    )
    assert probe["do"]["temperatureProbe"] == {"setpoint": {"celsius": 60}}
    assert probe["exit"]["conditions"] == {"and": {"nodes.temperatureProbe.current.celsius": {">=": 60}}}
    assert "entry" not in probe
    assert open_ended["exit"]["conditions"] == {"and": {}}
    assert [stage.advance for stage in payload_to_stages([probe, open_ended])] == [AnovaPOProbe(60), None]


@pytest.mark.parametrize("transition", list(AnovaPOTransition))
def test_transitions(transition) -> None:
    """A stage's transition is written on the stage before it, and reads back."""
    stages = [
        AnovaPOStage(temperature=200, advance=AnovaPOTimer(600, AnovaPOTimerTrigger.IMMEDIATELY)),
        AnovaPOStage(temperature=180, transition=transition),
    ]
    first, _ = stages_to_payload(stages)
    exit_conditions = first["exit"]["conditions"]["and"]
    if transition == AnovaPOTransition.MANUAL:
        assert exit_conditions == {"userAction": {"=": True}}
    elif transition == AnovaPOTransition.FOOD_REMOVED:
        assert exit_conditions == {"nodes.timer.mode": {"=": "completed"}, "nodes.cavityCamera.isEmpty": {"=": True}}
    else:
        assert exit_conditions == {"nodes.timer.mode": {"=": "completed"}}
    assert payload_to_stages(stages_to_payload(stages))[1].transition == transition


def test_settings() -> None:
    """Units, fan speeds, steam modes, elements and rack are the app's."""
    low, high_steam, sous_vide = stages_to_payload(
        [
            AnovaPOStage(temperature=350, temperature_unit="F", heating_elements=AnovaPOHeatingElement.TOP, fan=AnovaPOFanSpeed.LOW, rack=2),
            AnovaPOStage(temperature=200, steam=30, heating_elements=AnovaPOHeatingElement.TOP_BOTTOM, fan=AnovaPOFanSpeed.MEDIUM),
            AnovaPOStage(sous_vide=True, temperature=60, steam=100),
        ]
    )
    assert low["do"]["temperatureBulbs"] == {"mode": "dry", "dry": {"setpoint": {"celsius": 176.67}}}
    assert low["do"]["fan"] == {"speed": 33}
    assert low["do"]["heatingElements"] == {"top": {"on": True}, "bottom": {"on": False}, "rear": {"on": False}}
    assert low["rackPosition"] == 2
    assert "steamGenerators" not in low["do"]
    # Steam needs the fan on high, and is a percentage at 100 °C and above
    assert high_steam["do"]["fan"] == {"speed": 100}
    assert high_steam["do"]["steamGenerators"] == {"mode": "steam-percentage", "steamPercentage": {"setpoint": 30}}
    assert sous_vide["do"]["steamGenerators"] == {"mode": "relative-humidity", "relativeHumidity": {"setpoint": 100}}
    assert sous_vide["rackPosition"] == 3


def test_with_timer_trigger_keeps_the_rest() -> None:
    """Changing a running stage's timer start leaves everything else as the app sent it."""
    original = app_cook().cook.stages[0]
    changed = with_timer_trigger(original, AnovaPOTimerTrigger.IMMEDIATELY)
    assert "entry" not in changed and "entry" not in changed["do"]["timer"]
    assert changed["do"]["timer"]["initial"] == original["do"]["timer"]["initial"]
    assert changed["exit"] == original["exit"]
    assert "entry" in original


def test_commands_match_the_app_schema() -> None:
    """Every command we build passes the app's own IOvenCommand schema."""
    stages = stages_to_payload(
        [
            AnovaPOStage(sous_vide=True, temperature=60, steam=100, advance=AnovaPOTimer(60, AnovaPOTimerTrigger.PREHEATED)),
            AnovaPOStage(temperature=200, steam=30, advance=AnovaPOProbe(60), transition=AnovaPOTransition.FOOD_REMOVED),
            AnovaPOStage(temperature=180, transition=AnovaPOTransition.MANUAL),
        ]
    )
    for message in (
        commands.build_start_command("oven", stages, "Test"),
        commands.build_update_cook_stages_command("oven", stages),
        commands.build_stop_command("oven"),
        commands.build_set_temperature_bulbs_command("oven", "wet", 60),
        commands.build_set_fan_command("oven", 67),
        commands.build_set_heating_elements_command("oven", True, False, True),
        commands.build_set_steam_generators_command("oven", "relative-humidity", 50),
        commands.build_set_timer_command("oven", 600),
        commands.build_set_probe_command("oven", 0),
        commands.build_set_lamp_command("oven", True),
        commands.build_start_descale_command("oven"),
        commands.build_start_live_stream_command("oven"),
        commands.build_stop_live_stream_command("oven"),
    ):
        assert_oven_command(message)


def test_every_start_is_a_new_cook() -> None:
    """Playing the same recipe twice starts two cooks."""
    stages = stages_to_payload([AnovaPOStage(temperature=200)])
    first = commands.build_start_command("oven", stages)["payload"]["payload"]["cookId"]
    second = commands.build_start_command("oven", stages)["payload"]["payload"]["cookId"]
    assert first != second
    assert first.startswith("android-")
