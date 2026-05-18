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


def table_output(data: object, *, output_format: str = "table") -> None:
    """Render list response as table, yaml, or json based on --output flag."""
    if output_format == "json":
        output(data)
        return
    if output_format == "yaml":
        yaml_output(data)
        return

    items: list | None = None
    extra: dict = {}

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list):
                items = v
                extra = {ek: ev for ek, ev in data.items() if ek != k}
                break

    if items is None:
        output(data)
        return

    if not items:
        click.echo("(no items)")
        return

    if not isinstance(items[0], dict):
        for item in items:
            click.echo(str(item))
        return

    _render_table(items)

    for k, v in extra.items():
        if v is not None and v != {} and v != []:
            click.echo(f"\n{k}: {json.dumps(v, default=str)}")


def _render_table(items: list[dict]) -> None:
    import io
    from rich.console import Console
    from rich.table import Table
    import rich.box

    def _is_scalar(v: object) -> bool:
        return v is None or isinstance(v, (str, int, float, bool))

    all_cols = list(items[0].keys())
    cols = [c for c in all_cols if all(_is_scalar(item.get(c)) for item in items)]
    hidden = len(all_cols) - len(cols)

    table = Table(show_header=True, header_style="bold cyan", box=rich.box.SIMPLE)
    for col in cols:
        table.add_column(col, overflow="fold", max_width=48, no_wrap=False)

    for item in items:
        row = []
        for c in cols:
            v = item.get(c)
            if v is None:
                row.append("-")
            elif isinstance(v, bool):
                row.append("yes" if v else "no")
            else:
                s = str(v)
                row.append(s[:80] + "…" if len(s) > 80 else s)
        table.add_row(*row)

    if hidden:
        table.caption = f"{hidden} nested column(s) hidden — use -o json for full data"

    buf = io.StringIO()
    Console(file=buf, force_terminal=True).print(table)
    rendered = buf.getvalue()

    import os
    import subprocess
    env = os.environ.copy()
    env.setdefault("LESS", "FRX")
    pager = env.get("PAGER", "less")
    try:
        proc = subprocess.Popen(pager, shell=True, stdin=subprocess.PIPE, text=True, env=env)
        proc.communicate(rendered)
    except Exception:
        sys.stdout.write(rendered)


def yaml_output(data: object, *, output_format: str = "yaml") -> None:
    """Render response as YAML, or JSON if --output json."""
    if output_format == "json":
        output(data)
        return
    import yaml
    click.echo(yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False).rstrip())


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
