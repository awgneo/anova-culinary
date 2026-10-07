"""Number platform for Anova Precision Ovens."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaConfigEntry
from .anova_api import AnovaDevice, AnovaPODevice
from .anova_api.apo import AnovaPOTimer, limits
from .entity import AnovaEntity, AnovaEntityDescription, async_setup_device_entities, is_cooking

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AnovaNumberEntityDescription(AnovaEntityDescription, NumberEntityDescription):
    """A number: its value, and the oven call that sets it."""

    value_fn: Callable[[AnovaPODevice], float]
    set_fn: Callable[[AnovaPODevice, float], Awaitable[None]]


def _timer_minutes(oven: AnovaPODevice) -> float:
    """The running stage's timer, in minutes (0 without one)."""
    advance = oven.current_stage.advance
    return int(advance.duration / 60) if isinstance(advance, AnovaPOTimer) else 0


NUMBERS: tuple[AnovaNumberEntityDescription, ...] = (
    AnovaNumberEntityDescription(
        key="steam",
        translation_key="steam",
        native_min_value=0,
        native_max_value=limits.STEAM_MAX,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        available_fn=is_cooking,
        value_fn=lambda oven: oven.current_stage.steam,
        set_fn=lambda oven, value: oven.set_steam(int(value)),
    ),
    AnovaNumberEntityDescription(
        key="timer",
        translation_key="timer",
        native_min_value=0,
        native_max_value=limits.TIMER_MAX // 60,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        available_fn=is_cooking,
        value_fn=_timer_minutes,
        set_fn=lambda oven, value: oven.set_timer(int(value * 60)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Anova number platform."""

    def entities_for(device: AnovaDevice) -> list[NumberEntity]:
        if not isinstance(device, AnovaPODevice):
            return []
        return [AnovaNumber(device, description) for description in NUMBERS]

    async_setup_device_entities(hass, entry, async_add_entities, entities_for)


class AnovaNumber(AnovaEntity[AnovaPODevice], NumberEntity):
    """A number on the oven's running stage."""

    entity_description: AnovaNumberEntityDescription

    @property
    def native_value(self) -> float | None:
        """The value (unknown while it doesn't apply)."""
        return self.entity_description.value_fn(self.device) if self.available else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        await self._call(self.entity_description.set_fn(self.device, value))
