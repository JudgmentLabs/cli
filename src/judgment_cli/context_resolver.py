"""Resolve organization/project context for generated CLI commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import click

from judgment_cli import context as context_store
from judgment_cli.context_entities import (
    organization_label,
    project_label,
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
    if not isinstance(response, dict):
        raise click.ClickException("Unexpected organizations response.")
    organizations = response.get("organizations")
    if not isinstance(organizations, list):
        raise click.ClickException("Unexpected organizations response.")

    for organization in organizations:
        if not isinstance(organization, dict):
            raise click.ClickException("Unexpected organizations response.")
        organization_id = organization.get("organization_id")
        detail = organization.get("detail")
        if (
            not isinstance(organization_id, str)
            or not isinstance(detail, dict)
            or not isinstance(detail.get("name"), str)
        ):
            raise click.ClickException("Unexpected organizations response.")
    return organizations


def fetch_projects(client: Any, organization_id: str) -> list[dict[str, Any]]:
    response = client.request(
        "GET",
        "/projects",
        params={"organization_id": organization_id},
    )
    if not isinstance(response, dict):
        raise click.ClickException("Unexpected projects response.")
    projects = response.get("projects")
    if not isinstance(projects, list):
        raise click.ClickException("Unexpected projects response.")

    for project in projects:
        if not isinstance(project, dict):
            raise click.ClickException("Unexpected projects response.")
        if (
            not isinstance(project.get("project_id"), str)
            or not isinstance(project.get("project_name"), str)
        ):
            raise click.ClickException("Unexpected projects response.")
    return projects


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
        organization_matches = [
            organization
            for organization in fetch_organizations(client)
            if organization["detail"]["name"].casefold()
            == organization_name.casefold()
        ]
        if len(organization_matches) > 1:
            raise click.ClickException(
                f"Multiple organizations named {organization_name!r}; pass the ID instead."
            )
        if not organization_matches:
            raise click.ClickException(
                f"No organization named {organization_name!r} was found."
            )
        org = organization_matches[0]
        organization_id = org["organization_id"]
    elif not organization_id:
        organization_id = env_org_id or _str_or_none(saved.get("organization_id"))

    if project_name:
        if organization_id:
            projects = fetch_projects(client, organization_id)
            project_matches = [
                candidate
                for candidate in projects
                if candidate["project_name"].casefold() == project_name.casefold()
            ]
            if len(project_matches) > 1:
                raise click.ClickException(
                    f"Multiple projects named {project_name!r}; pass the ID instead."
                )
            if not project_matches:
                raise click.ClickException(
                    f"No project named {project_name!r} was found."
                )
            project = project_matches[0]
            project_id = project["project_id"]
        else:
            org, project = _find_project_across_organizations(
                client,
                project_name=project_name,
            )
            organization_id = org["organization_id"]
            project_id = project["project_id"]
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
        organization_id = org["organization_id"]
        project_id = project["project_id"]

    if not organization_id:
        organizations = fetch_organizations(client)
        if len(organizations) == 1:
            org = organizations[0]
            organization_id = org["organization_id"]
        else:
            raise click.ClickException(_organization_help(organizations))

    if not require_project:
        return context_store.ActiveContext(
            organization_id=organization_id,
            organization_name=(org["detail"]["name"] if org else None)
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
                project_id = project["project_id"]
            else:
                raise click.ClickException(_project_help(projects, organization_id))

    return context_store.ActiveContext(
        organization_id=organization_id,
        project_id=project_id,
        organization_name=(org["detail"]["name"] if org else None)
        or _saved_name(saved, "organization", organization_id),
        project_name=(project["project_name"] if project else None)
        or _saved_name(saved, "project", project_id),
    )


def _find_project_across_organizations(
    client: Any,
    *,
    project_id: str | None = None,
    project_name: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for organization in fetch_organizations(client):
        oid = organization["organization_id"]
        for project in fetch_projects(client, oid):
            if project_id and project["project_id"] == project_id:
                matches.append((organization, project))
            elif (
                project_name
                and project["project_name"].casefold() == project_name.casefold()
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
        "or set JUDGMENT_PROJECT_ID.\n\nProjects:\n"
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
