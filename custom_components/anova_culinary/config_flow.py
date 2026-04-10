"""Config flow for Anova API integration."""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .anova_api.client import AnovaClient
from .anova_api.auth import FirebaseAuthManager
from .anova_api.exceptions import AnovaAuthError, AnovaConnectionError
from .const import DOMAIN, CONF_TOKEN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    email = data.get("email")
    password = data.get("password")
    
    session = async_get_clientsession(hass)

    # User provided native login, fetch the Firebase refresh token
    try:
        auth_data = await FirebaseAuthManager.login(session, email, password)
        token = auth_data["refresh_token"]
    except AnovaAuthError:
        raise ValueError("invalid_auth")

    # Verify the token actually works in the client model
    client = AnovaClient(token=token, session=session)
    try:
        success = await client.connect()
        if not success:
            raise AnovaConnectionError("Connection returned false")
    except AnovaAuthError:
        raise ValueError("invalid_auth")
    except Exception:
        _LOGGER.exception("Unexpected exception")
        raise ValueError("cannot_connect")
    finally:
        await client.close()

    # Return info to store in the entry
    return {"title": "Anova WiFi Devices", "token": token}


class AnovaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Anova API."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                # Overwrite the user input with the verified token (or Firebase refresh token)
                return self.async_create_entry(title=info["title"], data={CONF_TOKEN: info["token"]})
            except ValueError as err:
                errors["base"] = str(err)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
