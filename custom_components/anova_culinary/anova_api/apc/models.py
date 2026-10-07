"""APC detailed data models for the Anova API."""

from enum import Enum


class AnovaPCTemperatureUnit(str, Enum):
    """Enumeration of temperature units."""

    C = "C"
    F = "F"
