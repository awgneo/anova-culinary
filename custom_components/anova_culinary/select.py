"""Select platform for Anova Precision Ovens: the running stage's elements, fan and timer start."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaConfigEntry
from .anova_api import AnovaDevice, AnovaPODevice
from .anova_api.apo import AnovaPOFanSpeed, AnovaPOHeatingElement, AnovaPOTimer, AnovaPOTimerTrigger, limits
from .entity import AnovaEntity, AnovaEntityDescription, async_setup_device_entities, is_cooking

PARALLEL_UPDATES = 0

HEATING_ELEMENTS = {
    AnovaPOHeatingElement.TOP: "Top",
    AnovaPOHeatingElement.REAR: "Rear",
    AnovaPOHeatingElement.BOTTOM: "Bottom",
    AnovaPOHeatingElement.TOP_REAR: "Top + Rear",
    AnovaPOHeatingElement.BOTTOM_REAR: "Bottom + Rear",
    AnovaPOHeatingElement.TOP_BOTTOM: "Top + Bottom",
}
FANS = {
    AnovaPOFanSpeed.OFF: "Off",
    AnovaPOFanSpeed.LOW: "Low",
    AnovaPOFanSpeed.MEDIUM: "Medium",
    AnovaPOFanSpeed.HIGH: "High",
}
TIMER_STARTS = {
    AnovaPOTimerTrigger.IMMEDIATELY: "Immediately",
    AnovaPOTimerTrigger.PREHEATED: "When Preheated",
    AnovaPOTimerTrigger.FOOD_DETECTED: "Food Detected",
    AnovaPOTimerTrigger.MANUALLY: "Manually",
}


@dataclass(frozen=True, kw_only=True)
class AnovaSelectEntityDescription(AnovaEntityDescription, SelectEntityDescription):
    """A select: its labelled values, the current one, and the oven call that sets it."""

    labels: dict[Enum, str]
    value_fn: Callable[[AnovaPODevice], Enum]
    set_fn: Callable[[AnovaPODevice, Enum], Awaitable[None]]
    # The values the running stage allows right now (all of them by default)
    allowed_fn: Callable[[AnovaPODevice], list[Enum]] | None = None


def _timer_start(oven: AnovaPODevice) -> AnovaPOTimerTrigger:
    """When the running stage's timer starts (manually without one, as the editor defaults)."""
    advance = oven.current_stage.advance
    return advance.trigger if isinstance(advance, AnovaPOTimer) else AnovaPOTimerTrigger.MANUALLY


SELECTS: tuple[AnovaSelectEntityDescription, ...] = (
    AnovaSelectEntityDescription(
        key="heating_element",
        translation_key="heating_element",
        labels=HEATING_ELEMENTS,
        available_fn=is_cooking,
        value_fn=lambda oven: oven.current_stage.heating_elements,
        set_fn=lambda oven, value: oven.set_heating_elements(value),
    ),
    AnovaSelectEntityDescription(
        key="fan",
        translation_key="fan",
        labels=FANS,
        available_fn=is_cooking,
        allowed_fn=lambda oven: limits.stage_fans(oven.current_stage),
        value_fn=lambda oven: oven.current_stage.fan,
        set_fn=lambda oven, value: oven.set_fan(value),
    ),
    AnovaSelectEntityDescription(
        key="timer_starts",
        translation_key="timer_starts",
        labels=TIMER_STARTS,
        available_fn=is_cooking,
        value_fn=_timer_start,
        set_fn=lambda oven, value: oven.set_timer_trigger(value),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Anova select platform."""

    def entities_for(device: AnovaDevice) -> list[SelectEntity]:
        if not isinstance(device, AnovaPODevice):
            return []
        return [AnovaSelect(device, description) for description in SELECTS]

    async_setup_device_entities(hass, entry, async_add_entities, entities_for)


class AnovaSelect(AnovaEntity[AnovaPODevice], SelectEntity):
    """A setting of the oven's running stage."""

    entity_description: AnovaSelectEntityDescription

    @property
    def options(self) -> list[str]:
        """The labels of the values the running stage allows (and the current one)."""
        description = self.entity_description
        if description.allowed_fn is None or not self.available:
            return list(description.labels.values())
        allowed = set(description.allowed_fn(self.device)) | {description.value_fn(self.device)}
        return [label for value, label in description.labels.items() if value in allowed]

    @property
    def current_option(self) -> str | None:
        """The current label (unknown while it doesn't apply)."""
        if not self.available:
            return None
        return self.entity_description.labels[self.entity_description.value_fn(self.device)]

    async def async_select_option(self, option: str) -> None:
        """Set the value with this label."""
        value = next(value for value, label in self.entity_description.labels.items() if label == option)
        await self._call(self.entity_description.set_fn(self.device, value))
