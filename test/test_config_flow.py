"""Tests for the config flow: sign-in, one entry per account, and signing in again."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.anova_culinary.anova_api import AnovaAuthError, AnovaClient, AnovaConnectionError, AnovaSignIn
from custom_components.anova_culinary.const import DOMAIN

CREDENTIALS = {"email": "me@example.com", "password": "secret"}


@pytest.fixture
def sign_in():
    """Signing in and connecting succeed as user-1."""
    with (
        patch(
            "custom_components.anova_culinary.config_flow.AnovaAuth.login",
            return_value=AnovaSignIn(user_id="user-1", refresh_token="refresh-1"),
        ) as login,
        patch.object(AnovaClient, "connect", return_value=None),
        patch.object(AnovaClient, "close", return_value=None),
        patch("custom_components.anova_culinary.async_setup_entry", return_value=True),
    ):
        yield login


async def test_form(hass) -> None:
    """Test we get the form."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}


async def test_sign_in(hass, sign_in) -> None:
    """Signing in keeps the refresh token, under the account's id."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER}, data=CREDENTIALS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "me@example.com"
    assert result["data"] == {"token": "refresh-1"}
    assert result["result"].unique_id == "user-1"


async def test_same_account_twice(hass, sign_in, mock_config_entry) -> None:
    """An account can only be added once."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER}, data=CREDENTIALS)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("error", "reason"),
    [(AnovaAuthError("bad"), "invalid_auth"), (AnovaConnectionError("down"), "cannot_connect"), (RuntimeError(), "unknown")],
)
async def test_errors(hass, error, reason) -> None:
    """Sign-in failures show on the form."""
    with patch("custom_components.anova_culinary.config_flow.AnovaAuth.login", side_effect=error):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER}, data=CREDENTIALS)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": reason}


async def test_reauth(hass, sign_in, mock_config_entry) -> None:
    """Signing in again replaces the token."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == {"token": "refresh-1"}


async def test_reauth_other_account(hass, sign_in, mock_config_entry) -> None:
    """Signing in again with another account is refused."""
    mock_config_entry.add_to_hass(hass)
    sign_in.return_value = AnovaSignIn(user_id="someone-else", refresh_token="refresh-2")
    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["reason"] == "wrong_account"
