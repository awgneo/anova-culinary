"""Firebase sign-in for Anova, made the way the Anova Oven app's Firebase SDK makes it.

Anova issues no token of its own: the WebSocket and every Anova backend take the Firebase
ID token (project anova-app). See PROTOCOL.md, part 1, §1.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from .exceptions import AnovaAuthError, AnovaConnectionError

_LOGGER = logging.getLogger(__name__)

# The Oven app's Firebase configuration (resources/res/values/strings.xml) and the headers its
# Firebase Auth SDK (firebase-auth 23.2.0) adds to every request
ANOVA_API_KEY = "AIzaSyCGJwHXUhkNBdPkH3OAkjc9-3xMMjvanfU"
ANOVA_HEADERS = {
    "X-Android-Package": "com.anovaculinary.anovaoven",
    "X-Android-Cert": "CBDEEEE8460457C57EFEBCA5C0207A8FC2F03D66",
    "X-Client-Version": "Android/Fallback/X23002000/FirebaseCore-Android",
    "X-Firebase-GMPID": "1:322173998509:android:ea694bec308287f4c07d24",
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 14)",
}
IDENTITY_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={ANOVA_API_KEY}"
TOKEN_URL = f"https://securetoken.googleapis.com/v1/token?key={ANOVA_API_KEY}"

# Refresh this long before the ID token expires
REFRESH_MARGIN = 300


@dataclass
class AnovaSignIn:
    """A signed-in account: its Firebase user id and refresh token."""

    user_id: str
    refresh_token: str


class AnovaAuth:
    """Keeps a valid Firebase ID token, refreshing it from the refresh token."""

    def __init__(self, session: aiohttp.ClientSession, refresh_token: str) -> None:
        """Initialize from a refresh token kept from sign-in."""
        self._session = session
        self._refresh_token = refresh_token
        self._id_token: str | None = None
        self._expires_at = 0.0
        self.user_id: str | None = None

    @property
    def expires_at(self) -> float:
        """When the current ID token stops being valid (epoch seconds, less the margin)."""
        return self._expires_at

    @classmethod
    async def login(cls, session: aiohttp.ClientSession, email: str, password: str) -> AnovaSignIn:
        """Sign in with an Anova account's email and password."""
        data = await _post(session, IDENTITY_URL, json={"email": email, "password": password, "returnSecureToken": True})
        return AnovaSignIn(user_id=data["localId"], refresh_token=data["refreshToken"])

    async def get_valid_token(self) -> str:
        """The current ID token, refreshed when it's about to expire."""
        if self._id_token is None or time.time() >= self._expires_at:
            data = await _post(self._session, TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": self._refresh_token})
            self._id_token = data["id_token"]
            self._refresh_token = data["refresh_token"]
            self.user_id = data.get("user_id")
            expires_in = int(data.get("expires_in", 3600))
            self._expires_at = time.time() + expires_in - REFRESH_MARGIN
            _LOGGER.debug("Refreshed the Anova sign-in (expires in %ds)", expires_in)
        return self._id_token


async def _post(session: aiohttp.ClientSession, url: str, **body: Any) -> dict[str, Any]:
    """POSTs to Firebase Auth; a rejection is an auth error, anything else a connection error."""
    try:
        async with session.post(url, headers=ANOVA_HEADERS, timeout=aiohttp.ClientTimeout(total=10), **body) as response:
            data = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise AnovaConnectionError(f"Couldn't reach Anova's sign-in service: {err}") from err
    if response.status != 200:
        message = (data.get("error") or {}).get("message") if isinstance(data, dict) else None
        raise AnovaAuthError(message or f"Sign-in was rejected ({response.status})")
    return data
