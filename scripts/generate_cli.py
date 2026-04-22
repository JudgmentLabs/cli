#!/usr/bin/env python3
"""
Auto-generate Click CLI commands from the Judgment OpenAPI spec.

Usage:
    python scripts/generate_cli.py [SPEC_URL_OR_FILE]

Reads the OpenAPI spec and produces src/judgment_cli/generated_commands.py
containing Click command groups for every operation except excluded endpoints.
"""

from __future__ import annotations

import json
import keyword
import re
import sys
import textwrap
from typing import Any

import httpx

from help_overrides import command_help, option_help

DEFAULT_SPEC = "https://api3.judgmentlabs.ai/openapi/json"
EXCLUDED_PATHS = {"/", "/health/", "/judges/upload"}

GROUP_DESCRIPTIONS: dict[str, str] = {
    "auth": "Authentication and user information",
    "automations": "Manage automations",
    "docs": "Search and read docs",
    "projects": "Manage projects",
    "root": "Top-level API routes",
    "traces": "View and manage traces",
    "judges": "Manage judges (scorers)",
    "behaviors": "View and manage behaviors",
    "sessions": "View and manage sessions",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_spec(source: str) -> dict:
    if source.startswith("http"):
        r = httpx.get(source, timeout=30)
        r.raise_for_status()
        return r.json()
    with open(source) as f:
        return json.load(f)


def derive_group_and_command(path: str, method: str) -> tuple[str, str]:
    parts = [part for part in path.strip("/").split("/") if part]
    if not parts:
        return "root", "index"
    if len(parts) == 1:
        if method == "GET":
            return parts[0], "list"
        return parts[0], method.lower()

    group = parts[0]
    tail = parts[-1]
    if tail == "detail":
        command = "get"
    elif tail == "page":
        command = "read"
    else:
        command = tail
    return group, command


def derive_description(operation: dict, group: str, command: str) -> str:
    override = command_help(group, command)
    if override:
        return override
    summary = operation.get("summary")
    description = operation.get("description")
    if summary and description:
        return f"{summary}\n\n{description}"
    return summary or description or f"{command.replace('-', ' ').title()} {group}"


def collect_operations(spec: dict) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path, path_item in spec.get("paths", {}).items():
        if path in EXCLUDED_PATHS:
            continue
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            group, command = derive_group_and_command(path, method.upper())
            original_command = command
            suffix = 2
            while (group, command) in seen:
                command = f"{original_command}-{suffix}"
                suffix += 1
            seen.add((group, command))
            operations.append(
                {
                    "group": group,
                    "command": command,
                    "description": derive_description(operation, group, command),
                    "path": path,
                    "method": method.upper(),
                    "operation": operation,
                }
            )
    operations.sort(key=lambda e: (e["group"], e["command"], e["path"]))
    return operations


def extract_path_params(path: str) -> list[str]:
    return re.findall(r"\{(\w+)\}", path)


def extract_query_params(operation: dict) -> list[dict]:
    params = []
    for p in operation.get("parameters", []):
        if p.get("in") == "query":
            params.append(
                {
                    "name": p["name"],
                    "required": p.get("required", False),
                    "schema": p.get("schema", {}),
                }
            )
    return params


def cli_option_name(name: str) -> str:
    """Convert a camelCase or snake_case name to a CLI --option-name."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return s.lower().replace("_", "-")


def py_var_name(name: str) -> str:
    """Ensure a valid Python variable name."""
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
    """Pull a human-readable description out of an OpenAPI schema, if any."""
    desc = schema.get("description")
    if desc:
        return desc
    for option in schema.get("anyOf", []):
        if isinstance(option, dict) and option.get("description"):
            return option["description"]
    return None


def _quote_help(text: str) -> str:
    """Encode a string as a Python source literal."""
    return repr(text)


def _emit_docstring(description: str) -> str:
    """Build the docstring source line for a generated command."""
    short, _, long = description.partition("\n\n")
    if not long:
        if not short.endswith((".", "!", "?")):
            short += "."
        return f'    """{short}"""'
    paragraphs = ["\b\n" + p for p in long.split("\n\n")]
    full = short + "\n\n" + "\n\n".join(paragraphs)
    return f"    {repr(full)}"


def click_param_args(
    schema: dict[str, Any],
    *,
    include_help: bool = False,
    help_override: str | None = None,
) -> str:
    args: list[str] = []
    choice_expr = click_choice_expr(schema)
    if choice_expr:
        args.append(f"type={choice_expr}")
    else:
        type_expr = click_type_expr(schema)
        if type_expr:
            args.append(f"type={type_expr}")
    if include_help:
        desc = help_override or _schema_description(schema)
        if desc:
            args.append(f"help={_quote_help(desc)}")
    return f", {', '.join(args)}" if args else ""


def extract_json_body_properties(operation: dict) -> list[dict[str, Any]]:
    request_body = operation.get("requestBody") or {}
    content = request_body.get("content") or {}
    json_content = content.get("application/json") or {}
    schema = json_content.get("schema") or {}
    if schema.get("type") != "object":
        return []

    required = set(schema.get("required", []))
    props: list[dict[str, Any]] = []
    for name, prop_schema in (schema.get("properties") or {}).items():
        props.append(
            {
                "name": name,
                "required": name in required,
                "schema": prop_schema,
                "scalar": _is_scalar_schema(prop_schema),
                "scalar_array": _is_scalar_array_schema(prop_schema),
            }
        )
    return props


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
    """Generate the source lines for a single Click command."""
    path_params = extract_path_params(path)
    query_params = extract_query_params(operation)
    body_props = extract_json_body_properties(operation)

    lines: list[str] = []

    lines.append(f'@{group_name}_group.command("{cmd_name}")')

    for pp in path_params:
        lines.append(f'@click.argument("{pp}")')

    for qp in query_params:
        opt = cli_option_name(qp["name"])
        var = py_var_name(qp["name"])
        override = option_help(group_name, cmd_name, qp["name"])
        if qp["required"]:
            type_arg = click_param_args(qp["schema"])
            lines.append(f'@click.argument("{qp["name"]}"{type_arg})')
        else:
            type_arg = click_param_args(qp["schema"], include_help=True, help_override=override)
            lines.append(f'@click.option("--{opt}", "{var}", default=None{type_arg})')

    if method != "GET":
        for prop in body_props:
            opt = cli_option_name(prop["name"])
            var = py_var_name(prop["name"])
            override = option_help(group_name, cmd_name, prop["name"])
            if prop["scalar"] and prop["required"]:
                type_arg = click_param_args(prop["schema"])
                lines.append(f'@click.argument("{prop["name"]}"{type_arg})')
            elif prop["scalar"]:
                type_arg = click_param_args(prop["schema"], include_help=True, help_override=override)
                lines.append(f'@click.option("--{opt}", "{var}", default=None{type_arg})')
            elif prop["scalar_array"]:
                item_type_arg = click_param_args(_array_item_schema(prop["schema"]) or {}, include_help=False)
                desc = override or _schema_description(prop["schema"]) or f"Repeatable; one value per item for {prop['name']}."
                lines.append(
                    f'@click.option("--{opt}", "{var}", multiple=True{item_type_arg}, help={_quote_help(desc)})'
                )
            else:
                desc = override or _schema_description(prop["schema"]) or f"JSON value for {prop['name']}."
                required_arg = ", required=True" if prop["required"] else ", default=None"
                lines.append(
                    f'@click.option("--{opt}", "{var}"{required_arg}, help={_quote_help(desc)})'
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
        lines.append(f'    result = ctx.obj["client"].request({", ".join(call_args)})')
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

    lines.append(f'    result = ctx.obj["client"].request("{method}", url, json_body=body)')
    lines.append("    _output(result)")

    return lines


def generate_all(spec: dict) -> str:
    """Generate the full generated_commands.py source."""
    operations = collect_operations(spec)
    groups: dict[str, list[dict]] = {}
    for entry in operations:
        gname = entry["group"]
        groups.setdefault(gname, []).append(entry)

    # --- header ---
    out = textwrap.dedent("""\
        # Auto-generated by scripts/generate_cli.py
        # DO NOT EDIT MANUALLY

        from __future__ import annotations

        import json

        import click

        from judgment_cli.ui import output as _output

    """)

    # --- groups + commands ---
    for gname in sorted(groups):
        desc = GROUP_DESCRIPTIONS.get(gname, f"Manage {gname}")
        out += "\n"
        out += f"# {'─' * 68}\n"
        out += f"# Group: {gname}\n"
        out += f"# {'─' * 68}\n"
        out += "\n\n"
        out += f'@click.group("{gname}")\n'
        out += f"def {gname}_group() -> None:\n"
        out += f'    """{desc}."""\n'
        out += "    pass\n"

        for entry in groups[gname]:
            out += "\n\n"
            func_name = f"{gname}_{entry['command']}".replace("-", "_")
            cmd_lines = generate_command_code(
                group_name=gname,
                cmd_name=entry["command"],
                func_name=func_name,
                description=entry["description"],
                path=entry["path"],
                method=entry["method"],
                operation=entry["operation"],
            )
            out += "\n".join(cmd_lines) + "\n"

    # --- register function ---
    out += "\n\n"
    out += "def register_commands(cli: click.Group) -> None:\n"
    out += '    """Register all generated command groups on the root CLI."""\n'
    for gname in sorted(groups):
        out += f'    cli.add_command({gname}_group, "{gname}")\n'
    out += ""

    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    spec_source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SPEC
    print(f"Loading OpenAPI spec from {spec_source} ...", file=sys.stderr)
    spec = load_spec(spec_source)
    print(f"Found {len(spec.get('paths', {}))} paths", file=sys.stderr)

    code = generate_all(spec)

    out_path = "src/judgment_cli/generated_commands.py"
    with open(out_path, "w") as f:
        f.write(code)
    print(f"Wrote {out_path}", file=sys.stderr)
