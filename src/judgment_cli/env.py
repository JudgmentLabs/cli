"""Environment-variable helpers for the Judgment CLI."""

from __future__ import annotations

import os
from typing import overload


@overload
def optional_env_var(var_name: str) -> str | None: ...


@overload
def optional_env_var(var_name: str, default: str) -> str: ...


def optional_env_var(var_name: str, default: str | None = None) -> str | None:
    return os.getenv(var_name, default)


def require_env_var(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {var_name}")
    return value
