"""Shared UI helpers for the Judgment CLI."""

from __future__ import annotations

import json
import sys
from typing import NoReturn

import click


def output(data: object) -> None:
    """Pretty-print response data as JSON to stdout."""
    if isinstance(data, str):
        click.echo(data)
        return
    click.echo(json.dumps(data, indent=2, default=str))


def success(message: str) -> None:
    click.echo(message)


def error(message: str, *, exit_code: int = 1) -> NoReturn:
    click.echo(f"Error: {message}", err=True)
    sys.exit(exit_code)


def confirm(prompt: str, *, default: bool = False) -> bool:
    return click.confirm(prompt, default=default)


def mask_key(key: str) -> str:
    """Mask an API key for safe display."""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "…" + key[-4:]
