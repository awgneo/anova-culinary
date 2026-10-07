"""Tests for two Anova accounts, one oven each: the recipes, actions and panel span both."""

from typing import Any
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.anova_culinary.anova_api import AnovaClient, AnovaProduct
from custom_components.anova_culinary.const import CONF_TOKEN, DOMAIN
from custom_components.anova_culinary.recipes import DATA_RECIPES
from conftest import oven_state

ACCOUNTS = {"refresh-left": ("left", "Kitchen Left Oven"), "refresh-right": ("right", "Kitchen Right Oven")}


async def test_two_accounts(hass, hass_ws_client) -> None:
    """Each account connects on its own; one recipe plays on both accounts' ovens."""
    sent: list[tuple[str, dict[str, Any]]] = []

    async def connect(self: AnovaClient) -> None:
        oven_id, name = ACCOUNTS[self._auth._refresh_token]
        self._process_discovery(AnovaProduct.APO, [{"cookerId": oven_id, "type": "oven_v2", "name": name}])
        self.devices[oven_id].update(oven_state(cooking=False))

    async def request(self: AnovaClient, message: dict[str, Any]) -> dict[str, Any]:
        sent.append((self._auth._refresh_token, message))
        return {"status": "ok"}

    entries = [
        MockConfigEntry(domain=DOMAIN, data={CONF_TOKEN: token}, unique_id=f"user-{token}", title=token)
        for token in ACCOUNTS
    ]
    with (
        patch.object(AnovaClient, "connect", connect),
        patch.object(AnovaClient, "request", request),
        patch.object(AnovaClient, "close", return_value=None),
        patch.object(AnovaClient, "connected", True),
        patch("custom_components.anova_culinary.panel.async_register_panel"),
    ):
        for entry in entries:
            entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get("climate.kitchen_left_oven") is not None
        assert hass.states.get("climate.kitchen_right_oven") is not None

        ws = await hass_ws_client(hass)
        await ws.send_json({"id": 1, "type": f"{DOMAIN}/ovens"})
        assert [oven["id"] for oven in (await ws.receive_json())["result"]] == ["left", "right"]

        await hass.services.async_call(
            DOMAIN, "save_recipe", {"name": "Toast", "stages": [{"temperature": 200}]}, blocking=True
        )
        (recipe_id,) = hass.data[DATA_RECIPES].data
        await hass.services.async_call(
            DOMAIN, "play_recipe", {"device_id": ["left", "right"], "recipe_id": recipe_id}, blocking=True
        )
    # Each oven's start went through its own account's connection
    assert [(account, message["payload"]["id"]) for account, message in sent] == [
        ("refresh-left", "left"),
        ("refresh-right", "right"),
    ]
