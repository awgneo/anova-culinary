"""Sensor platform for Anova API integration."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import AnovaConfigEntry
from .anova_api import AnovaDevice, AnovaPCDevice, AnovaPODevice
from .anova_api.models import parse_timestamp
from .entity import AnovaEntity, AnovaEntityDescription, async_setup_device_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AnovaSensorEntityDescription(AnovaEntityDescription, SensorEntityDescription):
    """A sensor: its value from the device."""

    value_fn: Callable[[AnovaDevice], StateType]


def _elapsed(device: AnovaDevice) -> int:
    """Seconds since the cook started (0 while idle)."""
    cook = device.state.cook if device.is_cooking else None
    if cook is None or not cook.started_timestamp:
        return 0
    return max(0, int((datetime.now(UTC) - parse_timestamp(cook.started_timestamp)).total_seconds()))


def _recipe(oven: AnovaPODevice) -> str:
    """The running recipe's title ('Manual Cook' without one, 'None' while idle)."""
    if (recipe := oven.recipe) is None:
        return "None"
    return recipe.title or "Manual Cook"


def _rack(oven: AnovaPODevice) -> int | None:
    """The running stage's rack."""
    stage = oven.current_stage
    return stage.rack if stage else None


TIMER_REMAINING = AnovaSensorEntityDescription(
    key="timer",
    translation_key="timer_remaining",
    device_class=SensorDeviceClass.DURATION,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=UnitOfTime.SECONDS,
    value_fn=lambda device: device.timer_remaining,
)
TIMER_ELAPSED = AnovaSensorEntityDescription(
    key="timer_elapsed",
    translation_key="timer_elapsed",
    device_class=SensorDeviceClass.DURATION,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=UnitOfTime.SECONDS,
    value_fn=_elapsed,
)


def _diagnostic(key: str, unit: str, device_class: SensorDeviceClass, value_fn: Callable) -> AnovaSensorEntityDescription:
    """A hardware reading, disabled by default."""
    return AnovaSensorEntityDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=SensorStateClass.MEASUREMENT if device_class == SensorDeviceClass.POWER else SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda oven: value_fn(oven.state.nodes) if oven.state else None,
    )


OVEN_SENSORS: tuple[AnovaSensorEntityDescription, ...] = (
    TIMER_REMAINING,
    TIMER_ELAPSED,
    AnovaSensorEntityDescription(key="recipe", translation_key="recipe", value_fn=_recipe),
    AnovaSensorEntityDescription(key="rack_position", translation_key="rack_position", value_fn=_rack),
    *(
        _diagnostic(f"{name}_heater_power", UnitOfPower.WATT, SensorDeviceClass.POWER, lambda n, name=name: getattr(n.heating_elements, name).watts)
        for name in ("top", "bottom", "rear")
    ),
    *(
        _diagnostic(f"{name}_heater_usage", UnitOfTime.HOURS, SensorDeviceClass.DURATION, lambda n, name=name: getattr(n.heating_elements, name).usage_hours)
        for name in ("top", "bottom", "rear")
    ),
    _diagnostic("boiler_power", UnitOfPower.WATT, SensorDeviceClass.POWER, lambda n: n.steam_generators.boiler.watts),
    _diagnostic("boiler_usage", UnitOfTime.HOURS, SensorDeviceClass.DURATION, lambda n: n.steam_generators.boiler.usage_hours),
    _diagnostic("evaporator_power", UnitOfPower.WATT, SensorDeviceClass.POWER, lambda n: n.steam_generators.evaporator.watts),
    _diagnostic("evaporator_usage", UnitOfTime.HOURS, SensorDeviceClass.DURATION, lambda n: n.steam_generators.evaporator.usage_hours),
)
COOKER_SENSORS: tuple[AnovaSensorEntityDescription, ...] = (TIMER_REMAINING, TIMER_ELAPSED)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Anova sensor platform."""

    def entities_for(device: AnovaDevice) -> list[SensorEntity]:
        if isinstance(device, AnovaPODevice):
            descriptions = OVEN_SENSORS
        elif isinstance(device, AnovaPCDevice):
            descriptions = COOKER_SENSORS
        else:
            return []
        return [AnovaSensor(device, description) for description in descriptions]

    async_setup_device_entities(hass, entry, async_add_entities, entities_for)


class AnovaSensor(AnovaEntity[AnovaDevice], SensorEntity):
    """A reading from a device."""

    entity_description: AnovaSensorEntityDescription

    @property
    def native_value(self) -> StateType:
        """The reading."""
        return self.entity_description.value_fn(self.device) if self.device.state else None
