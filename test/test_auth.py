"""Tests for sign-in: the Oven app's Firebase request, and token refresh."""

from typing import Any

import pytest

from custom_components.anova_culinary.anova_api.auth import ANOVA_API_KEY, ANOVA_HEADERS, AnovaAuth
from custom_components.anova_culinary.anova_api.exceptions import AnovaAuthError
from fakes import FakeResponse


class SignInSession:
    """Answers Firebase's sign-in and token endpoints."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.posts: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.posts.append({"url": url, **kwargs})
        if self.status != 200:
            return FakeResponse(self.status, {"error": {"message": "INVALID_LOGIN_CREDENTIALS"}})
        if "signInWithPassword" in url:
            return FakeResponse(200, {"localId": "user-1", "refreshToken": "refresh-1", "idToken": "id-1", "expiresIn": "3600"})
        return FakeResponse(200, {"id_token": "id-2", "refresh_token": "refresh-2", "expires_in": "3600", "user_id": "user-1"})


async def test_login_like_the_app() -> None:
    """Sign-in uses the Oven app's API key and Android headers."""
    session = SignInSession()
    sign_in = await AnovaAuth.login(session, "me@example.com", "secret")
    assert (sign_in.user_id, sign_in.refresh_token) == ("user-1", "refresh-1")
    post = session.posts[0]
    assert post["url"].endswith(f"key={ANOVA_API_KEY}")
    assert post["headers"] == ANOVA_HEADERS
    assert post["headers"]["X-Android-Package"] == "com.anovaculinary.anovaoven"


async def test_login_rejected() -> None:
    """Wrong credentials are an auth error with Firebase's reason."""
    with pytest.raises(AnovaAuthError, match="INVALID_LOGIN_CREDENTIALS"):
        await AnovaAuth.login(SignInSession(400), "me@example.com", "wrong")


async def test_token_refreshes_once() -> None:
    """The ID token is refreshed from the refresh token, then reused until it expires."""
    session = SignInSession()
    auth = AnovaAuth(session, "refresh-1")
    assert await auth.get_valid_token() == "id-2"
    assert await auth.get_valid_token() == "id-2"
    assert len(session.posts) == 1
    assert session.posts[0]["data"] == {"grant_type": "refresh_token", "refresh_token": "refresh-1"}
    assert auth.user_id == "user-1"
