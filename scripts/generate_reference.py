#!/usr/bin/env python3
"""Render the Judgment CLI's Click command tree as MDX reference docs.

Walks the registered ``judgment`` Click group, emits one MDX file per
group (plus a short index), and writes the result to ``--out``. Run
locally to preview, or from CI to publish into the docs repo's
``content/docs/sdk-reference/cli/`` tree.

Source of truth lives in ``src/judgment_cli/main.py`` and
``src/judgment_cli/generated_commands.py``; this script is a thin
renderer that introspects ``Click.Command``/``Click.Group`` objects.

Usage::

    python scripts/generate_reference.py --out content/docs/sdk-reference/cli
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Iterable

import click

from judgment_cli.main import cli as ROOT


# ---------------------------------------------------------------------------
# MDX rendering helpers
# ---------------------------------------------------------------------------


_FRONTMATTER_TEMPLATE = """\
---
title: "{title}"
description: "{description}"
---
"""


def _escape_mdx_inline(text: str) -> str:
    """Escape characters that MDX would otherwise parse as JSX.

    Only the literal ``<`` and ``>`` need escaping in inline prose; angle
    brackets inside fenced code blocks are left alone by MDX.
    """
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _escape_table_cell(text: str) -> str:
    """Escape a cell so it survives a single-row Markdown table."""
    text = text.replace("|", "\\|")
    text = text.replace("\n", " ")
    return _escape_mdx_inline(text).strip()


def _strip_help(text: str | None) -> str:
    """Normalise a Click help string for prose rendering.

    Click uses ``\\b`` to disable rewrapping in terminal help; that's
    noise in MDX, so drop it. We also rescue indented "literal" blocks
    (the convention Click users follow alongside ``\\b``) by promoting
    them to fenced code blocks — otherwise lines like ``  # bash`` get
    parsed by MDX as H1 headings, since 2-space indent isn't enough for
    Markdown to recognise a code block.
    """
    if not text:
        return ""
    text = text.replace("\b", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _promote_indented_blocks(text)
    return text.strip()


def _promote_indented_blocks(text: str) -> str:
    """Wrap runs of 2-space-indented lines in fenced bash code blocks.

    Matches Click's ``\\b``-style literal blocks where each line is
    indented with two or more spaces (and blank lines may separate
    consecutive indented runs that we want to keep together). The
    leading indent is stripped before fencing.

    Lines that are already inside a fenced ``` block in the source help
    are left alone, so we don't double-wrap structural JSON shape blocks
    that the OpenAPI spec emits with indented content.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    in_fence = False
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if not in_fence and line.startswith("  ") and line.strip():
            block: list[str] = []
            while i < len(lines):
                cur = lines[i]
                if cur.lstrip().startswith("```"):
                    break
                if cur.startswith("  ") and cur.strip():
                    block.append(cur[2:])
                    i += 1
                    continue
                # Allow a single blank line to join two indented runs.
                if not cur.strip() and i + 1 < len(lines) and lines[i + 1].startswith("  "):
                    block.append("")
                    i += 1
                    continue
                break
            out.append("```bash")
            out.extend(block)
            out.append("```")
        else:
            out.append(line)
            i += 1
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Param introspection
# ---------------------------------------------------------------------------


def _param_type_label(param: click.Parameter) -> str:
    """Render a Click param type as a short token suitable for a table cell.

    Choice values are rendered as a comma-separated list rather than a
    pipe-separated union, because pipes get stranded at line starts and
    ends when the cell wraps. Commas glue to the preceding value and let
    the browser break cleanly between options.
    """
    t = param.type
    if isinstance(t, click.Choice):
        return ", ".join(f"`{c}`" for c in t.choices)
    if isinstance(t, click.types.BoolParamType):
        return "boolean"
    if isinstance(t, click.types.IntParamType):
        return "integer"
    if isinstance(t, click.types.FloatParamType):
        return "number"
    if isinstance(t, click.Path):
        return "path"
    name = getattr(t, "name", "") or "string"
    return name


def _flag_names(opt: click.Option) -> str:
    """Render an Option's primary flag(s) as backticked tokens."""
    flags = list(opt.opts) + list(opt.secondary_opts or [])
    return ", ".join(f"`{f}`" for f in flags) if flags else f"`--{opt.name}`"


def _flag_names_nowrap(opt: click.Option) -> str:
    """Render flag names as HTML ``<code>`` with ``white-space: nowrap``.

    Hyphens are valid line-break opportunities in ``<code>``, so a long
    flag like ``--trigger-frequency-period-unit`` (or even short ones in
    a narrow first column) will wrap mid-flag in a Markdown table.
    Render each flag as inline HTML so the table cell never breaks
    inside a flag name.
    """
    flags = list(opt.opts) + list(opt.secondary_opts or [])
    if not flags:
        flags = [f"--{opt.name}"]
    return ", ".join(
        f'<code style={{{{whiteSpace:"nowrap"}}}}>{f}</code>' for f in flags
    )


def _argument_synopsis(arg: click.Argument) -> str:
    """Render a positional argument the way Click prints it in usage."""
    name = arg.human_readable_name.upper()
    if arg.nargs == -1:
        return f"[{name}...]"
    return f"<{name}>"


# ---------------------------------------------------------------------------
# Per-command rendering
# ---------------------------------------------------------------------------


def _render_command(
    group_name: str,
    command_name: str,
    cmd: click.Command,
    *,
    heading_level: int = 3,
) -> str:
    """Render a single command as an MDX section.

    ``group_name`` may be empty for top-level commands like ``login``.
    """
    arguments = [p for p in cmd.params if isinstance(p, click.Argument)]
    options = [
        p
        for p in cmd.params
        if isinstance(p, click.Option) and not p.hidden
    ]

    full_name = f"{group_name} {command_name}".strip()
    synopsis_parts = [f"judgment {full_name}"]
    if options:
        synopsis_parts.append("[OPTIONS]")
    synopsis_parts.extend(_argument_synopsis(a) for a in arguments)
    synopsis = " ".join(synopsis_parts)

    parts: list[str] = []
    parts.append(f"{'#' * heading_level} `{full_name}`")
    parts.append("")

    short = _strip_help(cmd.short_help)
    long = _strip_help(cmd.help)
    if long:
        parts.append(long)
        parts.append("")
    elif short:
        parts.append(short)
        parts.append("")

    parts.append("```bash")
    parts.append(synopsis)
    parts.append("```")
    parts.append("")

    if arguments:
        parts.append("**Arguments**")
        parts.append("")
        parts.append("| Name | Required |")
        parts.append("| ---- | -------- |")
        for arg in arguments:
            name = arg.human_readable_name.upper()
            required = "yes" if arg.required else "no"
            parts.append(f"| `{name}` | {required} |")
        parts.append("")

    if options:
        parts.append("**Options**")
        parts.append("")
        parts.append("| Flag | Type | Required | Description |")
        parts.append("| ---- | ---- | -------- | ----------- |")
        for opt in options:
            flag = _flag_names_nowrap(opt).replace("|", "\\|")
            type_label = _escape_table_cell(_param_type_label(opt))
            required = "yes" if opt.required else "no"
            help_text = _strip_help(opt.help)
            # Strip any embedded fenced code blocks from the table cell;
            # they don't fit inside a single Markdown row. The structural
            # JSON shapes get re-rendered as code blocks below the table.
            help_inline = re.sub(r"```.*?```", "", help_text, flags=re.DOTALL)
            help_inline = _escape_table_cell(help_inline)
            if not help_inline:
                help_inline = "—"
            parts.append(
                f"| {flag} | {type_label} | {required} | {help_inline} |"
            )
        parts.append("")

        # Re-emit any structural JSON shapes that were stripped from the
        # table — these are the most useful bits of help for flags like
        # `--conditions` and `--actions` and they need real code blocks.
        for opt in options:
            help_text = _strip_help(opt.help)
            blocks = re.findall(r"```(.*?)```", help_text, flags=re.DOTALL)
            if not blocks:
                continue
            parts.append(f"**`{_flag_names(opt).split(',')[0].strip('`')}` shape**")
            parts.append("")
            for block in blocks:
                body = block.strip()
                if not body:
                    continue
                lang_match = re.match(r"([a-zA-Z0-9]*)\n", body)
                if lang_match:
                    lang = lang_match.group(1) or "json"
                    body = body[lang_match.end():]
                else:
                    lang = "json"
                parts.append(f"```{lang}")
                parts.append(body.rstrip())
                parts.append("```")
                parts.append("")

    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Per-group / index rendering
# ---------------------------------------------------------------------------


def _iter_groups(root: click.Group) -> Iterable[tuple[str, click.Group | click.Command]]:
    """Yield (name, command) for every direct child of ``root``."""
    for name in sorted(root.commands.keys()):
        yield name, root.commands[name]


def _short_description(text: str) -> str:
    """Trim a help string to a single sentence suitable for frontmatter.

    MDX frontmatter is YAML-ish — long multi-line values with embedded
    quotes and code blocks regularly break parsers. Take only the first
    paragraph, collapse whitespace, and strip quotes.
    """
    if not text:
        return ""
    first = text.split("\n\n", 1)[0]
    first = re.sub(r"\s+", " ", first).strip()
    return first.replace('"', "'")


def _render_group(group_name: str, group: click.Group) -> str:
    """Render a Click group as a full MDX page."""
    title = group_name.capitalize()
    description = _strip_help(group.help) or f"`judgment {group_name}` commands."
    description_inline = _short_description(description)

    parts = [_FRONTMATTER_TEMPLATE.format(title=title, description=description_inline)]
    parts.append("")
    parts.append(description)
    parts.append("")

    commands = sorted(group.commands.items())
    if commands:
        parts.append("## Commands")
        parts.append("")
        parts.append("| Command | Description |")
        parts.append("| ------- | ----------- |")
        for cmd_name, cmd in commands:
            short = _strip_help(cmd.short_help) or _strip_help(cmd.help).split("\n")[0]
            parts.append(
                f"| [`{group_name} {cmd_name}`](#{group_name}-{cmd_name}) "
                f"| {_escape_table_cell(short) or '—'} |"
            )
        parts.append("")

    for cmd_name, cmd in commands:
        parts.append(_render_command(group_name, cmd_name, cmd))
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def _render_top_level_command(name: str, cmd: click.Command) -> str:
    """Render a top-level ``judgment <command>`` (e.g. ``login``) as an MDX page."""
    title = f"judgment {name}"
    description = _strip_help(cmd.short_help) or _strip_help(cmd.help) or f"`judgment {name}`."
    description_inline = _short_description(description)

    parts = [_FRONTMATTER_TEMPLATE.format(title=title, description=description_inline)]
    parts.append("")
    parts.append(_render_command("", name, cmd, heading_level=2).lstrip())
    return "\n".join(parts).rstrip() + "\n"


def _render_index(root: click.Group, group_files: list[tuple[str, str]]) -> str:
    """Render the CLI reference landing page."""
    parts = [
        _FRONTMATTER_TEMPLATE.format(
            title="CLI Reference",
            description="Auto-generated reference for every judgment CLI command and flag.",
        ),
        "",
        "Reference for every command and flag exposed by the `judgment` CLI. "
        "Most commands are auto-generated from the Judgment API's OpenAPI spec, so this page "
        "tracks the latest server surface.",
        "",
        "For installation, authentication, and quickstart usage, see the "
        "[CLI guide](/documentation/cli).",
        "",
        "## Command groups",
        "",
        "| Group | Description |",
        "| ----- | ----------- |",
    ]

    for slug, group_name in group_files:
        cmd = root.commands[group_name]
        short = _strip_help(cmd.short_help) or _strip_help(cmd.help).split("\n")[0]
        parts.append(
            f"| [`{group_name}`](/sdk-reference/cli/{slug}) "
            f"| {_escape_table_cell(short) or '—'} |"
        )

    parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _render_meta(group_files: list[tuple[str, str]], top_level_files: list[tuple[str, str]]) -> str:
    """Render the meta.json that orders pages in the docs side-nav."""
    pages = ["index"]
    if top_level_files:
        pages.append("---Top-level---")
        for slug, _ in top_level_files:
            pages.append(slug)
    if group_files:
        pages.append("---Groups---")
        for slug, _ in group_files:
            pages.append(slug)

    return json.dumps({"title": "CLI", "pages": pages}, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


# Top-level commands worth surfacing as their own reference pages. We keep
# this list explicit rather than rendering every leaf, because the CLI also
# attaches groups directly under root and we want to skip those here.
_TOP_LEVEL_COMMANDS = ["login", "logout", "status", "configure", "completion"]


def render(out_dir: Path) -> None:
    """Render the full reference tree into ``out_dir``."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    group_files: list[tuple[str, str]] = []
    for name, child in _iter_groups(ROOT):
        if not isinstance(child, click.Group):
            continue
        slug = name
        (out_dir / f"{slug}.mdx").write_text(_render_group(name, child))
        group_files.append((slug, name))

    top_level_files: list[tuple[str, str]] = []
    for name in _TOP_LEVEL_COMMANDS:
        cmd = ROOT.commands.get(name)
        if cmd is None or isinstance(cmd, click.Group):
            continue
        slug = name
        (out_dir / f"{slug}.mdx").write_text(_render_top_level_command(name, cmd))
        top_level_files.append((slug, name))

    (out_dir / "index.mdx").write_text(_render_index(ROOT, group_files))
    (out_dir / "meta.json").write_text(_render_meta(group_files, top_level_files))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("dist/cli-reference"),
        help="Directory to write rendered MDX into. Will be cleared before rendering.",
    )
    args = parser.parse_args()
    render(args.out)
    print(f"Wrote CLI reference to {args.out}")


if __name__ == "__main__":
    main()
