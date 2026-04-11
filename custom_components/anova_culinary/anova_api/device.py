from dataclasses import dataclass
from typing import Any, Optional

from .product import AnovaProduct

@dataclass
class AnovaDevice:
    """Represents a discovered Anova device."""
    id: str
    product: AnovaProduct
    type: str  # e.g., 'oven_v1', 'oven_v2', 'a3', 'pro'
    name: str = ""
    state: Optional[Any] = None

    @property
    def model(self) -> str:
        """Dynamically compute the friendly hardware model."""
        mapping = {
            "oven": "Anova Precision Oven 1.0",
            "oven_v1": "Anova Precision Oven 1.0",
            "oven_v2": "Anova Precision Oven 2.0",
            "a3": "Anova Precision Cooker",
            "pro": "Anova Precision Cooker Pro"
        }
        return mapping.get(self.type.lower(), "Anova Precision Cooker" if self.product == AnovaProduct.APC else "Anova Precision Oven")
