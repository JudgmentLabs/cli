"""Entry point for the Judgment CLI."""

from __future__ import annotations

import click

from judgment_cli import __version__
from judgment_cli.client import JudgmentClient
from judgment_cli import config
from judgment_cli import context as context_store
from judgment_cli.context_entities import (
    active_context_from_items,
    display_name,
    organization_id as get_organization_id,
    organization_label,
    project_id as get_project_id,
    project_label,
)
from judgment_cli.context_resolver import (
    fetch_organizations,
    fetch_projects,
    resolve_context,
)
from judgment_cli import credentials
from judgment_cli.generated_commands import register_commands
from judgment_cli.oauth import browser_login
from judgment_cli.ui import mask_key, select_item


@click.group()
@click.version_option(version=__version__, prog_name="judgment")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Judgment CLI — interact with the Judgment API from the command line.

    Credentials are read from environment variables (JUDGMENT_API_KEY,
    JUDGMENT_BASE_URL, JUDGMENT_AUTH_URL) or the local config file written by
    `judgment login`. Environment variables take precedence over the config file.
    """
    ctx.ensure_object(dict)
    resolved = credentials.resolve()
    ctx.obj["client"] = JudgmentClient(
        base_url=resolved.base_url,
        credential=resolved.credential,
    )


# ── login / logout / status ────────────────────────────────────────────


@cli.command()
@click.option(
    "--api-key",
    "api_key_login",
    is_flag=True,
    help="Prompt for an API key instead of opening browser login.",
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Print the authorization URL instead of opening a browser.",
)
def login(api_key_login: bool, no_browser: bool) -> None:
    """Authenticate and store credentials locally."""
    auth_url = config.resolve_auth_url().rstrip("/")

    if api_key_login:
        api_key = click.prompt("API key", hide_input=True)
        path = config.save(api_key=api_key)
        click.echo(f"Credentials saved to {path}")
        click.echo(f"API key: {mask_key(api_key)}")
        return

    if no_browser:
        click.echo("Open this URL in your browser to finish logging in:")
    else:
        click.echo("Opening browser for Judgment login...")
    tokens = browser_login(
        auth_url=auth_url,
        open_browser=not no_browser,
        on_authorize_url=click.echo if no_browser else None,
    )
    path = config.save_oauth(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_at=tokens.expires_at,
    )
    click.echo(f"Credentials saved to {path}")
    click.echo("Logged in with browser OAuth.")


@cli.command()
def configure() -> None:
    """Update stored credentials interactively.

    Each prompt shows the current value in brackets — press Enter to keep it,
    or type a new value and press Enter to replace it.
    """
    cfg = config.load()
    api_key = _prompt_field("API key", cfg.get("api_key", ""), hide=True)

    path = config.save(api_key=api_key)
    click.echo(f"Credentials saved to {path}")


def _prompt_field(label: str, current: str, *, hide: bool = False) -> str:
    """Prompt for a single field, returning ``current`` if the user hits Enter."""
    display = (mask_key(current) if hide else current) or "None"
    new = click.prompt(
        f"{label} [{display}]",
        default="",
        show_default=False,
        hide_input=hide,
    )
    return new or current


@cli.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell: str) -> None:
    """Print a shell-completion script for SHELL.

    Eval the output from your shell's rc file:

    \b
      # bash (~/.bashrc)
      eval "$(judgment completion bash)"

    \b
      # zsh (~/.zshrc)
      eval "$(judgment completion zsh)"

    \b
      # fish (~/.config/fish/config.fish)
      judgment completion fish | source
    """
    from click.shell_completion import get_completion_class

    completer_cls = get_completion_class(shell)
    if completer_cls is None:
        raise click.UsageError(f"Shell '{shell}' is not supported.")
    completer = completer_cls(cli, {}, "judgment", "_JUDGMENT_COMPLETE")
    click.echo(completer.source())


@cli.command()
def logout() -> None:
    """Remove stored credentials."""
    if config.clear():
        click.echo("Credentials removed.")
    else:
        click.echo("No credentials found.")


@cli.command()
def status() -> None:
    """Show current authentication status and credential sources."""
    cfg = config.load()
    saved_context = context_store.load_context()

    click.echo("Credential resolution (highest priority first):\n")

    import os
    sources = [
        ("Env", "JUDGMENT_API_KEY", os.environ.get("JUDGMENT_API_KEY", "")),
        ("Env", "JUDGMENT_ORG_ID", os.environ.get("JUDGMENT_ORG_ID", "")),
        ("Env", "JUDGMENT_PROJECT_ID", os.environ.get("JUDGMENT_PROJECT_ID", "")),
        ("Env", "JUDGMENT_BASE_URL", os.environ.get("JUDGMENT_BASE_URL", "")),
        ("Env", "JUDGMENT_AUTH_URL", os.environ.get("JUDGMENT_AUTH_URL", "")),
        ("Config", str(config.credentials_path()), ""),
        ("Context", str(context_store.context_path()), ""),
    ]
    for kind, name, val in sources:
        if kind == "Config":
            if cfg:
                click.echo(f"  {kind:6s}  {name}")
                for k, v in cfg.items():
                    display = mask_key(str(v)) if "key" in k or "token" in k else v
                    click.echo(f"          {k}: {display}")
            else:
                click.echo(f"  {kind:6s}  {name}  (not found)")
        elif kind == "Context":
            if saved_context:
                click.echo(f"  {kind:6s}  {name}")
                for k, v in saved_context.items():
                    click.echo(f"          {k}: {v}")
            else:
                click.echo(f"  {kind:6s}  {name}  (not found)")
        elif val:
            display = mask_key(val) if "KEY" in name else val
            click.echo(f"  {kind:6s}  {name} = {display}")
        else:
            click.echo(f"  {kind:6s}  {name}  (not set)")


@cli.group("context")
def context_group() -> None:
    """Manage the default organization and project for commands."""


@context_group.command("set")
@click.option(
    "--organization-id",
    "--org-id",
    default=None,
    help="Organization ID to use.",
)
@click.option(
    "--organization",
    "--org",
    default=None,
    help="Organization name to use.",
)
@click.option("--project-id", default=None, help="Project ID to use.")
@click.option("--project", default=None, help="Project name to use.")
@click.pass_context
def context_set(
    ctx: click.Context,
    organization_id: str | None,
    organization: str | None,
    project_id: str | None,
    project: str | None,
) -> None:
    """Select and save the default organization and project."""
    client = ctx.obj["client"]

    if (project_id or project) and not (organization_id or organization):
        active = resolve_context(
            client,
            project_id=project_id,
            project_name=project,
            require_project=True,
        )
        path = context_store.save_context(active)
        _echo_active_context(active, path)
        return

    organizations = fetch_organizations(client)
    selected_org = _select_organization(organizations, organization_id, organization)
    selected_org_id = get_organization_id(selected_org)
    if not selected_org_id:
        raise click.ClickException("Selected organization is missing an ID.")

    projects = fetch_projects(client, selected_org_id)
    selected_project = _select_project(projects, project_id, project)

    active = active_context_from_items(selected_org, selected_project)
    path = context_store.save_context(active)
    _echo_active_context(active, path)


@context_group.command("show")
def context_show() -> None:
    """Show the saved default organization and project."""
    saved = context_store.load_context()
    if not saved:
        click.echo("No context saved. Run `judgment context set`.")
        return

    click.echo("Active context:")
    click.echo(f"  Organization: {_display_context_value(saved, 'organization')}")
    click.echo(f"  Project:      {_display_context_value(saved, 'project')}")


@context_group.command("clear")
def context_clear() -> None:
    """Clear the saved default organization and project."""
    if context_store.clear_context():
        click.echo("Context cleared.")
    else:
        click.echo("No context saved.")


def _select_organization(
    organizations: list[dict],
    organization_id: str | None,
    organization_name: str | None,
) -> dict:
    if organization_id:
        return _match_by_id(organizations, organization_id, "organization")
    if organization_name:
        return _match_by_name(organizations, organization_name, "organization")
    if not organizations:
        raise click.ClickException("No organizations were found for this account.")
    if len(organizations) == 1:
        selected = organizations[0]
        click.echo(f"Using organization: {organization_label(selected)}")
        return selected

    return select_item(
        "Organizations",
        organizations,
        label=organization_label,
    )


def _select_project(
    projects: list[dict],
    project_id: str | None,
    project_name: str | None,
) -> dict:
    if project_id:
        return _match_by_id(projects, project_id, "project")
    if project_name:
        return _match_by_name(projects, project_name, "project")
    if not projects:
        raise click.ClickException("No projects were found in this organization.")
    if len(projects) == 1:
        selected = projects[0]
        click.echo(f"Using project: {project_label(selected)}")
        return selected

    return select_item(
        "Projects (sorted by trace volume)",
        projects,
        label=project_label,
    )


def _match_by_id(items: list[dict], value: str, entity_name: str) -> dict:
    get_id = get_organization_id if entity_name == "organization" else get_project_id
    matches = [item for item in items if get_id(item) == value]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise click.ClickException(f"Multiple {entity_name}s matched ID {value!r}.")
    raise click.ClickException(f"No {entity_name} matched ID {value!r}.")


def _match_by_name(items: list[dict], value: str, entity_name: str) -> dict:
    matches = [
        item
        for item in items
        if (display_name(item) or "").casefold() == value.casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise click.ClickException(
            f"Multiple {entity_name}s named {value!r}; pass the ID instead."
        )
    raise click.ClickException(f"No {entity_name} named {value!r}.")


def _echo_active_context(active: context_store.ActiveContext, path) -> None:
    click.echo("Active context saved:")
    click.echo(
        f"  Organization: {_label_with_id(active.organization_name, active.organization_id)}"
    )
    if active.project_id:
        click.echo(
            f"  Project:      {_label_with_id(active.project_name, active.project_id)}"
        )
    click.echo(f"Saved to {path}")


def _display_context_value(saved: dict, prefix: str) -> str:
    name = saved.get(f"{prefix}_name")
    value_id = saved.get(f"{prefix}_id")
    return _label_with_id(
        name if isinstance(name, str) else None,
        str(value_id or ""),
    )


def _label_with_id(name: str | None, value_id: str) -> str:
    return f"{name} ({value_id})" if name else value_id


register_commands(cli)

# Hand-written commands attach themselves to the auto-generated groups when
# imported (see judgment_cli/judges.py). Importing for side effects only.
from judgment_cli import judges  # noqa: E402, F401


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
