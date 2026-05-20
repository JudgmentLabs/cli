from __future__ import annotations

import time

import httpx

from judgment_cli.client import JudgmentClient
from judgment_cli.oauth import OAuthTokens


def test_oauth_client_refreshes_expired_token(monkeypatch) -> None:
    refreshed: list[OAuthTokens] = []

    def fake_refresh_tokens(*, base_url: str, refresh_token: str) -> OAuthTokens:
        assert base_url == "https://cli.example"
        assert refresh_token == "old-refresh"
        return OAuthTokens(
            access_token="new-access",
            refresh_token="new-refresh",
            expires_at=int(time.time()) + 3600,
        )

    monkeypatch.setattr("judgment_cli.client.refresh_tokens", fake_refresh_tokens)

    client = JudgmentClient(
        "https://cli.example",
        "old-access",
        auth_type="oauth",
        refresh_token="old-refresh",
        expires_at=1,
        token_updater=refreshed.append,
    )

    headers = client._auth_headers()

    assert headers["Authorization"] == "Bearer new-access"
    assert client.refresh_token == "new-refresh"
    assert refreshed and refreshed[0].access_token == "new-access"


def test_oauth_client_retries_once_after_unauthorized(monkeypatch) -> None:
    tokens = OAuthTokens(
        access_token="new-access",
        refresh_token="new-refresh",
        expires_at=int(time.time()) + 3600,
    )
    monkeypatch.setattr(
        "judgment_cli.client.refresh_tokens",
        lambda *, base_url, refresh_token: tokens,
    )

    seen_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization", ""))
        if len(seen_auth) == 1:
            return httpx.Response(401, json={"message": "expired"})
        return httpx.Response(200, json={"ok": True})

    client = JudgmentClient(
        "https://cli.example",
        "old-access",
        auth_type="oauth",
        refresh_token="old-refresh",
        expires_at=int(time.time()) + 3600,
    )
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    assert client.request("GET", "/organizations") == {"ok": True}
    assert seen_auth == ["Bearer old-access", "Bearer new-access"]
