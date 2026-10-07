"""Switch platform for Anova Precision Ovens."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaConfigEntry
from .anova_api import AnovaDevice, AnovaPODevice
from .entity import AnovaEntity, AnovaEntityDescription, async_setup_device_entities, is_cooking

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AnovaSwitchEntityDescription(AnovaEntityDescription, SwitchEntityDescription):
    """A switch: its state, and the oven call that sets it."""

    is_on_fn: Callable[[AnovaPODevice], bool]
    set_fn: Callable[[AnovaPODevice, bool], Awaitable[None]]


SWITCHES: tuple[AnovaSwitchEntityDescription, ...] = (
    AnovaSwitchEntityDescription(
        key="sous_vide",
        translation_key="sous_vide",
        available_fn=is_cooking,
        is_on_fn=lambda oven: oven.current_stage.sous_vide,
        set_fn=lambda oven, on: oven.set_sous_vide(on),
    ),
    AnovaSwitchEntityDescription(
        key="door_light",
        translation_key="door_light",
        is_on_fn=lambda oven: oven.lamp_on,
        set_fn=lambda oven, on: oven.set_lamp(on),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Anova switch platform."""

    def entities_for(device: AnovaDevice) -> list[SwitchEntity]:
        if not isinstance(device, AnovaPODevice):
            return []
        return [AnovaSwitch(device, description) for description in SWITCHES]

    async_setup_device_entities(hass, entry, async_add_entities, entities_for)


class AnovaSwitch(AnovaEntity[AnovaPODevice], SwitchEntity):
    """A switch on the oven."""

    entity_description: AnovaSwitchEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Whether it's on (unknown while it doesn't apply)."""
        return self.entity_description.is_on_fn(self.device) if self.available else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self._call(self.entity_description.set_fn(self.device, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self._call(self.entity_description.set_fn(self.device, False))
