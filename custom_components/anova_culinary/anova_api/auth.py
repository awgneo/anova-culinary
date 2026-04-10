"""Firebase Authentication Manager for Anova API."""

import asyncio
import logging
import time
from typing import Optional, Dict

import aiohttp

from .exceptions import AnovaAuthError

_LOGGER = logging.getLogger(__name__)

ANOVA_API_KEY = "AIzaSyB0VNqmJVAeR1fn_NbqqhwSytyMOZ_JO9c"
IDENTITY_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={ANOVA_API_KEY}"
TOKEN_URL = f"https://securetoken.googleapis.com/v1/token?key={ANOVA_API_KEY}"

class FirebaseAuthManager:
    """Manages Firebase OAuth JWT rotations for Anova."""

    def __init__(self, session: aiohttp.ClientSession, refresh_token: str):
        """Initialize the Auth Manager with a permanent refresh token."""
        self._session = session
        self._refresh_token = refresh_token
        self._id_token: Optional[str] = None
        self._expires_at: float = 0.0

    @classmethod
    async def login(cls, session: aiohttp.ClientSession, email: str, password: str) -> Dict[str, str]:
        """Perform an initial email and password login to obtain a refresh token."""
        payload = {
            "email": email,
            "password": password,
            "returnSecureToken": True,
        }
        try:
            async with session.post(IDENTITY_URL, json=payload, timeout=10) as resp:
                data = await resp.json()
                if resp.status != 200:
                    error_msg = data.get("error", {}).get("message", "Unknown Auth Error")
                    raise AnovaAuthError(f"Login failed: {error_msg}")
                return {
                    "id_token": data["idToken"],
                    "refresh_token": data["refreshToken"],
                    "expires_in": int(data.get("expiresIn", 3600))
                }
        except Exception as err:
            raise AnovaAuthError(f"Network error during login: {err}") from err

    async def _rotate_token(self) -> None:
        """Exchange the refresh token for a brand new id_token."""
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        try:
            async with self._session.post(TOKEN_URL, data=payload, timeout=10) as resp:
                data = await resp.json()
                if resp.status != 200:
                    _LOGGER.error("Token rotation failed! Server responded: %s", data)
                    raise AnovaAuthError("Refresh token rejected or expired.")
                
                self._id_token = data["id_token"]
                self._refresh_token = data["refresh_token"]
                
                # Buffer expiration by 5 minutes securely
                expires_in = int(data.get("expires_in", 3600))
                self._expires_at = time.time() + expires_in - 300
                _LOGGER.debug("Successfully rotated Anova Firebase id_token (expires in %ds)", expires_in)
        except Exception as err:
            raise AnovaAuthError(f"Network error during token rotation: {err}") from err

    async def get_valid_token(self) -> str:
        """Return the current id_token, auto-rotating if computationally requested."""
        if not self._id_token or time.time() >= self._expires_at:
            await self._rotate_token()
        return self._id_token
