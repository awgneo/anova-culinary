"""The recipe format: oven stages as the recipe editor and Home Assistant see them.

recipe.py converts these to and from the oven's own stages (StageV2) exactly as the Anova
Oven app does; stored recipes are this format, so their JSON never changes shape.
"""

from dataclasses import dataclass, field
from enum import Enum

from mashumaro import field_options
from mashumaro.mixins.dict import DataClassDictMixin


class AnovaPOHeatingElement(str, Enum):
    """Enumeration of valid heating element combinations."""

    TOP = "top"
    REAR = "rear"
    BOTTOM = "bottom"
    TOP_REAR = "top+rear"
    BOTTOM_REAR = "bottom+rear"
    TOP_BOTTOM = "top+bottom"

    @property
    def top(self) -> bool:
        """Whether the top element is on."""
        return "top" in self.value

    @property
    def bottom(self) -> bool:
        """Whether the bottom element is on."""
        return "bottom" in self.value

    @property
    def rear(self) -> bool:
        """Whether the rear element is on."""
        return "rear" in self.value

    @classmethod
    def of(cls, top: bool, bottom: bool, rear: bool) -> "AnovaPOHeatingElement":
        """The combination with these elements on (rear when none, or all three, are)."""
        value = "+".join(name for name, on in (("top", top), ("bottom", bottom), ("rear", rear)) if on)
        try:
            return cls(value)
        except ValueError:
            return cls.REAR


class AnovaPOFanSpeed(str, Enum):
    """Enumeration of valid fan speeds."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    OFF = "off"

    @property
    def speed(self) -> int:
        """The speed stages and SET_FAN carry (the app's 0, 33, 67 and 100)."""
        return {"off": 0, "low": 33, "medium": 67, "high": 100}[self.value]

    @classmethod
    def of(cls, speed: int) -> "AnovaPOFanSpeed":
        """The setting nearest a stage's numeric speed."""
        if speed <= 0:
            return cls.OFF
        if speed <= 33:
            return cls.LOW
        if speed <= 67:
            return cls.MEDIUM
        return cls.HIGH


class AnovaPOTimerTrigger(str, Enum):
    """Enumeration of valid timer starts."""

    FOOD_DETECTED = "food_detected"
    IMMEDIATELY = "immediately"
    PREHEATED = "preheated"
    MANUALLY = "manually"


class AnovaPOTransition(str, Enum):
    """How a stage (the second onward) begins once the stage before it ends."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"
    FOOD_REMOVED = "food_removed"


@dataclass
class AnovaPOProbe:
    """Universal schema for a stage's probe transition constraint."""

    target: float


@dataclass
class AnovaPOTimer:
    """Universal schema for a stage's timer transition constraint."""

    duration: int
    trigger: AnovaPOTimerTrigger


@dataclass
class AnovaPOStage(DataClassDictMixin):
    """Universal schema representing a single state of cooking intent.

    `temperature` and a probe `advance.target` are in `temperature_unit`.
    """

    id: str = ""
    sous_vide: bool = False
    temperature: float = 0.0
    temperature_unit: str = "C"
    steam: int = 0
    heating_elements: AnovaPOHeatingElement = AnovaPOHeatingElement.REAR
    fan: AnovaPOFanSpeed = AnovaPOFanSpeed.HIGH
    advance: AnovaPOTimer | AnovaPOProbe | None = None
    transition: AnovaPOTransition = AnovaPOTransition.AUTOMATIC
    rack: int | None = None

    @property
    def mode(self) -> str:
        """The temperature bulb the oven regulates: wet for sous vide, else dry."""
        return "wet" if self.sous_vide else "dry"

    @property
    def celsius(self) -> float:
        """The target in Celsius."""
        return to_celsius(self.temperature, self.temperature_unit)


@dataclass
class AnovaPORecipe(DataClassDictMixin):
    """Static storage entity representing an array of intended stages."""

    id: str = ""
    title: str = field(default="", metadata=field_options(alias="name"))
    stages: list[AnovaPOStage] = field(default_factory=list)

    class Config:
        serialize_by_alias = True


def to_celsius(value: float, unit: str) -> float:
    """A temperature in `unit` (C or F) as Celsius, to the app's two decimals."""
    return round((value - 32) * 5 / 9, 2) if unit == "F" else value


def from_celsius(celsius: float, unit: str) -> float:
    """Celsius in `unit` (C or F), to a tenth of a degree."""
    return round(celsius * 9 / 5 + 32, 1) if unit == "F" else celsius
