"""Shared UI helpers for the Judgment CLI."""

from __future__ import annotations

import json
import sys
from typing import Callable, NoReturn, Sequence, TypeVar

import click

T = TypeVar("T")


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


def select_item(
    title: str,
    items: Sequence[T],
    *,
    label: Callable[[T], str],
    page_size: int = 12,
) -> T:
    """Select one item with a searchable TTY UI or numeric fallback."""
    if not items:
        raise click.ClickException(f"No {title.lower()} available.")
    if _can_use_interactive_selector():
        return _select_item_interactive(
            title,
            items,
            label=label,
            page_size=page_size,
        )
    return _select_item_by_number(title, items, label=label)


def _can_use_interactive_selector() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _select_item_by_number(
    title: str,
    items: Sequence[T],
    *,
    label: Callable[[T], str],
) -> T:
    click.echo(title)
    for idx, item in enumerate(items, start=1):
        click.echo(f"{idx}. {label(item)}")
    choice = click.prompt("Choose", type=click.IntRange(1, len(items)))
    return items[choice - 1]


def _select_item_interactive(
    title: str,
    items: Sequence[T],
    *,
    label: Callable[[T], str],
    page_size: int,
) -> T:
    query = ""
    selected = 0

    while True:
        matches = _filter_item_indexes(items, query, label=label)
        if selected >= len(matches):
            selected = max(0, len(matches) - 1)

        _render_selector(
            title,
            items,
            matches,
            selected=selected,
            query=query,
            label=label,
            page_size=page_size,
        )

        char = _read_selector_key()
        if char in ("\x03", "\x04"):
            raise click.Abort()
        if char in ("\r", "\n"):
            if matches:
                click.clear()
                return items[matches[selected]]
            continue
        if char in ("\x7f", "\b"):
            query = query[:-1]
            selected = 0
            continue
        if char in ("\x1b[A", "\x1bOA"):
            selected = max(0, selected - 1)
            continue
        if char in ("\x1b[B", "\x1bOB"):
            selected = min(len(matches) - 1, selected + 1) if matches else 0
            continue
        if char.startswith("\x1b"):
            query = ""
            selected = 0
            continue
        if char.isprintable():
            query += char
            selected = 0


def _render_selector(
    title: str,
    items: Sequence[T],
    matches: list[int],
    *,
    selected: int,
    query: str,
    label: Callable[[T], str],
    page_size: int,
) -> None:
    click.clear()
    click.echo(title)
    click.echo(f"Search: {query}")
    click.echo("Use arrows, type to filter, Enter to select, Esc to clear.")

    if not matches:
        click.echo("\n(no matches)")
        return

    start, end = _selector_window(selected, len(matches), page_size)
    click.echo(f"\nShowing {start + 1}-{end} of {len(matches)}")
    for visible_pos, match_idx in enumerate(matches[start:end], start=start):
        marker = ">" if visible_pos == selected else " "
        rendered = f"{marker} {label(items[match_idx])}"
        if visible_pos == selected:
            rendered = click.style(rendered, bold=True, fg="cyan")
        click.echo(rendered)


def _read_selector_key() -> str:
    char = click.getchar(echo=False)
    if char != "\x1b":
        return char

    # Arrow keys may arrive as separate ESC+[+letter characters on POSIX.
    # Wait very briefly for the rest so a plain Esc still works as "clear".
    try:
        import select

        parts = [char]
        while len(parts) < 3 and select.select([sys.stdin], [], [], 0.01)[0]:
            parts.append(click.getchar(echo=False))
        return "".join(parts)
    except Exception:
        return char


def _filter_item_indexes(
    items: Sequence[T],
    query: str,
    *,
    label: Callable[[T], str],
) -> list[int]:
    terms = [term for term in _normalize_query(query).split(" ") if term]
    if not terms:
        return list(range(len(items)))
    matches: list[int] = []
    for idx, item in enumerate(items):
        normalized = _normalize_query(label(item))
        if all(term in normalized for term in terms):
            matches.append(idx)
    return matches


def _selector_window(selected: int, total: int, page_size: int) -> tuple[int, int]:
    page_size = max(1, page_size)
    if total <= page_size:
        return 0, total
    half = page_size // 2
    start = max(0, selected - half)
    end = min(total, start + page_size)
    start = max(0, end - page_size)
    return start, end


def _normalize_query(value: str) -> str:
    return " ".join(value.casefold().split())


def mask_key(key: str) -> str:
    """Mask an API key for safe display."""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "…" + key[-4:]
