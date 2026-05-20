"""Manage persistent CLI credentials in a platform-appropriate config dir."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from platformdirs import user_config_dir

from judgment_cli.env import optional_env_var

_DEFAULT_BASE_URL = "https://cli.judgmentlabs.ai"
_APP_NAME = "judgment"
_APP_AUTHOR = "JudgmentLabs"


@dataclass(frozen=True)
class ResolvedCredentials:
    base_url: str
    api_key: str
    refresh_token: str = ""
    expires_at: int | None = None
    auth_type: str = "api_key"

    def __iter__(self) -> Iterator[str]:
        yield self.base_url
        yield self.api_key


def _config_dir() -> Path:
    return Path(user_config_dir(_APP_NAME, _APP_AUTHOR))


def _config_path() -> Path:
    return _config_dir() / "credentials.json"


def load() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save(*, api_key: str, base_url: str | None = None) -> Path:
    data: dict[str, str] = {"auth_type": "api_key", "api_key": api_key}
    if base_url and base_url != _DEFAULT_BASE_URL:
        data["base_url"] = base_url
    return _write(data)


def save_oauth(
    *,
    access_token: str,
    refresh_token: str,
    expires_at: int,
    base_url: str | None = None,
) -> Path:
    data: dict[str, str | int] = {
        "auth_type": "oauth",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
    }
    if base_url and base_url != _DEFAULT_BASE_URL:
        data["base_url"] = base_url
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
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data, indent=2) + "\n")
    return path


def clear() -> bool:
    path = _config_path()
    if path.exists():
        path.unlink()
        return True
    return False


def resolve() -> ResolvedCredentials:
    """Resolve credentials using precedence: env > config file > default."""
    cfg = load()

    base_url: str = (
        optional_env_var("JUDGMENT_BASE_URL")
        or cfg.get("base_url")
        or _DEFAULT_BASE_URL
    )
    api_key: str = (
        optional_env_var("JUDGMENT_API_KEY")
        or cfg.get("api_key")
        or cfg.get("access_token")
        or ""
    )
    refresh_token = (
        "" if optional_env_var("JUDGMENT_API_KEY") else cfg.get("refresh_token", "")
    )
    raw_expires_at = cfg.get("expires_at")
    expires_at = raw_expires_at if isinstance(raw_expires_at, int) else None
    auth_type = "api_key"
    if not optional_env_var("JUDGMENT_API_KEY") and cfg.get("auth_type") == "oauth":
        auth_type = "oauth"
    return ResolvedCredentials(
        base_url=base_url,
        api_key=api_key,
        refresh_token=refresh_token,
        expires_at=expires_at,
        auth_type=auth_type,
    )
