"""Water heater platform for Anova Precision Cookers."""

from typing import Any

from homeassistant.components.water_heater import (
    STATE_ECO,
    STATE_ELECTRIC,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaConfigEntry
from .anova_api import AnovaDevice, AnovaPCDevice, AnovaPCTemperatureUnit
from .anova_api.apc.limits import TEMPERATURE_RANGE
from .entity import AnovaEntity, AnovaEntityDescription, async_setup_device_entities

PARALLEL_UPDATES = 0

# The target to start at before one is set
DEFAULT_TARGET = 60.0

COOKER = AnovaEntityDescription(key="", name=None, translation_key="cooker")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Anova water heater platform."""

    def entities_for(device: AnovaDevice) -> list[WaterHeaterEntity]:
        return [AnovaCooker(device, COOKER)] if isinstance(device, AnovaPCDevice) else []

    async_setup_device_entities(hass, entry, async_add_entities, entities_for)


class AnovaCooker(AnovaEntity[AnovaPCDevice], WaterHeaterEntity):
    """Representation of an Anova Precision Cooker: electric while cooking, eco while idle."""

    _attr_supported_features = WaterHeaterEntityFeature.TARGET_TEMPERATURE | WaterHeaterEntityFeature.OPERATION_MODE
    _attr_operation_list = [STATE_ELECTRIC, STATE_ECO]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp, _attr_max_temp = TEMPERATURE_RANGE[AnovaPCTemperatureUnit.C]

    @property
    def current_temperature(self) -> float | None:
        """The water temperature."""
        return self.device.temperature

    @property
    def target_temperature(self) -> float | None:
        """The target."""
        return self.device.target_temperature

    @property
    def current_operation(self) -> str:
        """Electric while cooking."""
        return STATE_ELECTRIC if self.device.is_cooking else STATE_ECO

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Change the running cook's target, or start a cook at it."""
        temperature = kwargs[ATTR_TEMPERATURE]
        if self.device.is_cooking:
            await self._call(self.device.set_target_temperature(temperature, AnovaPCTemperatureUnit.C))
        else:
            await self._call(self.device.start(temperature, AnovaPCTemperatureUnit.C))

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Start (electric) or stop (eco)."""
        if operation_mode == STATE_ECO:
            await self._call(self.device.stop())
        elif not self.device.is_cooking:
            await self._call(self.device.start(self.device.target_temperature or DEFAULT_TARGET, AnovaPCTemperatureUnit.C))
