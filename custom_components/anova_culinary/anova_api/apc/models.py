"""APC detailed data models for the Anova API."""

from dataclasses import dataclass, field
from enum import Enum

class APCTemperatureUnit(str, Enum):
    """Enumeration of temperature units."""
    C = "C"
    F = "F"

@dataclass
class TimerState:
    """State of the cooking timer."""
    running: bool = False
    initial: int = 0  # Initial timer value in seconds
    remaining: int = 0  # Remaining time in seconds

@dataclass
class APCState:
    """Current state of a Precision Cooker."""
    state: str = "idle"  # idle, preheating, cooking
    target_temperature: float = 0.0
    current_temperature: float = 0.0
    unit: APCTemperatureUnit = APCTemperatureUnit.C
    timer: TimerState = field(default_factory=TimerState)
    is_running: bool = False
