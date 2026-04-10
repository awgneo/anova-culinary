"""Shared data models for the Anova API."""

from dataclasses import dataclass
from enum import Enum

class DeviceType(str, Enum):
    """Enumeration of supported device type categories."""
    APC = "APC"  # Precision Cooker
    APO = "APO"  # Precision Oven

@dataclass
class AnovaDevice:
    """Represents a discovered Anova device."""
    device_id: str
    type: DeviceType
    model: str  # e.g., 'oven_v1', 'oven_v2', 'a3', 'pro'
    name: str = "Unknown Device"
