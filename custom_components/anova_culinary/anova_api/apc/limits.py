"""The limits the Anova app enforces on a third-generation Precision Cooker (PROTOCOL.md,
part 3, §5.1)."""

from ..exceptions import AnovaValidationError
from .models import AnovaPCTemperatureUnit

TEMPERATURE_RANGE = {
    AnovaPCTemperatureUnit.C: (0.0, 99.5),
    AnovaPCTemperatureUnit.F: (32.0, 211.5),
}
TIMER_MAX = 359940  # 99 h 59 min


def validate_temperature(value: float, unit: AnovaPCTemperatureUnit) -> None:
    """Raises if a target is out of range in its unit."""
    low, high = TEMPERATURE_RANGE[unit]
    if not low <= value <= high:
        raise AnovaValidationError(f"{value:g} °{unit.value} is outside {low:g}–{high:g} °{unit.value}")


def validate_timer(seconds: int) -> None:
    """Raises if a timer is out of range."""
    if not 0 <= seconds <= TIMER_MAX:
        raise AnovaValidationError("The timer must be 0 to 99 h 59 min")
