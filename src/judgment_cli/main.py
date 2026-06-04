"""Entry point for the Judgment CLI."""

from __future__ import annotations

import click

from judgment_cli import __version__
from judgment_cli.client import JudgmentClient
from judgment_cli import config
from judgment_cli import credentials
from judgment_cli.generated_commands import register_commands
from judgment_cli.oauth import browser_login
from judgment_cli.ui import mask_key


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

    click.echo("Credential resolution (highest priority first):\n")

    import os
    sources = [
        ("Env", "JUDGMENT_API_KEY", os.environ.get("JUDGMENT_API_KEY", "")),
        ("Env", "JUDGMENT_BASE_URL", os.environ.get("JUDGMENT_BASE_URL", "")),
        ("Env", "JUDGMENT_AUTH_URL", os.environ.get("JUDGMENT_AUTH_URL", "")),
        ("Config", str(config.credentials_path()), ""),
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
        elif val:
            display = mask_key(val) if "KEY" in name else val
            click.echo(f"  {kind:6s}  {name} = {display}")
        else:
            click.echo(f"  {kind:6s}  {name}  (not set)")


register_commands(cli)

# Hand-written commands attach themselves to the auto-generated groups when
# imported (see judgment_cli/judges.py). Importing for side effects only.
from judgment_cli import judges  # noqa: E402, F401


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
