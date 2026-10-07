"""Every rule the Anova Oven app enforces on a Precision Oven 2.0 stage, in one place.

From the app's temperatureRanges and MANUAL_COOK_VALIDATION_RULES (PROTOCOL.md, part 2,
§5). Temperatures are Celsius. Entities, the recipe converter and the panel all use these.
"""

from dataclasses import replace

from ..exceptions import AnovaValidationError
from .models import AnovaPOFanSpeed, AnovaPOHeatingElement, AnovaPOProbe, AnovaPOStage, AnovaPOTimer, from_celsius, to_celsius

TEMPERATURE_MIN = 25.0
DRY_MAX = 250.0
# The bottom element alone (Oven 2.0), and with the fan off: proofing
BOTTOM_MAX = 230.0
PROOFING_MAX = 45.0
# Sous vide (wet bulb), without and with steam
WET_MAX = 92.0
WET_STEAM_MAX = 98.0
PROBE_MIN = 1.0
PROBE_MAX = 100.0
STEAM_MAX = 100
TIMER_MAX = 359940  # 99 h 59 min
# At and above this target, steam is a steam percentage; below, relative humidity
STEAM_PERCENTAGE_FROM = 100.0

# The combinations that may run the fan below high (dry heat, no steam)
QUIET_ELEMENTS = (AnovaPOHeatingElement.TOP, AnovaPOHeatingElement.BOTTOM, AnovaPOHeatingElement.TOP_BOTTOM)


def allowed_fans(
    sous_vide: bool, elements: AnovaPOHeatingElement, steam: int, celsius: float | None = None
) -> list[AnovaPOFanSpeed]:
    """The fan speeds a stage may use: only high with steam, sous vide or the rear element;
    off with the bottom element alone only up to the proofing maximum (when `celsius` is known)."""
    if sous_vide or steam > 0 or elements not in QUIET_ELEMENTS:
        return [AnovaPOFanSpeed.HIGH]
    if elements == AnovaPOHeatingElement.BOTTOM and celsius is not None and celsius > PROOFING_MAX:
        return [fan for fan in AnovaPOFanSpeed if fan != AnovaPOFanSpeed.OFF]
    return list(AnovaPOFanSpeed)


def stage_fans(stage: AnovaPOStage) -> list[AnovaPOFanSpeed]:
    """The fan speeds a stage's other settings allow."""
    return allowed_fans(stage.sous_vide, stage.heating_elements, stage.steam, stage.celsius)


def temperature_range(
    sous_vide: bool, elements: AnovaPOHeatingElement, steam: int, fan: AnovaPOFanSpeed
) -> tuple[float, float]:
    """The target range for a stage's settings."""
    if sous_vide:
        return TEMPERATURE_MIN, WET_STEAM_MAX if steam > 0 else WET_MAX
    if elements == AnovaPOHeatingElement.BOTTOM:
        return TEMPERATURE_MIN, PROOFING_MAX if fan == AnovaPOFanSpeed.OFF and steam == 0 else BOTTOM_MAX
    return TEMPERATURE_MIN, DRY_MAX


def stage_range(stage: AnovaPOStage) -> tuple[float, float]:
    """The target range (Celsius) for a stage's other settings."""
    return temperature_range(stage.sous_vide, stage.heating_elements, stage.steam, stage.fan)


def steam_mode(celsius: float) -> str:
    """The steam mode the app uses at this target."""
    return "steam-percentage" if celsius >= STEAM_PERCENTAGE_FROM else "relative-humidity"


def validate_temperature(stage: AnovaPOStage, celsius: float) -> None:
    """Raises if `celsius` is outside the stage's range."""
    low, high = stage_range(stage)
    if not low <= celsius <= high:
        raise AnovaValidationError(f"{celsius:g} °C is outside {low:g}–{high:g} °C for these settings")


def validate_probe(celsius: float) -> None:
    """Raises if a probe target is out of range."""
    if not PROBE_MIN <= celsius <= PROBE_MAX:
        raise AnovaValidationError(f"The probe target must be {PROBE_MIN:g}–{PROBE_MAX:g} °C")


def validate_timer(seconds: int) -> None:
    """Raises if a timer is out of range."""
    if not 0 <= seconds <= TIMER_MAX:
        raise AnovaValidationError("The timer must be 0 to 99 h 59 min")


def validate_steam(steam: int) -> None:
    """Raises if a steam setpoint is out of range."""
    if not 0 <= steam <= STEAM_MAX:
        raise AnovaValidationError(f"Steam must be 0–{STEAM_MAX}%")


def normalize_stage(stage: AnovaPOStage) -> AnovaPOStage:
    """The stage made valid, changing as little as it can: the fan raised where the settings
    require it (to high, or from off to low above the proofing maximum, keeping the target),
    then the target, steam, timer and probe clamped into range."""
    steam = min(max(stage.steam, 0), STEAM_MAX)
    fans = allowed_fans(stage.sous_vide, stage.heating_elements, steam, stage.celsius)
    if stage.fan in fans:
        fan = stage.fan
    else:
        fan = AnovaPOFanSpeed.LOW if AnovaPOFanSpeed.LOW in fans else AnovaPOFanSpeed.HIGH
    low, high = temperature_range(stage.sous_vide, stage.heating_elements, steam, fan)
    celsius = min(max(stage.celsius, low), high)
    advance = stage.advance
    if isinstance(advance, AnovaPOTimer):
        advance = replace(advance, duration=min(max(advance.duration, 0), TIMER_MAX))
    elif isinstance(advance, AnovaPOProbe):
        target = from_celsius(min(max(to_celsius(advance.target, stage.temperature_unit), PROBE_MIN), PROBE_MAX), stage.temperature_unit)
        advance = replace(advance, target=target)
    temperature = stage.temperature if celsius == stage.celsius else from_celsius(celsius, stage.temperature_unit)
    return replace(stage, fan=fan, steam=steam, temperature=temperature, advance=advance)


def limits() -> dict[str, float | int]:
    """The constants, for the recipe editor."""
    return {
        "temperature_min": TEMPERATURE_MIN,
        "dry_max": DRY_MAX,
        "bottom_max": BOTTOM_MAX,
        "proofing_max": PROOFING_MAX,
        "wet_max": WET_MAX,
        "wet_steam_max": WET_STEAM_MAX,
        "probe_min": PROBE_MIN,
        "probe_max": PROBE_MAX,
        "steam_max": STEAM_MAX,
        "timer_max": TIMER_MAX,
    }

