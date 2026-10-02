from enum import Enum

class AnovaProduct(str, Enum):
    """Enumeration of supported device type categories."""
    APC = "APC"  # Precision Cooker
    APO = "APO"  # Precision Oven