"""Entry point for the Judgment CLI."""

from __future__ import annotations

import click

from judgment_cli import __version__
from judgment_cli.client import JudgmentClient
from judgment_cli import config
from judgment_cli.generated_commands import register_commands, traces_group
from judgment_cli.commands import register_manual_commands


@click.group()
@click.option(
    "--base-url",
    default=None,
    help="Judgment API base URL (env: JUDGMENT_BASE_URL).",
)
@click.option(
    "--api-key",
    default=None,
    help="API key for authentication (env: JUDGMENT_API_KEY).",
)
@click.option(
    "--org-id",
    default=None,
    help="Organization ID (env: JUDGMENT_ORG_ID).",
)
@click.version_option(version=__version__, prog_name="judgment")
@click.pass_context
def cli(ctx: click.Context, base_url: str | None, api_key: str | None, org_id: str | None) -> None:
    """Judgment CLI — interact with the Judgment API from the command line."""
    ctx.ensure_object(dict)
    resolved_url, resolved_key, resolved_org = config.resolve(
        flag_base_url=base_url,
        flag_api_key=api_key,
        flag_org_id=org_id,
    )
    ctx.obj["client"] = JudgmentClient(
        base_url=resolved_url.rstrip("/"),
        api_key=resolved_key,
        organization_id=resolved_org,
    )


# ── login / logout / status ────────────────────────────────────────────


@cli.command()
@click.option("--api-key", prompt="API key", hide_input=True, help="Your Judgment API key.")
@click.option("--org-id", prompt="Organization ID (leave blank to skip)", default="", help="Organization ID.")
@click.option("--base-url", default=None, help="Custom API base URL.")
def login(api_key: str, org_id: str, base_url: str | None) -> None:
    """Authenticate and store credentials locally."""
    path = config.save(
        api_key=api_key,
        org_id=org_id or None,
        base_url=base_url,
    )
    click.echo(f"Credentials saved to {path}")
    click.echo(f"API key: {config.mask_key(api_key)}")
    if org_id:
        click.echo(f"Org ID:  {org_id}")


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

    click.echo("Credential resolution (highest priority first):\n")

    import os
    sources = [
        ("Flag", "--api-key / --base-url / --org-id", "(passed at invocation)"),
        ("Env", "JUDGMENT_API_KEY", os.environ.get("JUDGMENT_API_KEY", "")),
        ("Env", "JUDGMENT_BASE_URL", os.environ.get("JUDGMENT_BASE_URL", "")),
        ("Env", "JUDGMENT_ORG_ID", os.environ.get("JUDGMENT_ORG_ID", "")),
        ("Config", str(config._config_path()), ""),
    ]
    for kind, name, val in sources:
        if kind == "Config":
            if cfg:
                click.echo(f"  {kind:6s}  {name}")
                for k, v in cfg.items():
                    display = config.mask_key(v) if "key" in k else v
                    click.echo(f"          {k}: {display}")
            else:
                click.echo(f"  {kind:6s}  {name}  (not found)")
        elif val:
            display = config.mask_key(val) if "KEY" in name else val
            click.echo(f"  {kind:6s}  {name} = {display}")
        else:
            click.echo(f"  {kind:6s}  {name}  (not set)")


register_commands(cli)
register_manual_commands({"traces": traces_group})


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
