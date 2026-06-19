"""Persistent default organization/project context for the CLI."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from judgment_cli import config


@dataclass(frozen=True)
class ActiveContext:
    organization_id: str
    project_id: str | None = None
    organization_name: str | None = None
    project_name: str | None = None


def context_path() -> Path:
    return config.credentials_path().with_name("context.json")


def load_context() -> dict[str, Any]:
    path = context_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_context(context: ActiveContext) -> Path:
    data = {
        "organization_id": context.organization_id,
        "organization_name": context.organization_name,
        "project_id": context.project_id,
        "project_name": context.project_name,
    }
    data = {key: value for key, value in data.items() if value}

    path = context_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data, indent=2) + "\n")
    return path


def clear_context() -> bool:
    path = context_path()
    if path.exists():
        path.unlink()
        return True
    return False
