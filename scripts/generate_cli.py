#!/usr/bin/env python3
"""
Auto-generate Click CLI commands from the Judgment OpenAPI spec.

Usage:
    python scripts/generate_cli.py [SPEC_URL_OR_FILE]

Reads the OpenAPI spec and produces src/judgment_cli/generated_commands.py
containing Click command groups for every operation in INCLUDE_OPERATIONS.
"""

from __future__ import annotations

import json
import re
import sys
import textwrap
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Default spec location
# ---------------------------------------------------------------------------
DEFAULT_SPEC = "https://api2.judgmentlabs.ai/openapi/json"

# ---------------------------------------------------------------------------
# Include list — only these operations become CLI commands.
# Each entry maps an OpenAPI operationId to a CLI group + command name.
# ---------------------------------------------------------------------------

INCLUDE_OPERATIONS: list[dict[str, Any]] = [
    # ── orgs ──────────────────────────────────────────────────────
    {
        "operation_id": "getOrganizations",
        "group": "orgs",
        "command": "list",
        "description": "List organizations for the current user",
    },
    {
        "operation_id": "getOrganizationsByOrganization_id",
        "group": "orgs",
        "command": "get",
        "description": "Get organization details",
    },
    {
        "operation_id": "getOrganizationsByOrganization_idUsage",
        "group": "orgs",
        "command": "usage",
        "description": "Get organization usage metrics",
    },
    # ── projects ──────────────────────────────────────────────────
    {
        "operation_id": "getProjects",
        "group": "projects",
        "command": "list",
        "description": "List all projects in the organization",
    },
    {
        "operation_id": "getProjectsByProject_id",
        "group": "projects",
        "command": "get",
        "description": "Get a project by ID",
    },
    # ── traces ────────────────────────────────────────────────────
    # "traces list" is hand-written in trace_search.py (search with filters)
    {
        "operation_id": "getProjectsByProject_idTracesByTrace_id",
        "group": "traces",
        "command": "get",
        "description": "Get trace details",
    },
    {
        "operation_id": "getProjectsByProject_idTracesByTrace_idSpans",
        "group": "traces",
        "command": "spans",
        "description": "Get all spans for a trace",
    },
    {
        "operation_id": "getProjectsByProject_idTracesByTrace_idBehaviors",
        "group": "traces",
        "command": "behaviors",
        "description": "Get behaviors detected on a trace",
    },
    # ── datasets ──────────────────────────────────────────────────
    {
        "operation_id": "getProjectsByProject_idDatasets",
        "group": "datasets",
        "command": "list",
        "description": "List all datasets in a project",
    },
    # ── judges ────────────────────────────────────────────────────
    {
        "operation_id": "getProjectsByProject_idJudges",
        "group": "judges",
        "command": "list",
        "description": "List all judges in a project",
    },
    {
        "operation_id": "getProjectsByProject_idJudgesByJudge_id",
        "group": "judges",
        "command": "get",
        "description": "Get judge details and versions",
    },
    {
        "operation_id": "getProjectsByProject_idJudgesModels",
        "group": "judges",
        "command": "models",
        "description": "List available LLM models for judges",
    },
    # ── behaviors ─────────────────────────────────────────────────
    {
        "operation_id": "getProjectsByProject_idBehaviors",
        "group": "behaviors",
        "command": "list",
        "description": "List all behaviors in a project",
    },
    {
        "operation_id": "getProjectsByProject_idBehaviorsByBehavior_id",
        "group": "behaviors",
        "command": "get",
        "description": "Get behavior details",
    },
    # ── tests ─────────────────────────────────────────────────────
    {
        "operation_id": "getProjectsByProject_idTests",
        "group": "tests",
        "command": "list",
        "description": "List test (experiment) runs",
    },
    # ── prompts ───────────────────────────────────────────────────
    {
        "operation_id": "getProjectsByProject_idPrompts",
        "group": "prompts",
        "command": "list",
        "description": "List all prompts in a project",
    },
    {
        "operation_id": "getProjectsByProject_idPromptsByPrompt_name",
        "group": "prompts",
        "command": "get",
        "description": "Get the latest version of a prompt",
    },
    {
        "operation_id": "getProjectsByProject_idPromptsByPrompt_nameList",
        "group": "prompts",
        "command": "versions",
        "description": "List all versions of a prompt",
    },
    # ── rules ─────────────────────────────────────────────────────
    {
        "operation_id": "getProjectsByProject_idRules",
        "group": "rules",
        "command": "list",
        "description": "List all rules in a project",
    },
    # ── sessions ──────────────────────────────────────────────────
    {
        "operation_id": "getProjectsByProject_idSessionsBySession_id",
        "group": "sessions",
        "command": "get",
        "description": "Get session details",
    },
]

# Friendly group descriptions
GROUP_DESCRIPTIONS: dict[str, str] = {
    "auth": "Authentication and user information",
    "health": "API health checks",
    "orgs": "Manage organizations",
    "projects": "Manage projects",
    "traces": "View and manage traces",
    "datasets": "Manage datasets",
    "judges": "Manage judges (scorers)",
    "behaviors": "View and manage behaviors",
    "tests": "View test / experiment runs",
    "prompts": "Manage prompt versions",
    "rules": "Manage automation rules",
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


def build_operation_index(spec: dict) -> dict[str, dict]:
    """Build {operationId: {path, method, operation}} from the spec."""
    index: dict[str, dict] = {}
    for path, path_item in spec.get("paths", {}).items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            op_id = operation.get("operationId")
            if op_id:
                index[op_id] = {
                    "path": path,
                    "method": method.upper(),
                    "operation": operation,
                }
    return index


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
    return s.lower().replace("-", "_")


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
    """Generate the source lines for a single GET Click command."""
    path_params = extract_path_params(path)
    query_params = extract_query_params(operation)

    lines: list[str] = []

    lines.append(f'@{group_name}_group.command("{cmd_name}")')

    for pp in path_params:
        lines.append(f'@click.argument("{pp}")')

    for qp in query_params:
        opt = cli_option_name(qp["name"])
        var = py_var_name(qp["name"])
        if qp["required"]:
            lines.append(f'@click.option("--{opt}", "{var}", required=True)')
        else:
            lines.append(f'@click.option("--{opt}", "{var}", default=None)')

    lines.append("@click.pass_context")

    sig_parts = ["ctx"] + path_params + [py_var_name(q["name"]) for q in query_params]
    lines.append(f"def {func_name}({', '.join(sig_parts)}):")
    lines.append(f'    """{description}."""')

    if path_params:
        url_template = path
        for pp in path_params:
            url_template = url_template.replace(f"{{{pp}}}", f"{{{pp}}}")
        lines.append(f'    url = f"{url_template}"')
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

    call_args = [f'"GET"', "url"]
    if query_params:
        call_args.append("params=params")

    lines.append(f'    result = ctx.obj["client"].request({", ".join(call_args)})')
    lines.append("    _output(result)")

    return lines


def generate_all(spec: dict) -> str:
    """Generate the full generated_commands.py source."""
    op_index = build_operation_index(spec)

    # Group the include list
    groups: dict[str, list[dict]] = {}
    for entry in INCLUDE_OPERATIONS:
        op_id = entry["operation_id"]
        if op_id not in op_index:
            print(f"WARNING: operationId '{op_id}' not found in spec — skipping", file=sys.stderr)
            continue
        gname = entry["group"]
        groups.setdefault(gname, []).append({**entry, **op_index[op_id]})

    # --- header ---
    out = textwrap.dedent("""\
        # Auto-generated by scripts/generate_cli.py
        # DO NOT EDIT MANUALLY

        from __future__ import annotations

        import json

        import click


        def _output(data: object) -> None:
            \"\"\"Pretty-print response data as JSON.\"\"\"
            click.echo(json.dumps(data, indent=2, default=str))

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
