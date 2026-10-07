"""Test configuration: the integration set up against a fake Anova account."""

import copy
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.anova_culinary.anova_api import AnovaClient, AnovaProduct
from custom_components.anova_culinary.const import CONF_TOKEN, DOMAIN
from fakes import fixture
from test_apc import COOKER_STATE

OVEN_ID = "oven-1"
IDLE_OVEN_ID = "oven-2"
COOKER_ID = "cooker-1"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mocked Config Entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="me@example.com",
        data={CONF_TOKEN: "mock-refresh-token"},
        unique_id="user-1",
        entry_id="test_anova_entry_id",
    )


def oven_state(cooking: bool = True) -> dict[str, Any]:
    """The app's sous vide cook, or the same oven idle."""
    state = copy.deepcopy(fixture("apo_state.json")["payload"]["state"])
    if not cooking:
        state["state"]["mode"] = "idle"
        del state["cook"]
    return state


class Sent:
    """The commands sent while the integration runs."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    @property
    def commands(self) -> list[tuple[str, Any]]:
        """(command, payload) for each, the oven's inner payload unwrapped."""
        return [
            (m["command"], m["payload"].get("payload", m["payload"]) if "id" in m["payload"] else m["payload"])
            for m in self.messages
        ]


@pytest.fixture
async def sent(hass, mock_config_entry) -> Sent:
    """Sets the integration up with two ovens (one cooking) and a cooker; returns what it sends."""
    sent = Sent()
    mock_config_entry.add_to_hass(hass)

    async def connect(self: AnovaClient) -> None:
        self._process_discovery(
            AnovaProduct.APO,
            [
                {"cookerId": OVEN_ID, "type": "oven_v2", "name": "Test Oven"},
                {"cookerId": IDLE_OVEN_ID, "type": "oven_v2", "name": "Idle Oven"},
            ],
        )
        self._process_discovery(AnovaProduct.APC, [{"cookerId": COOKER_ID, "type": "a7", "name": "Test Cooker"}])
        self.devices[OVEN_ID].update(oven_state())
        self.devices[IDLE_OVEN_ID].update(oven_state(cooking=False))
        self.devices[COOKER_ID].update(COOKER_STATE)

    async def request(self: AnovaClient, message: dict[str, Any]) -> dict[str, Any]:
        sent.messages.append(message)
        return {"status": "ok"}

    with (
        patch.object(AnovaClient, "connect", connect),
        patch.object(AnovaClient, "request", request),
        patch.object(AnovaClient, "close", return_value=None),
        patch.object(AnovaClient, "connected", True),
        patch("custom_components.anova_culinary.panel.async_register_panel") as register_panel,
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert register_panel.called
        yield sent


@pytest.fixture
def client(hass, mock_config_entry, sent) -> AnovaClient:
    """The set-up integration's client."""
    return mock_config_entry.runtime_data
