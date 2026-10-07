"""Tests for the oven limits: the app's MANUAL_COOK_VALIDATION_RULES."""

import pytest

from custom_components.anova_culinary.anova_api.apo import limits
from custom_components.anova_culinary.anova_api.apo.models import (
    AnovaPOFanSpeed,
    AnovaPOHeatingElement,
    AnovaPOProbe,
    AnovaPOStage,
    AnovaPOTimer,
    AnovaPOTimerTrigger,
)
from custom_components.anova_culinary.anova_api.exceptions import AnovaValidationError

E = AnovaPOHeatingElement
ALL_FANS = list(AnovaPOFanSpeed)
HIGH = [AnovaPOFanSpeed.HIGH]


@pytest.mark.parametrize(
    ("elements", "sous_vide", "steam", "fans", "high"),
    [
        (E.TOP_BOTTOM, False, 0, ALL_FANS, 250),
        (E.TOP, False, 0, ALL_FANS, 250),
        (E.BOTTOM, False, 0, ALL_FANS, 230),
        (E.REAR, False, 0, HIGH, 250),
        (E.TOP_REAR, False, 0, HIGH, 250),
        (E.BOTTOM_REAR, False, 0, HIGH, 250),
        (E.TOP, False, 30, HIGH, 250),
        (E.BOTTOM, False, 30, HIGH, 230),
        (E.REAR, True, 0, HIGH, 92),
        (E.TOP_BOTTOM, True, 0, HIGH, 92),
        (E.REAR, True, 100, HIGH, 98),
    ],
)
def test_rule_table(elements, sous_vide, steam, fans, high) -> None:
    """Allowed fans and the range for each combination, as the app's table has them."""
    assert limits.allowed_fans(sous_vide, elements, steam) == fans
    assert limits.temperature_range(sous_vide, elements, steam, AnovaPOFanSpeed.HIGH) == (25, high)


def test_proofing() -> None:
    """The bottom element alone with the fan off is proofing: up to 45 °C, so off isn't offered above it."""
    assert limits.temperature_range(False, E.BOTTOM, 0, AnovaPOFanSpeed.OFF) == (25, 45)
    assert limits.temperature_range(False, E.BOTTOM, 0, AnovaPOFanSpeed.LOW) == (25, 230)
    assert AnovaPOFanSpeed.OFF in limits.allowed_fans(False, E.BOTTOM, 0, 40)
    assert AnovaPOFanSpeed.OFF not in limits.allowed_fans(False, E.BOTTOM, 0, 200)
    proofing = limits.normalize_stage(AnovaPOStage(temperature=200, heating_elements=E.BOTTOM, fan=AnovaPOFanSpeed.OFF))
    assert (proofing.fan, proofing.temperature) == (AnovaPOFanSpeed.LOW, 200)


def test_steam_mode() -> None:
    """Relative humidity below 100 °C, a steam percentage from 100 °C."""
    assert limits.steam_mode(99.9) == "relative-humidity"
    assert limits.steam_mode(100) == "steam-percentage"


def test_validation() -> None:
    """Out-of-range values raise."""
    stage = AnovaPOStage(sous_vide=True, temperature=60)
    limits.validate_temperature(stage, 92)
    with pytest.raises(AnovaValidationError):
        limits.validate_temperature(stage, 93)
    with pytest.raises(AnovaValidationError):
        limits.validate_probe(0.5)
    with pytest.raises(AnovaValidationError):
        limits.validate_timer(limits.TIMER_MAX + 1)
    with pytest.raises(AnovaValidationError):
        limits.validate_steam(101)


def test_normalize_stage() -> None:
    """A stage is made valid the way the app's editor would."""
    stage = limits.normalize_stage(
        AnovaPOStage(
            temperature=500,
            temperature_unit="F",
            heating_elements=E.BOTTOM,
            fan=AnovaPOFanSpeed.LOW,
            advance=AnovaPOProbe(250),
        )
    )
    assert stage.fan == AnovaPOFanSpeed.LOW
    assert stage.temperature == 446.0  # 230 °C
    assert stage.advance == AnovaPOProbe(212.0)  # 100 °C
    rear = limits.normalize_stage(AnovaPOStage(temperature=200, fan=AnovaPOFanSpeed.OFF))
    assert rear.fan == AnovaPOFanSpeed.HIGH
    assert rear.temperature == 200
    timer = limits.normalize_stage(AnovaPOStage(temperature=200, advance=AnovaPOTimer(10**9, AnovaPOTimerTrigger.MANUALLY)))
    assert timer.advance.duration == limits.TIMER_MAX
