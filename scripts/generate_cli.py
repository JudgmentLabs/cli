#!/usr/bin/env python3
"""Auto-generate Click CLI commands from the Judgment OpenAPI spec.

This script consumes ``cli-server``'s OpenAPI document and emits
``src/judgment_cli/generated_commands.py``. The CLI server is the single
source of truth for command names, descriptions, option help, and group
structure — this generator is a thin renderer.

The generator reads, in order of preference:

* ``operationId``  — required, ``"<group>.<command>"``. Determines both the
  Click group and the command name.
* ``tags[0]``      — used as a fallback for the group when ``operationId``
  is missing.
* spec-level ``tags`` — used to populate group docstrings.
* operation ``summary`` + ``description`` — Click command docstring.
* schema-level ``description`` on each request-body / query property —
  Click ``--option`` help.

Routes whose ``operationId`` is in :data:`MANUAL_COMMANDS` are skipped so
that hand-written commands (e.g. ``judgment judges upload``) own those
slots.

Run ``python scripts/generate_cli.py --help`` for usage.
"""

from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
import textwrap
from typing import Any

import httpx

DEFAULT_SPEC = "https://cli.judgmentlabs.ai/openapi/json"

# Operations whose CLI command is hand-written in judgment_cli/judges.py
# (or another extension module) and must not be auto-generated.
MANUAL_COMMANDS = {"judges.upload"}


# ---------------------------------------------------------------------------
# Spec loading + traversal
# ---------------------------------------------------------------------------


def load_spec(source: str) -> dict:
    if source.startswith("http"):
        r = httpx.get(source, timeout=30)
        r.raise_for_status()
        return r.json()
    with open(source) as f:
        return json.load(f)


def derive_group_and_command(
    operation: dict, path: str, method: str
) -> tuple[str, str]:
    """Map an OpenAPI operation to ``(group, command)``.

    Requires an explicit ``operationId`` of the form ``"<group>.<command>"``.
    Falls back to ``tags[0]`` plus the path's last segment when ``operationId``
    is missing but a tag is present. Raises ``SystemExit`` if neither is set —
    every route in cli-server is expected to declare both.
    """
    op_id = operation.get("operationId")
    if op_id and "." in op_id:
        group, _, command = op_id.partition(".")
        return group, command

    tags = operation.get("tags") or []
    if tags:
        group = str(tags[0])
        parts = [p for p in path.strip("/").split("/") if p and p != group]
        command = parts[-1] if parts else (
            "list" if method.upper() == "GET" else method.lower()
        )
        return group, command

    raise SystemExit(
        f"Operation {method} {path} has neither an operationId nor a tag. "
        "Add `detail: { tags: ['<group>'], operationId: '<group>.<command>' }` "
        "to the route in the server."
    )


def collect_operations(spec: dict) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            if not isinstance(operation, dict):
                continue
            op_id = operation.get("operationId")
            if op_id in MANUAL_COMMANDS:
                continue
            group, command = derive_group_and_command(
                operation, path, method.upper()
            )
            base = command
            suffix = 2
            while (group, command) in seen:
                command = f"{base}-{suffix}"
                suffix += 1
            seen.add((group, command))
            operations.append(
                {
                    "group": group,
                    "command": command,
                    "path": path,
                    "method": method.upper(),
                    "operation": operation,
                }
            )
    operations.sort(key=lambda e: (e["group"], e["command"], e["path"]))
    return operations


def collect_group_descriptions(spec: dict) -> dict[str, str]:
    """Pull `{tag_name: description}` out of the spec's top-level tags array."""
    descriptions: dict[str, str] = {}
    for tag in spec.get("tags") or []:
        if not isinstance(tag, dict):
            continue
        name = tag.get("name")
        desc = tag.get("description")
        if name and desc:
            descriptions[name] = desc
    return descriptions


# ---------------------------------------------------------------------------
# Schema + parameter introspection
# ---------------------------------------------------------------------------


def extract_path_params(path: str) -> list[str]:
    return re.findall(r"\{(\w+)\}", path)


def extract_query_params(operation: dict) -> list[dict]:
    return [
        {
            "name": p["name"],
            "required": p.get("required", False),
            "schema": p.get("schema", {}),
        }
        for p in operation.get("parameters", [])
        if p.get("in") == "query"
    ]


def cli_option_name(name: str) -> str:
    """Convert ``camelCase`` or ``snake_case`` to a kebab CLI flag name."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return s.lower().replace("_", "-")


def py_var_name(name: str) -> str:
    """Coerce *name* into a valid (non-reserved) Python identifier."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    s = s.lower().replace("-", "_")
    if keyword.iskeyword(s):
        s += "_value"
    return s


def _schema_type(schema: dict[str, Any]) -> str | None:
    if "type" in schema:
        return schema["type"]
    for option in schema.get("anyOf", []):
        if option.get("type") and option["type"] != "null":
            return option["type"]
    return None


def _is_scalar_schema(schema: dict[str, Any]) -> bool:
    return _schema_type(schema) in {"string", "integer", "number", "boolean"}


def _array_item_schema(schema: dict[str, Any]) -> dict[str, Any] | None:
    if _schema_type(schema) != "array":
        return None
    items = schema.get("items")
    return items if isinstance(items, dict) else None


def _is_scalar_array_schema(schema: dict[str, Any]) -> bool:
    item_schema = _array_item_schema(schema)
    return bool(item_schema and _is_scalar_schema(item_schema))


def _is_positional_scalar(schema: dict[str, Any]) -> bool:
    """Whether a required scalar should render as a Click positional arg.

    Only plain string scalars (no enum) qualify — they typically identify
    entities like ``PROJECT_ID`` or ``NAME`` and read naturally positionally.
    Required enums, numbers, and booleans become required ``--option`` flags
    instead, where a name like ``--combine-type all`` reads better than an
    anonymous ``{all|any}`` slot in the signature.
    """
    return _schema_type(schema) == "string" and not schema.get("enum")


def click_type_expr(schema: dict[str, Any]) -> str | None:
    schema_type = _schema_type(schema)
    if schema_type == "integer":
        return "int"
    if schema_type == "number":
        return "float"
    if schema_type == "boolean":
        return "bool"
    return None


def click_choice_expr(schema: dict[str, Any]) -> str | None:
    values = schema.get("enum")
    if not values:
        return None
    quoted = ", ".join(repr(v) for v in values)
    return f"click.Choice([{quoted}])"


def _schema_description(schema: dict[str, Any]) -> str | None:
    """Extract a human description from a schema (or any of its anyOf branches)."""
    desc = schema.get("description")
    if desc:
        return desc
    for option in schema.get("anyOf", []):
        if isinstance(option, dict) and option.get("description"):
            return option["description"]
    return None


def _quote(text: str) -> str:
    return repr(text)


def _emit_docstring(description: str) -> str:
    """Render a Click command docstring, preserving paragraph breaks."""
    short, _, long = description.partition("\n\n")
    if not long:
        return f'    """{short}"""'
    paragraphs = ["\b\n" + p for p in long.split("\n\n")]
    full = short + "\n\n" + "\n\n".join(paragraphs)
    return f"    {repr(full)}"


def click_param_args(
    schema: dict[str, Any],
    *,
    include_help: bool = False,
) -> str:
    """Render extra ``click.option``/``click.argument`` args (type, choices, help)."""
    args: list[str] = []
    choice_expr = click_choice_expr(schema)
    if choice_expr:
        args.append(f"type={choice_expr}")
    else:
        type_expr = click_type_expr(schema)
        if type_expr:
            args.append(f"type={type_expr}")
    if include_help:
        desc = _schema_description(schema)
        if desc:
            args.append(f"help={_quote(desc)}")
    return f", {', '.join(args)}" if args else ""


def extract_json_body_properties(operation: dict) -> list[dict[str, Any]]:
    request_body = operation.get("requestBody") or {}
    json_content = (request_body.get("content") or {}).get(
        "application/json"
    ) or {}
    schema = json_content.get("schema") or {}
    if schema.get("type") != "object":
        return []

    required = set(schema.get("required", []))
    return [
        {
            "name": name,
            "required": name in required,
            "schema": prop_schema,
            "scalar": _is_scalar_schema(prop_schema),
            "scalar_array": _is_scalar_array_schema(prop_schema),
            "positional": (
                name in required
                and _is_scalar_schema(prop_schema)
                and _is_positional_scalar(prop_schema)
            ),
        }
        for name, prop_schema in (schema.get("properties") or {}).items()
    ]


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


def generate_command_code(
    group_name: str,
    cmd_name: str,
    func_name: str,
    description: str,
    path: str,
    method: str,
    operation: dict,
) -> list[str]:
    """Render the source lines for a single Click command."""
    path_params = extract_path_params(path)
    query_params = extract_query_params(operation)
    body_props = extract_json_body_properties(operation)

    lines: list[str] = [f'@{group_name}_group.command("{cmd_name}")']

    for pp in path_params:
        lines.append(f'@click.argument("{pp}")')

    for qp in query_params:
        opt = cli_option_name(qp["name"])
        var = py_var_name(qp["name"])
        if qp["required"] and _is_positional_scalar(qp["schema"]):
            type_arg = click_param_args(qp["schema"])
            lines.append(f'@click.argument("{qp["name"]}"{type_arg})')
        elif qp["required"]:
            type_arg = click_param_args(qp["schema"], include_help=True)
            lines.append(
                f'@click.option("--{opt}", "{var}", required=True{type_arg})'
            )
        else:
            type_arg = click_param_args(qp["schema"], include_help=True)
            lines.append(
                f'@click.option("--{opt}", "{var}", default=None{type_arg})'
            )

    if method != "GET":
        for prop in body_props:
            opt = cli_option_name(prop["name"])
            var = py_var_name(prop["name"])
            if prop["positional"]:
                type_arg = click_param_args(prop["schema"])
                lines.append(f'@click.argument("{prop["name"]}"{type_arg})')
            elif prop["scalar"]:
                type_arg = click_param_args(prop["schema"], include_help=True)
                required_arg = (
                    ", required=True" if prop["required"] else ", default=None"
                )
                lines.append(
                    f'@click.option("--{opt}", "{var}"{required_arg}{type_arg})'
                )
            elif prop["scalar_array"]:
                item_type_arg = click_param_args(
                    _array_item_schema(prop["schema"]) or {}, include_help=False
                )
                desc = (
                    _schema_description(prop["schema"])
                    or f"Repeatable; one value per item for {prop['name']}."
                )
                required_arg = ", required=True" if prop["required"] else ""
                lines.append(
                    f'@click.option("--{opt}", "{var}", multiple=True{required_arg}{item_type_arg}, help={_quote(desc)})'
                )
            else:
                desc = (
                    _schema_description(prop["schema"])
                    or f"JSON value for {prop['name']}."
                )
                required_arg = (
                    ", required=True" if prop["required"] else ", default=None"
                )
                lines.append(
                    f'@click.option("--{opt}", "{var}"{required_arg}, help={_quote(desc)})'
                )

    lines.append("@click.pass_context")

    sig_parts = ["ctx"] + path_params + [py_var_name(q["name"]) for q in query_params]
    if method != "GET":
        sig_parts += [py_var_name(prop["name"]) for prop in body_props]
    lines.append(f"def {func_name}({', '.join(sig_parts)}):")
    lines.append(_emit_docstring(description))

    if path_params:
        lines.append(f'    url = f"{path}"')
    else:
        lines.append(f'    url = "{path}"')

    if query_params:
        lines.append("    params = {}")
        for qp in query_params:
            var = py_var_name(qp["name"])
            if qp["required"]:
                lines.append(f'    params["{qp["name"]}"] = {var}')
            else:
                lines.append(f"    if {var} is not None:")
                lines.append(f'        params["{qp["name"]}"] = {var}')

    if method == "GET":
        call_args = [f'"{method}"', "url"]
        if query_params:
            call_args.append("params=params")
        lines.append(
            f'    result = ctx.obj["client"].request({", ".join(call_args)})'
        )
        lines.append("    _output(result)")
        return lines

    lines.append("    body = {}")
    for prop in body_props:
        var = py_var_name(prop["name"])
        if prop["scalar"]:
            if prop["required"]:
                lines.append(f'    body["{prop["name"]}"] = {var}')
            else:
                lines.append(f"    if {var} is not None:")
                lines.append(f'        body["{prop["name"]}"] = {var}')
        elif prop["scalar_array"]:
            lines.append(f"    if {var}:")
            lines.append(f'        body["{prop["name"]}"] = list({var})')
        else:
            if prop["required"]:
                lines.append(f'    body["{prop["name"]}"] = json.loads({var})')
            else:
                lines.append(f"    if {var} is not None:")
                lines.append(f'        body["{prop["name"]}"] = json.loads({var})')

    lines.append(
        f'    result = ctx.obj["client"].request("{method}", url, json_body=body)'
    )
    lines.append("    _output(result)")

    return lines


def derive_description(operation: dict, group: str, command: str) -> str:
    summary = operation.get("summary")
    description = operation.get("description")
    if summary and description:
        return f"{summary}\n\n{description}"
    return summary or description or f"{command.replace('-', ' ').title()} {group}"


def generate_all(spec: dict) -> str:
    operations = collect_operations(spec)
    group_descriptions = collect_group_descriptions(spec)
    groups: dict[str, list[dict]] = {}
    for entry in operations:
        groups.setdefault(entry["group"], []).append(entry)

    out = textwrap.dedent("""\
        # Auto-generated by scripts/generate_cli.py
        # DO NOT EDIT MANUALLY

        from __future__ import annotations

        import json

        import click

        from judgment_cli.ui import output as _output

    """)

    missing = sorted(set(groups) - set(group_descriptions))
    if missing:
        raise SystemExit(
            "Missing top-level OpenAPI tag description for group(s): "
            f"{', '.join(missing)}. Add a `{{ name, description }}` entry to "
            "the `tags` array in cli-server/index.ts for each group."
        )

    for gname in sorted(groups):
        desc = group_descriptions[gname]
        out += "\n"
        out += f"# {'─' * 68}\n"
        out += f"# Group: {gname}\n"
        out += f"# {'─' * 68}\n"
        out += "\n\n"
        out += f'@click.group("{gname}")\n'
        out += f"def {gname}_group() -> None:\n"
        out += f"    {_quote(desc)}\n"

        for entry in groups[gname]:
            out += "\n\n"
            func_name = f"{gname}_{entry['command']}".replace("-", "_")
            cmd_lines = generate_command_code(
                group_name=gname,
                cmd_name=entry["command"],
                func_name=func_name,
                description=derive_description(
                    entry["operation"], gname, entry["command"]
                ),
                path=entry["path"],
                method=entry["method"],
                operation=entry["operation"],
            )
            out += "\n".join(cmd_lines) + "\n"

        out += "\n"

    out += "\n"
    out += "def register_commands(cli: click.Group) -> None:\n"
    out += '    """Register all generated command groups on the root CLI."""\n'
    for gname in sorted(groups):
        out += f'    cli.add_command({gname}_group, "{gname}")\n'

    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Click CLI commands from the Judgment OpenAPI spec.",
    )
    parser.add_argument(
        "--spec",
        default=DEFAULT_SPEC,
        metavar="URL_OR_FILE",
        help=f"OpenAPI spec URL or local file path (default: {DEFAULT_SPEC}).",
    )
    args = parser.parse_args()

    print(f"Loading OpenAPI spec from {args.spec} ...", file=sys.stderr)
    spec = load_spec(args.spec)
    print(f"Found {len(spec.get('paths', {}))} paths", file=sys.stderr)

    code = generate_all(spec)

    out_path = "src/judgment_cli/generated_commands.py"
    with open(out_path, "w") as f:
        f.write(code)
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
