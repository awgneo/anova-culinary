"""The Anova API integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .anova_api import AnovaAuthError, AnovaClient, AnovaConnectionError, AnovaDevice
from .const import CONF_TOKEN, DOMAIN
from .panel import async_setup_panel
from .recipes import async_setup_recipes
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type AnovaConfigEntry = ConfigEntry[AnovaClient]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up what every account shares: the recipe collection, actions and the panel."""
    await async_setup_recipes(hass)
    async_setup_services(hass)
    await async_setup_panel(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AnovaConfigEntry) -> bool:
    """Set up Anova API from a config entry."""
    client = AnovaClient(entry.data[CONF_TOKEN], async_get_clientsession(hass))
    try:
        await client.connect()
    except AnovaAuthError as err:
        raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="auth_failed") from err
    except AnovaConnectionError as err:
        raise ConfigEntryNotReady(translation_domain=DOMAIN, translation_key="cannot_connect") from err

    # Entries made before the account's id became their unique id
    if entry.unique_id is None and client.user_id:
        hass.config_entries.async_update_entry(entry, unique_id=client.user_id)

    entry.runtime_data = client
    entry.async_on_unload(client.register_auth_error_callback(lambda _: entry.async_start_reauth(hass)))
    entry.async_on_unload(client.register_device_callback(_device_removed(hass, entry)))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AnovaConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.close()
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: AnovaConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a device that's no longer paired to the account."""
    return not any(identifier[1] in entry.runtime_data.devices for identifier in device.identifiers if identifier[0] == DOMAIN)


def _device_removed(hass: HomeAssistant, entry: AnovaConfigEntry):
    """Removes a device from Home Assistant when it's unpaired from the account."""

    @callback
    def device_changed(device: AnovaDevice, added: bool) -> None:
        if added:
            return
        registry = dr.async_get(hass)
        if entry_device := registry.async_get_device(identifiers={(DOMAIN, device.id)}):
            registry.async_update_device(entry_device.id, remove_config_entry_id=entry.entry_id)

    return device_changed
