"""Binary Sensor platform for physical Anova states."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaConfigEntry
from .anova_api import AnovaDevice, AnovaPCDevice, AnovaPODevice
from .entity import AnovaEntity, AnovaEntityDescription, async_setup_device_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AnovaBinarySensorEntityDescription(AnovaEntityDescription, BinarySensorEntityDescription):
    """A binary sensor: its value from the device's state."""

    is_on_fn: Callable[..., bool]


def _problem(key: str, is_on_fn: Callable[..., bool], device_class=BinarySensorDeviceClass.PROBLEM) -> AnovaBinarySensorEntityDescription:
    """A condition that needs attention."""
    return AnovaBinarySensorEntityDescription(key=key, translation_key=key, device_class=device_class, is_on_fn=is_on_fn)


OVEN_BINARY_SENSORS: tuple[AnovaBinarySensorEntityDescription, ...] = (
    # For Home Assistant Door class: False = Closed, True = Open
    AnovaBinarySensorEntityDescription(
        key="door_status",
        translation_key="door_status",
        device_class=BinarySensorDeviceClass.DOOR,
        is_on_fn=lambda state: not state.nodes.door.closed,
    ),
    AnovaBinarySensorEntityDescription(
        key="cavity_light",
        translation_key="cavity_light",
        device_class=BinarySensorDeviceClass.LIGHT,
        is_on_fn=lambda state: state.nodes.cavity_lamp.on,
    ),
    # Occupancy class: True means occupied (food detected), False means clear (empty)
    AnovaBinarySensorEntityDescription(
        key="camera",
        translation_key="camera_status",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        is_on_fn=lambda state: not state.nodes.cavity_camera.is_empty,
    ),
    _problem("water_tank_empty", lambda state: state.nodes.water_tank.empty),
    _problem("water_tank_low", lambda state: state.nodes.water_tank.low),
    _problem("water_tank_removed", lambda state: state.nodes.water_tank.removed),
    _problem("waste_water_tank_full", lambda state: state.nodes.waste_water_tank.full),
    _problem("waste_water_tank_removed", lambda state: state.nodes.waste_water_tank.removed),
    _problem("descale_required", lambda state: state.nodes.steam_generators.boiler.descale_required),
)
COOKER_BINARY_SENSORS: tuple[AnovaBinarySensorEntityDescription, ...] = (
    _problem("low_water", lambda state: state.is_low_water),
    _problem("water_leak", lambda state: state.status.mode == "waterLeak", BinarySensorDeviceClass.MOISTURE),
    _problem("high_temperature", lambda state: state.status.mode == "highTemp", BinarySensorDeviceClass.HEAT),
    _problem("motor_stuck", lambda state: state.status.mode == "motorStuck"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""

    def entities_for(device: AnovaDevice) -> list[BinarySensorEntity]:
        if isinstance(device, AnovaPODevice):
            descriptions = OVEN_BINARY_SENSORS
        elif isinstance(device, AnovaPCDevice):
            descriptions = COOKER_BINARY_SENSORS
        else:
            return []
        return [AnovaBinarySensor(device, description) for description in descriptions]

    async_setup_device_entities(hass, entry, async_add_entities, entities_for)


class AnovaBinarySensor(AnovaEntity[AnovaDevice], BinarySensorEntity):
    """A condition reported by a device."""

    entity_description: AnovaBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Whether the condition holds."""
        return self.entity_description.is_on_fn(self.device.state) if self.device.state else None
