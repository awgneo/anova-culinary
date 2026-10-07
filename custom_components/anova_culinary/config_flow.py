"""Config flow for Anova API integration: sign in with the Anova account."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .anova_api import AnovaAuth, AnovaAuthError, AnovaClient, AnovaConnectionError, AnovaSignIn
from .const import CONF_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class AnovaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Anova API."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Sign in with an Anova account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            sign_in = await self._sign_in(user_input, errors)
            if sign_in is not None:
                await self.async_set_unique_id(sign_in.user_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_EMAIL], data={CONF_TOKEN: sign_in.refresh_token})
        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Anova stopped accepting the sign-in."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Sign in again with the same account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            sign_in = await self._sign_in(user_input, errors)
            if sign_in is not None:
                await self.async_set_unique_id(sign_in.user_id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates={CONF_TOKEN: sign_in.refresh_token}
                )
        return self.async_show_form(step_id="reauth_confirm", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    async def _sign_in(self, user_input: dict[str, Any], errors: dict[str, str]) -> AnovaSignIn | None:
        """Signs in and checks the connection, filling `errors` on failure."""
        session = async_get_clientsession(self.hass)
        try:
            sign_in = await AnovaAuth.login(session, user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
            client = AnovaClient(sign_in.refresh_token, session)
            try:
                await client.connect()
            finally:
                await client.close()
        except AnovaAuthError:
            errors["base"] = "invalid_auth"
        except AnovaConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return sign_in
        return None
