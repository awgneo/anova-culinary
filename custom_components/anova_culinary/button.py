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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Anova button platform."""

    def entities_for(device: AnovaDevice) -> list[ButtonEntity]:
        return [AnovaDescaleButton(device, DESCALE)] if isinstance(device, AnovaPODevice) else []

    async_setup_device_entities(hass, entry, async_add_entities, entities_for)


class AnovaDescaleButton(AnovaEntity[AnovaPODevice], ButtonEntity):
    """Starts descaling the steam boiler."""

    async def async_press(self) -> None:
        """Start descaling."""
        await self._call(self.device.start_descale())
