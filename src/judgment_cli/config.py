"""Manage persistent CLI credentials stored in ~/.config/judgment/credentials.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_DEFAULT_BASE_URL = "https://api2.judgmentlabs.ai"


def _config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg) if xdg else Path.home() / ".config"
    return root / "judgment"


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    path.chmod(0o600)
    return path


def clear() -> bool:
    path = _config_path()
    if path.exists():
        path.unlink()
        return True
    return False


def resolve(
    *,
    flag_base_url: str | None,
    flag_api_key: str | None,
    flag_org_id: str | None,
) -> tuple[str, str, str | None]:
    """Return (base_url, api_key, org_id) using precedence: flag > env > config file."""
    cfg = load()

    base_url = (
        flag_base_url
        or os.environ.get("JUDGMENT_BASE_URL")
        or cfg.get("base_url")
        or _DEFAULT_BASE_URL
    )
    api_key = (
        flag_api_key
        or os.environ.get("JUDGMENT_API_KEY")
        or cfg.get("api_key")
        or ""
    )
    org_id = (
        flag_org_id
        or os.environ.get("JUDGMENT_ORG_ID")
        or cfg.get("org_id")
    )
    return base_url, api_key, org_id


def mask_key(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return key[:4] + "…" + key[-4:]
