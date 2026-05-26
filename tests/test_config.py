from __future__ import annotations

from pathlib import Path

from judgment_cli import config


def test_save_api_key_clears_oauth_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )
    monkeypatch.delenv("JUDGMENT_API_KEY", raising=False)
    config.save_oauth(
        access_token="oauth-access",
        refresh_token="oauth-refresh",
        expires_at=123,
    )

    config.save(api_key="manual-key")

    saved = config.load()
    assert saved == {"auth_type": "api_key", "api_key": "manual-key"}


def test_resolve_base_url_prefers_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )
    monkeypatch.setenv("JUDGMENT_BASE_URL", "https://env.example")

    assert config.resolve_base_url() == "https://env.example"


def test_resolve_auth_url_prefers_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )
    monkeypatch.setenv("JUDGMENT_AUTH_URL", "https://auth-env.example")

    assert config.resolve_auth_url() == "https://auth-env.example"
