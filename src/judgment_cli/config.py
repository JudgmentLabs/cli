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


class ResolvedLLM(NamedTuple):
    base_url: str
    api_key: str
    model: str
    auto_execute: bool


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
    data: dict[str, Any] = {
        k: v for k, v in load().items() if k.startswith("llm_")
    }
    data["api_key"] = api_key
    if base_url and base_url != _DEFAULT_BASE_URL:
        data["base_url"] = base_url
    else:
        data.pop("base_url", None)
    return _write(data)


def update_llm(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    auto_execute: bool | None = None,
) -> Path:
    data = load()
    if base_url is not None:
        data["llm_base_url"] = base_url
    if api_key is not None:
        data["llm_api_key"] = api_key
    if model is not None:
        data["llm_model"] = model
    if auto_execute is not None:
        data["llm_auto_execute"] = auto_execute
    return _write(data)


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
        or ""
    )
    return ResolvedCredentials(base_url=base_url, api_key=api_key)


def resolve_llm() -> ResolvedLLM | None:
    """Resolve OpenAI-compatible LLM settings for natural-language commands."""
    cfg = load()

    base_url = (
        optional_env_var("JUDGMENT_LLM_BASE_URL")
        or optional_env_var("LLM_BASE_URL")
        or cfg.get("llm_base_url")
    )
    api_key = (
        optional_env_var("JUDGMENT_LLM_API_KEY")
        or optional_env_var("LLM_API_KEY")
        or cfg.get("llm_api_key")
    )
    model = (
        optional_env_var("JUDGMENT_LLM_MODEL")
        or optional_env_var("LLM_MODEL")
        or cfg.get("llm_model")
    )
    auto_execute_raw: object = (
        optional_env_var("JUDGMENT_LLM_AUTO_EXECUTE")
        or optional_env_var("LLM_AUTO_EXECUTE")
        or cfg.get("llm_auto_execute")
        or False
    )

    if not base_url or not api_key or not model:
        return None

    return ResolvedLLM(
        base_url=str(base_url).rstrip("/"),
        api_key=str(api_key),
        model=str(model),
        auto_execute=_as_bool(auto_execute_raw),
    )


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
