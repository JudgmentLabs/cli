"""Resolve organization/project context for generated CLI commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import click

from judgment_cli import context as context_store
from judgment_cli.context_entities import (
    display_name,
    extract_items,
    organization_id as get_organization_id,
    organization_label,
    organization_name as get_organization_name,
    project_id as get_project_id,
    project_label,
    project_name as get_project_name,
    sort_projects_by_usage,
)
from judgment_cli.env import optional_env_var


ORG_ENV_VARS = ("JUDGMENT_ORG_ID", "JUDGMENT_ORGANIZATION_ID")
PROJECT_ENV_VAR = "JUDGMENT_PROJECT_ID"


@dataclass(frozen=True)
class ParsedContextualArgs:
    organization_id: str | None
    project_id: str | None
    values: dict[str, str]


def fetch_organizations(client: Any) -> list[dict[str, Any]]:
    response = client.request("GET", "/organizations")
    return extract_items(response, ("organizations",))


def fetch_projects(client: Any, organization_id: str) -> list[dict[str, Any]]:
    response = client.request(
        "GET",
        "/projects",
        params={"organization_id": organization_id},
    )
    return sort_projects_by_usage(extract_items(response, ("projects",)))


def parse_contextual_positionals(
    args: tuple[str, ...],
    *,
    positional_names: list[str],
    needs_organization_id: bool,
    needs_project_id: bool,
    organization_id: str | None = None,
    project_id: str | None = None,
) -> ParsedContextualArgs:
    """Split optional leading org/project IDs from command-specific args."""
    values = list(args)
    expected = len(positional_names)
    extra = len(values) - expected
    max_extra = int(needs_organization_id) + int(needs_project_id)

    if extra < 0:
        missing = positional_names[len(values) :]
        raise click.UsageError(f"Missing argument(s): {', '.join(missing)}")
    if extra > max_extra:
        raise click.UsageError(
            f"Got {len(values)} positional arguments, expected at most "
            f"{expected + max_extra}."
        )

    positional_organization_id: str | None = None
    positional_project_id: str | None = None
    if needs_organization_id and needs_project_id:
        if extra == 2:
            positional_organization_id = values[0]
            positional_project_id = values[1]
        elif extra == 1:
            positional_project_id = values[0]
    elif needs_organization_id and extra == 1:
        positional_organization_id = values[0]
    elif needs_project_id and extra == 1:
        positional_project_id = values[0]

    if (
        organization_id
        and positional_organization_id
        and organization_id != positional_organization_id
    ):
        raise click.UsageError(
            "Pass organization ID either positionally or with --organization-id, not both."
        )
    if project_id and positional_project_id and project_id != positional_project_id:
        raise click.UsageError(
            "Pass project ID either positionally or with --project-id, not both."
        )

    command_values = values[extra:]
    return ParsedContextualArgs(
        organization_id=organization_id or positional_organization_id,
        project_id=project_id or positional_project_id,
        values=dict(zip(positional_names, command_values)),
    )


def resolve_context(
    client: Any,
    *,
    organization_id: str | None = None,
    organization_name: str | None = None,
    project_id: str | None = None,
    project_name: str | None = None,
    require_project: bool = False,
) -> context_store.ActiveContext:
    """Resolve org/project IDs from CLI values, env vars, context, or API data."""
    if organization_id and organization_name:
        raise click.ClickException(
            "Pass only one of --organization-id or --organization."
        )
    if project_id and project_name:
        raise click.ClickException("Pass only one of --project-id or --project.")

    saved = context_store.load_context()
    env_org_id = _first_env(ORG_ENV_VARS)
    env_project_id = optional_env_var(PROJECT_ENV_VAR)

    org: dict[str, Any] | None = None
    project: dict[str, Any] | None = None

    if organization_name:
        org = _find_one_by_name(
            fetch_organizations(client),
            organization_name,
            "organization",
        )
        organization_id = get_organization_id(org)
    elif not organization_id:
        organization_id = env_org_id or _str_or_none(saved.get("organization_id"))

    if project_name:
        if organization_id:
            projects = fetch_projects(client, organization_id)
            project = _find_one_by_name(projects, project_name, "project")
            project_id = get_project_id(project)
        else:
            org, project = _find_project_across_organizations(
                client,
                project_name=project_name,
            )
            organization_id = get_organization_id(org)
            project_id = get_project_id(project)
    elif not project_id:
        project_id = env_project_id
        saved_project_id = _str_or_none(saved.get("project_id"))
        saved_organization_id = _str_or_none(saved.get("organization_id"))
        if (
            not project_id
            and saved_project_id
            and (not organization_id or saved_organization_id == organization_id)
        ):
            project_id = saved_project_id

    if not organization_id and project_id:
        org, project = _find_project_across_organizations(
            client,
            project_id=project_id,
        )
        organization_id = get_organization_id(org)
        project_id = get_project_id(project)

    if not organization_id:
        organizations = fetch_organizations(client)
        if len(organizations) == 1:
            org = organizations[0]
            organization_id = get_organization_id(org)
        else:
            raise click.ClickException(_organization_help(organizations))

    if not require_project:
        return context_store.ActiveContext(
            organization_id=organization_id,
            organization_name=get_organization_name(org)
            or _saved_name(saved, "organization", organization_id),
        )

    if not project_id:
        saved_project_id = _str_or_none(saved.get("project_id"))
        if (
            saved_project_id
            and saved.get("organization_id") == organization_id
        ):
            project_id = saved_project_id
        else:
            projects = fetch_projects(client, organization_id)
            if len(projects) == 1:
                project = projects[0]
                project_id = get_project_id(project)
            else:
                raise click.ClickException(_project_help(projects, organization_id))

    return context_store.ActiveContext(
        organization_id=organization_id,
        project_id=project_id,
        organization_name=get_organization_name(org)
        or _saved_name(saved, "organization", organization_id),
        project_name=get_project_name(project)
        or _saved_name(saved, "project", project_id),
    )


def _find_one_by_name(
    items: list[dict[str, Any]],
    name: str,
    entity_name: str,
) -> dict[str, Any]:
    exact = [
        item
        for item in items
        if (display_name(item) or "").casefold() == name.casefold()
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise click.ClickException(
            f"Multiple {entity_name}s named {name!r}; pass the ID instead."
        )
    raise click.ClickException(f"No {entity_name} named {name!r} was found.")


def _find_project_across_organizations(
    client: Any,
    *,
    project_id: str | None = None,
    project_name: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for organization in fetch_organizations(client):
        oid = get_organization_id(organization)
        if not oid:
            continue
        for project in fetch_projects(client, oid):
            if project_id and get_project_id(project) == project_id:
                matches.append((organization, project))
            elif (
                project_name
                and (get_project_name(project) or "").casefold()
                == project_name.casefold()
            ):
                matches.append((organization, project))

    label = project_id or project_name or "project"
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise click.ClickException(
            f"Multiple projects matched {label!r}; pass --organization-id too."
        )
    raise click.ClickException(f"No project matched {label!r}.")


def _organization_help(organizations: list[dict[str, Any]]) -> str:
    if not organizations:
        return "No organizations were found for this account."
    choices = "\n".join(f"  {organization_label(org)}" for org in organizations[:10])
    return (
        "No organization selected. Run `judgment context set`, pass "
        "--organization-id, or set JUDGMENT_ORG_ID.\n\nOrganizations:\n"
        f"{choices}"
    )


def _project_help(projects: list[dict[str, Any]], organization_id: str) -> str:
    if not projects:
        return f"No projects were found for organization {organization_id}."
    choices = "\n".join(f"  {project_label(project)}" for project in projects[:10])
    return (
        "No project selected. Run `judgment context set`, pass --project-id, "
        "or set JUDGMENT_PROJECT_ID.\n\nMost-used projects:\n"
        f"{choices}"
    )


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = optional_env_var(name)
        if value:
            return value
    return None


def _saved_name(
    saved: dict[str, Any],
    prefix: str,
    entity_id: str | None,
) -> str | None:
    if saved.get(f"{prefix}_id") != entity_id:
        return None
    return _str_or_none(saved.get(f"{prefix}_name"))


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
