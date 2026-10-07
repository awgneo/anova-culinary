"""Finding devices across every loaded Anova account."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from collections.abc import Awaitable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .anova_api import AnovaDevice, AnovaException, AnovaPODevice, AnovaValidationError
from .const import DOMAIN

if TYPE_CHECKING:
    from . import AnovaConfigEntry


def loaded_devices(hass: HomeAssistant) -> Iterator[AnovaDevice]:
    """Every device of every loaded account."""
    entry: AnovaConfigEntry
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        yield from entry.runtime_data.devices.values()


def loaded_ovens(hass: HomeAssistant) -> list[AnovaPODevice]:
    """Every oven of every loaded account, by name."""
    return sorted((d for d in loaded_devices(hass) if isinstance(d, AnovaPODevice)), key=lambda oven: oven.name)


async def call_device(action: Awaitable[Any]) -> None:
    """Runs a device action, raising its failure as a translated Home Assistant error."""
    try:
        await action
    except AnovaValidationError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_setting", translation_placeholders={"error": str(err)}
        ) from err
    except AnovaException as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="command_failed", translation_placeholders={"error": str(err)}
        ) from err
