from __future__ import annotations

from pathlib import Path

from judgment_cli import config


def test_resolve_prefers_env_api_key_over_oauth_config(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "_config_dir", lambda: tmp_path)
    config.save_oauth(
        access_token="oauth-access",
        refresh_token="oauth-refresh",
        expires_at=123,
    )
    monkeypatch.setenv("JUDGMENT_API_KEY", "env-key")

    resolved = config.resolve()

    assert resolved.api_key == "env-key"
    assert resolved.refresh_token == ""
    assert resolved.auth_type == "api_key"


def test_resolve_uses_oauth_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "_config_dir", lambda: tmp_path)
    monkeypatch.delenv("JUDGMENT_API_KEY", raising=False)
    config.save_oauth(
        access_token="oauth-access",
        refresh_token="oauth-refresh",
        expires_at=123,
    )

    resolved = config.resolve()

    assert resolved.api_key == "oauth-access"
    assert resolved.refresh_token == "oauth-refresh"
    assert resolved.expires_at == 123
    assert resolved.auth_type == "oauth"
    assert tuple(resolved) == (resolved.base_url, "oauth-access")


def test_save_api_key_clears_oauth_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "_config_dir", lambda: tmp_path)
    monkeypatch.delenv("JUDGMENT_API_KEY", raising=False)
    config.save_oauth(
        access_token="oauth-access",
        refresh_token="oauth-refresh",
        expires_at=123,
    )

    config.save(api_key="manual-key")

    saved = config.load()
    assert saved == {"auth_type": "api_key", "api_key": "manual-key"}
