"""Select platform for Anova Precision Ovens: the running stage's elements, fan and timer start.

The options keep the labels they've always had, so dashboards and automations reading them
keep working.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaConfigEntry
from .anova_api import AnovaDevice, AnovaPODevice
from .anova_api.apo import AnovaPOFanSpeed, AnovaPOHeatingElement, AnovaPOTimer, AnovaPOTimerTrigger
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

    def __init__(self, device: AnovaPODevice, description: AnovaSelectEntityDescription) -> None:
        """Initialize the select."""
        super().__init__(device, description)
        self._attr_options = list(description.labels.values())

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
