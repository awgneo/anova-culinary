"""Test the Anova API config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from custom_components.anova_culinary.const import DOMAIN
from custom_components.anova_culinary.config_flow import validate_input

async def test_form_user(hass):
    """Test we get the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["errors"] == {}

async def test_form_invalid_token(hass):
    """Test we handle invalid auth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER},
        data={"token": "bad-token"}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_format"

async def test_form_valid(hass):
    """Test successful flow."""
    with patch(
        "custom_components.anova_culinary.config_flow.AnovaClient.connect", 
        return_value=True
    ), patch(
        "custom_components.anova_culinary.config_flow.AnovaClient.close",
        return_value=None
    ), patch(
        "custom_components.anova_culinary.async_setup_entry",
        return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={"token": "anova-test-token-123"},
        )
        
        assert result["type"] == "create_entry"
        assert result["title"] == "Anova WiFi Devices"
        assert result["data"] == {"token": "anova-test-token-123"}
