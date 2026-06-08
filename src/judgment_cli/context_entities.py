"""Normalize organization and project API records for CLI context flows."""

from __future__ import annotations

from typing import Any, Iterable

import click

from judgment_cli.context import ActiveContext


def extract_items(response: object, preferred_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]
    if not isinstance(response, dict):
        return []
    for key in preferred_keys:
        value = response.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for value in response.values():
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def sort_projects_by_usage(projects: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(projects, key=_project_usage_sort_key, reverse=True)


def organization_label(organization: dict[str, Any]) -> str:
    name = organization_name(organization) or "(unnamed organization)"
    oid = organization_id(organization) or "-"
    return f"{name}  {oid}"


def project_label(project: dict[str, Any]) -> str:
    name = project_name(project) or "(unnamed project)"
    pid = project_id(project) or "-"
    traces = trace_count(project)
    suffix = f"  {traces:,} traces" if traces is not None else ""
    return f"{name}{suffix}  {pid}"


def active_context_from_items(
    organization: dict[str, Any],
    project: dict[str, Any] | None = None,
) -> ActiveContext:
    oid = organization_id(organization)
    if not oid:
        raise click.ClickException("Selected organization is missing an ID.")
    return ActiveContext(
        organization_id=oid,
        organization_name=organization_name(organization),
        project_id=project_id(project) if project else None,
        project_name=project_name(project) if project else None,
    )


def display_name(item: dict[str, Any] | None) -> str | None:
    return organization_name(item) or project_name(item)


def organization_id(item: dict[str, Any] | None) -> str | None:
    return field(item, ("organization_id", "org_id", "id"))


def organization_name(item: dict[str, Any] | None) -> str | None:
    return field(
        item,
        (
            "organization_name",
            "org_name",
            "name",
            "display_name",
            "detail.name",
        ),
    )


def project_id(item: dict[str, Any] | None) -> str | None:
    return field(item, ("project_id", "id"))


def project_name(item: dict[str, Any] | None) -> str | None:
    return field(item, ("project_name", "name", "display_name"))


def trace_count(project: dict[str, Any]) -> int | None:
    for key in ("total_traces", "trace_count", "traces_count", "num_traces"):
        value = project.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def field(item: dict[str, Any] | None, names: tuple[str, ...]) -> str | None:
    if not item:
        return None
    for name in names:
        value: object = item
        for part in name.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if isinstance(value, str) and value:
            return value
    return None


def _project_usage_sort_key(project: dict[str, Any]) -> tuple[int, int, str]:
    favorite = bool(
        project.get("favorite")
        or project.get("is_favorite")
        or project.get("is_favorited")
    )
    traces = trace_count(project) or 0
    name = project_name(project) or ""
    return (int(favorite), traces, name.casefold())
