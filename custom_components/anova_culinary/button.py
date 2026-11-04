"""Button platform for Anova Precision Ovens."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaConfigEntry
from .anova_api import AnovaDevice, AnovaPODevice
from .entity import AnovaEntity, AnovaEntityDescription, async_setup_device_entities

PARALLEL_UPDATES = 0

DESCALE = AnovaEntityDescription(
    key="descale",
    translation_key="descale",
    entity_category=EntityCategory.CONFIG,
    available_fn=lambda oven: not oven.is_cooking,
)
CONTINUE = AnovaEntityDescription(
    key="continue",
    translation_key="continue",
    available_fn=lambda oven: oven.can_continue,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Anova button platform."""

    def entities_for(device: AnovaDevice) -> list[ButtonEntity]:
        if not isinstance(device, AnovaPODevice):
            return []
        return [AnovaDescaleButton(device, DESCALE), AnovaContinueButton(device, CONTINUE)]

    async_setup_device_entities(hass, entry, async_add_entities, entities_for)


class AnovaDescaleButton(AnovaEntity[AnovaPODevice], ButtonEntity):
    """Starts descaling the steam boiler."""

    async def async_press(self) -> None:
        """Start descaling."""
        await self._call(self.device.start_descale())


class AnovaContinueButton(AnovaEntity[AnovaPODevice], ButtonEntity):
    """Does what the cook waits on: starts its timer, or its next stage (the app's buttons)."""

    async def async_press(self) -> None:
        """Continue the cook."""
        await self._call(self.device.continue_cook())
