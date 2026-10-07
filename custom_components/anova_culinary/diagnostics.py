"""Diagnostics for the Anova integration: each device's latest state, without secrets."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import AnovaConfigEntry
from .const import CONF_TOKEN

TO_REDACT = {CONF_TOKEN, "deviceId", "cookerId", "id", "cookId", "cookableId", "processedCommandIds"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: AnovaConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    client = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "connected": client.connected,
        "devices": [
            {
                "type": device.type,
                "model": device.model,
                "available": device.available,
                "state": async_redact_data(device.state.to_dict(), TO_REDACT) if device.state else None,
            }
            for device in client.devices.values()
        ],
    }
