"""Manage persistent CLI credentials in a platform-appropriate config dir."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, NamedTuple

from platformdirs import user_config_dir

from judgment_cli.env import optional_env_var

_DEFAULT_BASE_URL = "https://cli.judgmentlabs.ai"
_APP_NAME = "judgment"
_APP_AUTHOR = "JudgmentLabs"


class ResolvedCredentials(NamedTuple):
    base_url: str
    api_key: str
    org_id: str | None


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


def save(*, api_key: str, org_id: str | None = None, base_url: str | None = None) -> Path:
    data: dict[str, str] = {"api_key": api_key}
    if org_id:
        data["org_id"] = org_id
    if base_url and base_url != _DEFAULT_BASE_URL:
        data["base_url"] = base_url
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
        or ""
    )
    org_id: str | None = (
        optional_env_var("JUDGMENT_ORG_ID")
        or cfg.get("org_id")
    )
    return ResolvedCredentials(base_url=base_url, api_key=api_key, org_id=org_id)
