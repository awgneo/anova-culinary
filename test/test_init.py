"""Tests for setup: entities, unique ids, devices, sign-in failures and unloading."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.anova_culinary.anova_api import AnovaAuthError, AnovaClient, AnovaConnectionError, AnovaProduct
from custom_components.anova_culinary.const import DOMAIN

# The unique ids entities had before the rebuild: dashboards and automations rely on them
LEGACY_UNIQUE_IDS = {
    ("climate", "anova_culinary_oven-1"),
    ("climate", "anova_culinary_oven-1_probe"),
    ("switch", "anova_culinary_oven-1_sous_vide"),
    ("switch", "anova_culinary_oven-1_door_light"),
    ("switch", "anova_culinary_oven-1_steam_switch"),
    ("number", "anova_culinary_oven-1_steam"),
    ("number", "anova_culinary_oven-1_timer"),
    ("select", "anova_culinary_oven-1_heating_element"),
    ("select", "anova_culinary_oven-1_fan"),
    ("select", "anova_culinary_oven-1_timer_starts"),
    ("sensor", "anova_culinary_oven-1_timer"),
    ("sensor", "anova_culinary_oven-1_timer_elapsed"),
    ("sensor", "anova_culinary_oven-1_recipe"),
    ("binary_sensor", "anova_culinary_oven-1_door_status"),
    ("binary_sensor", "anova_culinary_oven-1_cavity_light"),
    ("binary_sensor", "anova_culinary_oven-1_camera"),
    ("water_heater", "anova_culinary_cooker-1"),
    ("sensor", "anova_culinary_cooker-1_timer"),
}


async def test_unique_ids_are_kept(hass, sent) -> None:
    """Every entity the integration had keeps its unique id."""
    registry = er.async_get(hass)
    ids = {(entry.domain, entry.unique_id) for entry in registry.entities.values()}
    assert LEGACY_UNIQUE_IDS <= ids


async def test_devices(hass, sent) -> None:
    """Each device has a registry entry with its model and firmware."""
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "oven-1")})
    assert (device.name, device.model, device.manufacturer) == ("Test Oven", "Anova Precision Oven 2.0", "Anova")
    assert device.sw_version == "11_225_1.4.2_01.01.26"


async def test_devices_paired_later(hass, client) -> None:
    """A device paired after setup gets entities; one unpaired is removed."""
    client._process_discovery(
        AnovaProduct.APO,
        [
            {"cookerId": "oven-1", "type": "oven_v2"},
            {"cookerId": "oven-2", "type": "oven_v2"},
            {"cookerId": "oven-3", "type": "oven_v2", "name": "New Oven"},
        ],
    )
    await hass.async_block_till_done()
    assert hass.states.get("climate.new_oven") is not None
    client._process_discovery(AnovaProduct.APO, [{"cookerId": "oven-1", "type": "oven_v2"}])
    await hass.async_block_till_done()
    assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "oven-3")}) is None


async def test_unload(hass, mock_config_entry, sent) -> None:
    """Unloading closes the connection."""
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_sign_in_rejected(hass, mock_config_entry) -> None:
    """A rejected sign-in asks to sign in again."""
    mock_config_entry.add_to_hass(hass)
    with patch.object(AnovaClient, "connect", side_effect=AnovaAuthError("revoked")):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_cannot_connect(hass, mock_config_entry) -> None:
    """An unreachable Anova retries setup later."""
    mock_config_entry.add_to_hass(hass)
    with patch.object(AnovaClient, "connect", side_effect=AnovaConnectionError("down")):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
