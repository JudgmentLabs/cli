"""Labels for organization and project API records."""

from __future__ import annotations

from typing import Any


def organization_label(organization: dict[str, Any]) -> str:
    return f"{organization['detail']['name']}  {organization['organization_id']}"


def project_label(project: dict[str, Any]) -> str:
    traces = trace_count(project)
    suffix = f"  {traces:,} traces" if traces is not None else ""
    return f"{project['project_name']}{suffix}  {project['project_id']}"


def trace_count(project: dict[str, Any]) -> int | None:
    value = project.get("total_traces")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None
