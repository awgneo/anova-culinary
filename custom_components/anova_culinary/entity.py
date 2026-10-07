"""The base of every Anova entity: one device, its descriptions, and calls into anova_api."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaConfigEntry
from .anova_api import AnovaDevice
from .const import DOMAIN, MANUFACTURER
from .helpers import call_device


@dataclass(frozen=True, kw_only=True)
class AnovaEntityDescription(EntityDescription):
    """Description for all Anova entities; `key` is the unique id's suffix ('' for the device itself)."""

    available_fn: Callable[[Any], bool] = lambda _: True


def is_cooking(device: Any) -> bool:
    """Available while a cook runs: the controls of the running stage."""
    return device.is_cooking


class AnovaEntity[DeviceT: AnovaDevice](Entity):
    """Common elements for all entities: device info, updates and availability."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: AnovaEntityDescription

    def __init__(self, device: DeviceT, description: AnovaEntityDescription) -> None:
        """Initialize the entity."""
        self.device = device
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{device.id}" + (f"_{description.key}" if description.key else "")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=device.model,
            model_id=device.type,
            sw_version=device.state.system_info.firmware_version if device.state else None,
        )

    @property
    def available(self) -> bool:
        """Whether the device is reachable and this entity applies right now."""
        return self.device.available and self.entity_description.available_fn(self.device)

    async def async_added_to_hass(self) -> None:
        """Follow the device's updates."""
        self.async_on_remove(self.device.register_callback(self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        """Takes a device update."""
        self.async_write_ha_state()

    async def _call(self, action: Awaitable[Any]) -> None:
        """Runs a device action, raising its failure as a translated Home Assistant error."""
        await call_device(action)

def async_setup_device_entities(
    hass: HomeAssistant,
    entry: AnovaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    entities_for: Callable[[AnovaDevice], Iterable[Entity]],
) -> None:
    """Adds each device's entities now, and those of devices paired later."""
    client = entry.runtime_data
    async_add_entities(entity for device in client.devices.values() for entity in entities_for(device))

    @callback
    def device_changed(device: AnovaDevice, added: bool) -> None:
        if added:
            async_add_entities(entities_for(device))

    entry.async_on_unload(client.register_device_callback(device_changed))
