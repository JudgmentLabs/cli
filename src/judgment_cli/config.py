"""Manage persistent CLI credentials in a platform-appropriate config dir."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from judgment_cli.env import optional_env_var

DEFAULT_BASE_URL = "https://cli.judgmentlabs.ai"
DEFAULT_AUTH_URL = "https://auth.judgmentlabs.ai"
_APP_NAME = "judgment"
_APP_AUTHOR = "JudgmentLabs"


def credentials_path() -> Path:
    return Path(user_config_dir(_APP_NAME, _APP_AUTHOR)) / "credentials.json"


def load() -> dict[str, Any]:
    path = credentials_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save(*, api_key: str) -> Path:
    data: dict[str, str] = {"auth_type": "api_key", "api_key": api_key}
    return _write(data)


def save_oauth(
    *,
    access_token: str,
    refresh_token: str,
    expires_at: int,
) -> Path:
    data: dict[str, str | int] = {
        "auth_type": "oauth",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
    }
    return _write(data)


def update_oauth_tokens(
    *, access_token: str, refresh_token: str, expires_at: int
) -> Path:
    cfg = load()
    cfg.update(
        {
            "auth_type": "oauth",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }
    )
    cfg.pop("api_key", None)
    return _write(cfg)


def _write(data: dict[str, Any]) -> Path:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data, indent=2) + "\n")
    return path


def clear() -> bool:
    path = credentials_path()
    if path.exists():
        path.unlink()
        return True
    return False


def resolve_base_url() -> str:
    """Resolve the API base URL from env or the default."""
    return optional_env_var("JUDGMENT_BASE_URL") or DEFAULT_BASE_URL


def resolve_auth_url() -> str:
    """Resolve the OAuth server URL from env or the default."""
    return optional_env_var("JUDGMENT_AUTH_URL") or DEFAULT_AUTH_URL
