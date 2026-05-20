from __future__ import annotations

from pathlib import Path

from judgment_cli import config


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


def test_resolve_base_url_prefers_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "_config_dir", lambda: tmp_path)
    config.save(api_key="manual-key", base_url="https://configured.example")
    monkeypatch.setenv("JUDGMENT_BASE_URL", "https://env.example")

    assert config.resolve_base_url() == "https://env.example"
