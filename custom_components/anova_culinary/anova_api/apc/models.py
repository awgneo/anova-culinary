"""APC detailed data models for the Anova API."""

from dataclasses import dataclass, field
from enum import Enum

class AnovaPCTemperatureUnit(str, Enum):
    """Enumeration of temperature units."""
    C = "C"
    F = "F"

@dataclass
class AnovaPCTimerState:
    """State of the cooking timer."""
    running: bool = False
    initial: int = 0  # Initial timer value in seconds
    remaining: int = 0  # Remaining time in seconds

@dataclass
class AnovaPCState:
    """Current state of a Precision Cooker."""
    state: str = "idle"  # idle, preheating, cooking
    target_temperature: float = 0.0
    current_temperature: float = 0.0
    unit: AnovaPCTemperatureUnit = AnovaPCTemperatureUnit.C
    timer: AnovaPCTimerState = field(default_factory=AnovaPCTimerState)
    is_running: bool = False

@dataclass
class AnovaPCCook:
    """Represents an intended APC cook session."""
    target_temperature: float
    temperature_unit: AnovaPCTemperatureUnit
    timer: int = 3600
