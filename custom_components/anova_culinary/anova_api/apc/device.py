"""A third-generation Precision Cooker (a6 Nano 3.0, a7 3.0, a8 Mini, a9 Pro 3.0)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from ..device import AnovaDevice
from ..exceptions import AnovaValidationError
from ..product import AnovaProduct
from . import commands, limits
from .models import AnovaPCTemperatureUnit
from .state import AnovaPCState


class AnovaPCDevice(AnovaDevice[AnovaPCState]):
    """An Anova Precision Cooker of the current generation."""

    product: ClassVar[AnovaProduct] = AnovaProduct.APC
    state_class = AnovaPCState
    models: ClassVar[dict[str, str]] = {
        "a6": "Anova Precision Cooker Nano 3.0",
        "a7": "Anova Precision Cooker 3.0",
        "a8": "Anova Precision Cooker Mini",
        "a9": "Anova Precision Cooker Pro 3.0",
    }

    @property
    def is_cooking(self) -> bool:
        """Whether a cook is running."""
        return self.state is not None and self.state.is_cooking

    @property
    def unit(self) -> AnovaPCTemperatureUnit:
        """The cooker's display unit."""
        return AnovaPCTemperatureUnit(self.state.status.temperature_unit) if self.state else AnovaPCTemperatureUnit.C

    @property
    def temperature(self) -> float | None:
        """The water temperature (Celsius)."""
        return self.state.nodes.water_temperature_sensor.current.celsius if self.state else None

    @property
    def target_temperature(self) -> float | None:
        """The target (Celsius)."""
        return self.state.nodes.water_temperature_sensor.setpoint.celsius if self.state else None

    @property
    def timer_remaining(self) -> int | None:
        """Seconds left on the timer."""
        return self.state.nodes.timer.remaining(datetime.now(UTC)) if self.state else None

    async def start(self, target: float, unit: AnovaPCTemperatureUnit, timer: int = 0) -> None:
        """Starts a cook at `target` in `unit`; `timer` in seconds, 0 for none."""
        limits.validate_temperature(target, unit)
        limits.validate_timer(timer)
        await self._request(commands.build_start_command(self.id, self.type, target, unit.value, timer))

    async def stop(self) -> None:
        """Stops the cook."""
        await self._request(commands.build_stop_command(self.id, self.type))

    async def set_target_temperature(self, target: float, unit: AnovaPCTemperatureUnit) -> None:
        """Changes the running cook's target."""
        if not self.is_cooking:
            raise AnovaValidationError("No cook is running")
        limits.validate_temperature(target, unit)
        await self._request(commands.build_set_target_temperature_command(self.id, self.type, target, unit.value))

    async def set_timer(self, seconds: int) -> None:
        """Changes or adds the running cook's timer."""
        if not self.is_cooking:
            raise AnovaValidationError("No cook is running")
        limits.validate_timer(seconds)
        await self._request(commands.build_set_timer_command(self.id, self.type, seconds))
