"""Test configuration and mocks for Anova API."""

import pytest
from unittest.mock import AsyncMock, patch

@pytest.fixture
def mock_ws_response():
    """Mock aiohttp websocket response."""
    mock_ws = AsyncMock()
    mock_ws.send_str = AsyncMock()
    mock_ws.close = AsyncMock()
    mock_ws.closed = False
    
    # Mocking async iterator requires a bit of setup
    # but we can test logic manually in individual tests if needed
    
    return mock_ws

@pytest.fixture
def mock_session(mock_ws_response):
    """Mock aiohttp ClientSession."""
    session = AsyncMock()
    session.ws_connect = AsyncMock(return_value=mock_ws_response)
    
    # Properly mock async context manager for session.post
    mock_post_resp = AsyncMock()
    mock_post_resp.status = 200
    mock_post_resp.json = AsyncMock(return_value={"id_token": "mock-token", "refresh_token": "mock-refresh", "expires_in": 3600})
    
    mock_post = AsyncMock()
    mock_post.return_value.__aenter__.return_value = mock_post_resp
    session.post = mock_post
    
    session.close = AsyncMock()
    return session

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield

from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.anova_culinary.const import DOMAIN, CONF_TOKEN
from custom_components.anova_culinary.anova_api.product import AnovaProduct

@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mocked Config Entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Anova Culinary",
        data={CONF_TOKEN: "mock-valid-token"},
        entry_id="test_anova_entry_id",
    )

@pytest.fixture
async def init_integration(hass, mock_config_entry):
    """Set up the Anova integration securely for testing platforms."""
    mock_config_entry.add_to_hass(hass)

    async def mock_connect(self):
        """Simulate connection and immediate discovery payloads."""
        self._process_discovery([{"cookerId": "APC-123", "type": "a7", "name": "Test Cooker"}], AnovaProduct.APC)
        self._process_discovery([{"cookerId": "APO-456", "type": "oven_v2", "name": "Test Oven"}], AnovaProduct.APO)
        return True

    with patch("custom_components.anova_culinary.AnovaClient.connect", new=mock_connect):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    return mock_config_entry
