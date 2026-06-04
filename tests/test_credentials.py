from __future__ import annotations

import time

import pytest

from judgment_cli import config
from judgment_cli.credentials import (
    ApiKeyCredential,
    CredentialRefreshError,
    OAuthCredential,
    resolve as resolve_credential,
)
from judgment_cli.oauth import OAuthTokens


def test_api_key_credential_applies_bearer_header() -> None:
    headers: dict[str, str] = {}

    ApiKeyCredential("manual-key").apply(headers)

    assert headers["Authorization"] == "Bearer manual-key"


def test_resolve_prefers_env_api_key_over_oauth_config(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )
    config.save_oauth(
        access_token="oauth-access",
        refresh_token="oauth-refresh",
        expires_at=123,
    )
    monkeypatch.setenv("JUDGMENT_API_KEY", "env-key")

    resolved = resolve_credential()
    headers: dict[str, str] = {}
    resolved.credential.apply(headers)

    assert isinstance(resolved.credential, ApiKeyCredential)
    assert headers["Authorization"] == "Bearer env-key"


def test_resolve_uses_oauth_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )
    monkeypatch.delenv("JUDGMENT_API_KEY", raising=False)
    config.save_oauth(
        access_token="oauth-access",
        refresh_token="oauth-refresh",
        expires_at=int(time.time()) + 3600,
    )

    resolved = resolve_credential()
    headers: dict[str, str] = {}
    resolved.credential.apply(headers)

    assert isinstance(resolved.credential, OAuthCredential)
    assert headers["Authorization"] == "Bearer oauth-access"


def test_oauth_credential_refreshes_expired_token(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )

    def fake_refresh_tokens(*, auth_url: str, refresh_token: str) -> OAuthTokens:
        assert auth_url == "https://auth.example"
        assert refresh_token == "old-refresh"
        return OAuthTokens(
            access_token="new-access",
            refresh_token="new-refresh",
            expires_at=int(time.time()) + 3600,
        )

    monkeypatch.setattr("judgment_cli.credentials.refresh_tokens", fake_refresh_tokens)
    credential = OAuthCredential(
        auth_url="https://auth.example",
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=1,
    )
    headers: dict[str, str] = {}

    credential.apply(headers)

    assert headers["Authorization"] == "Bearer new-access"
    assert credential.refresh_token == "new-refresh"


def test_oauth_credential_refresh_persists_tokens(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )
    config.save_oauth(
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=1,
    )

    monkeypatch.setattr(
        "judgment_cli.credentials.refresh_tokens",
        lambda *, auth_url, refresh_token: OAuthTokens(
            access_token="new-access",
            refresh_token="new-refresh",
            expires_at=1234,
        ),
    )

    credential = OAuthCredential.from_config(config.load(), "https://auth.example")
    assert credential is not None
    credential.refresh()

    saved = config.load()
    assert saved["access_token"] == "new-access"
    assert saved["refresh_token"] == "new-refresh"
    assert saved["expires_at"] == 1234


def test_oauth_credential_refresh_parse_error_is_wrapped(monkeypatch) -> None:
    monkeypatch.setattr(
        "judgment_cli.credentials.refresh_tokens",
        lambda *, auth_url, refresh_token: (_ for _ in ()).throw(
            RuntimeError("OAuth response missing access_token")
        ),
    )
    credential = OAuthCredential(
        auth_url="https://auth.example",
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=1,
    )

    with pytest.raises(CredentialRefreshError, match="missing access_token"):
        credential.apply({})
