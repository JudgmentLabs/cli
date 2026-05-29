"""Natural-language command generation for the Judgment CLI."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import click
import httpx

from judgment_cli import config


_COMMAND_CONTEXT_SETTINGS = {
    "ignore_unknown_options": True,
    "allow_extra_args": True,
}

_LITELLM_MODELS_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/"
    "refs/heads/main/model_prices_and_context_window.json"
)

_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5.2",
        "litellm_provider": "openai",
    },
}

_SYSTEM_PROMPT = """You are the natural-language command router for the Judgment CLI.
Respond with ONLY the command. No explanation, no markdown, no backticks, no commentary. Just the raw command.

Rules:
- Output exactly one shell command line.
- The command must use the local `judgment` CLI. Do not use curl or direct HTTP.
- You may use shell pipes, loops, command substitution, and Python standard-library one-liners to combine multiple `judgment` commands and parse `-o json` output.
- When the user asks for an answer that requires counting, sorting, ranking, filtering, or joining across multiple Judgment resources, generate a pipeline/composed command that computes and prints the answer. Do not stop at a broad list command.
- Prefer `judgment ... -o json | python3 -c '...'` for non-trivial parsing because Python is more portable than jq. Use `json`, `sys`, and `subprocess` from the standard library.
- Prefer read-only Judgment commands (`list`, `search`, `get`, `spans`, `tags`, `behaviors`) unless the user explicitly asks to create, update, delete, tag, or evaluate something.
- Do not invent organization IDs, project IDs, trace IDs, judge IDs, prompt names, or behavior IDs.
- If a required ID is available in the environment context, use the corresponding shell variable in the command, such as "$JUDGMENT_ORG_ID" or "$JUDGMENT_PROJECT_ID".
- If account context names a likely organization, use that organization ID when the user did not specify one.
- For read-only project-scoped requests where the user did not specify a project, use the account context's recommended read-only project, which is the project with the most traces in the likely organization.
- If no usable organization/project IDs are available in environment or account context, compose a command that discovers them first: choose the organization with the largest `detail.projects[0].count`, then the project in that organization with the largest `total_traces`.
- For mutating project-scoped requests, do not assume a project unless the user explicitly specifies one or the environment provides `JUDGMENT_PROJECT_ID`.
- If a required ID is not available and cannot be safely discovered in a composed read-only command, generate the best Judgment discovery command instead, such as `judgment organizations list`.
- Quote JSON arguments with single quotes so they survive the shell.
- For trace duration filters, Judgment uses nanoseconds. 1 second = 1000000000 nanoseconds.
- For `judgment traces search`, always include `--pagination '{"limit":25,"cursorSortValue":null,"cursorItemId":null}'` unless the user asks for another limit.
- For "long" or "slow" traces, use `duration` with a numeric comparison and sort by duration descending when a narrow time range is available.
- Any `traces search` sort other than `created_at` descending needs `--time-range` with `start_time` and a window of at most 7 days.
- If output is piped or parsed, include `-o json`.
"""


@dataclass(frozen=True)
class LiteLLMModel:
    model_id: str
    provider: str
    mode: str
    input_cost: float | None = None
    output_cost: float | None = None
    context_tokens: int | None = None


@dataclass(frozen=True)
class ProjectCandidate:
    organization_id: str
    organization_name: str
    project_id: str
    project_name: str
    total_traces: int
    is_production: bool


@click.group("ai")
def ai_group() -> None:
    """AI-powered Judgment CLI tools."""


@ai_group.command("x", context_settings=_COMMAND_CONTEXT_SETTINGS)
@click.argument("prompt", nargs=-1, required=True, type=click.UNPROCESSED)
@click.pass_context
def ai_x(ctx: click.Context, prompt: tuple[str, ...]) -> None:
    """Generate and run a Judgment CLI command from natural language."""
    generate_command(" ".join(prompt), root_command=ctx.find_root().command)


@ai_group.command("configure")
def ai_configure() -> None:
    """Set up the OpenAI-compatible LLM used by natural-language commands."""
    configure_llm()


@ai_group.command("models")
@click.option("--provider", default=None, help="Filter by LiteLLM provider, e.g. openai.")
@click.option("--search", "search_term", default=None, help="Filter model IDs by text.")
@click.option("--limit", default=40, show_default=True, type=int, help="Maximum models to show.")
def ai_models(provider: str | None, search_term: str | None, limit: int) -> None:
    """Browse available LLM models from LiteLLM."""
    browse_models(provider=provider, search_term=search_term, limit=limit)


@click.command("x", context_settings=_COMMAND_CONTEXT_SETTINGS)
@click.argument("prompt", nargs=-1, required=True, type=click.UNPROCESSED)
@click.pass_context
def x_command(ctx: click.Context, prompt: tuple[str, ...]) -> None:
    """AI Judgment command (shortcut for 'ai x')."""
    generate_command(" ".join(prompt), root_command=ctx.find_root().command)


def register_ai_commands(cli: click.Group) -> None:
    """Register AI commands on the root CLI."""
    cli.add_command(ai_group, "ai")
    cli.add_command(x_command, "x")


def configure_llm() -> None:
    """Interactive LLM configuration, modeled after ahh's AI setup flow."""
    while True:
        cfg = config.load()
        auto_execute = _as_bool(cfg.get("llm_auto_execute", False))

        _print_llm_config(cfg)

        action = _select_menu(
            "LLM Configuration",
            [
                ("Quick Setup (from presets)", "PRESET"),
                ("Browse Models", "MODELS"),
                ("Set Base URL", "BASE_URL"),
                ("Set API Key", "KEY"),
                ("Set Model", "MODEL"),
                (
                    f"Toggle Auto-Execute (currently {'ON' if auto_execute else 'off'})",
                    "AUTO_EXEC",
                ),
                ("Exit", "EXIT"),
            ],
        )

        if action == "PRESET":
            provider = _select_menu(
                "Provider",
                [
                    (
                        f"{name} ({preset['base_url']})",
                        name,
                    )
                    for name, preset in _PROVIDER_PRESETS.items()
                ],
            )
            preset = _PROVIDER_PRESETS[provider]
            base_url = preset["base_url"]
            default_model = preset["default_model"]
            api_key = click.prompt("API key", hide_input=True)
            model = _pick_model(
                provider=preset["litellm_provider"],
                default=default_model,
            )
            config.update_llm(base_url=base_url, api_key=api_key, model=model)
            click.echo(
                click.style(f"Configured {provider} with model {model}.", fg="green")
            )
        elif action == "MODELS":
            provider = _current_provider(cfg)
            browse_models(provider=provider, search_term=None, limit=40)
        elif action == "BASE_URL":
            base_url = click.prompt(
                "OpenAI-compatible base URL",
                default=str(cfg.get("llm_base_url") or "https://api.openai.com/v1"),
            )
            if not base_url.startswith(("http://", "https://")):
                click.echo(
                    click.style(
                        "Base URL must start with http:// or https://.",
                        fg="red",
                    )
                )
                continue
            config.update_llm(base_url=base_url)
            click.echo(click.style(f"Set base URL to {base_url}.", fg="green"))
        elif action == "KEY":
            api_key = click.prompt("API key", hide_input=True)
            config.update_llm(api_key=api_key)
            click.echo(click.style("Saved API key.", fg="green"))
        elif action == "MODEL":
            model = _pick_model(
                provider=_current_provider(cfg),
                default=str(cfg.get("llm_model") or "gpt-5.2"),
            )
            config.update_llm(model=model)
            click.echo(click.style(f"Set model to {model}.", fg="green"))
        elif action == "AUTO_EXEC":
            new_value = not auto_execute
            if new_value:
                click.echo(
                    click.style(
                        "\nWarning: Auto-execute will run generated commands without confirmation.",
                        fg="red",
                    )
                )
                if not click.confirm("Are you sure?", default=False):
                    continue
            config.update_llm(auto_execute=new_value)
            click.echo(
                click.style(
                    f"Auto-execute {'enabled' if new_value else 'disabled'}.",
                    fg="red" if new_value else "green",
                )
            )
        else:
            return


def _print_llm_config(cfg: dict[str, Any]) -> None:
    from rich.console import Console
    from rich.table import Table

    auto_execute = _as_bool(cfg.get("llm_auto_execute", False))
    table = Table.grid(padding=(0, 2))
    table.add_column(style="yellow")
    table.add_column()
    table.add_row("Base URL", str(cfg.get("llm_base_url") or "not set"))
    table.add_row(
        "API Key",
        click.style("configured", fg="green")
        if cfg.get("llm_api_key")
        else click.style("not set", fg="yellow"),
    )
    table.add_row("Model", str(cfg.get("llm_model") or "not set"))
    table.add_row(
        "Auto-execute",
        click.style("ON", fg="red")
        if auto_execute
        else click.style("off", fg="green"),
    )
    click.echo()
    click.echo(click.style("LLM Configuration:", fg="blue"))
    Console().print(table)
    click.echo()


def _select_menu(
    message: str,
    choices: list[tuple[str, str]],
    *,
    default_index: int = 0,
) -> str:
    if not choices:
        raise click.ClickException("No choices available.")

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return _numeric_select(message, choices, default_index=default_index)

    try:
        return _tty_select(message, choices, default_index=default_index)
    except (ImportError, OSError, AttributeError):
        return _numeric_select(message, choices, default_index=default_index)


def _numeric_select(
    message: str,
    choices: list[tuple[str, str]],
    *,
    default_index: int,
) -> str:
    click.echo(click.style(f"? {message}", fg="blue"))
    for index, (name, _) in enumerate(choices, start=1):
        click.echo(f"  {index}. {name}")
    value = click.prompt(
        "Choose",
        type=click.IntRange(1, len(choices)),
        default=default_index + 1,
        show_choices=False,
    )
    return choices[value - 1][1]


def _tty_select(
    message: str,
    choices: list[tuple[str, str]],
    *,
    default_index: int,
) -> str:
    import termios
    import tty

    selected = max(0, min(default_index, len(choices) - 1))
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    rendered_lines = 0
    restored = False

    def restore_terminal() -> None:
        nonlocal restored
        if restored:
            return
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()
        restored = True

    def render() -> None:
        nonlocal rendered_lines
        if rendered_lines:
            sys.stdout.write(f"\x1b[{rendered_lines}F\x1b[J")

        hint = click.style("(Use arrow keys)", dim=True)
        lines = [f"{click.style('?', fg='blue')} {message} {hint}"]
        for index, (name, _) in enumerate(choices):
            prefix = "❯" if index == selected else " "
            text = click.style(name, fg="cyan") if index == selected else name
            lines.append(f"{prefix} {text}")

        sys.stdout.write("\n".join(lines))
        sys.stdout.write("\n")
        sys.stdout.flush()
        rendered_lines = len(lines)

    def read_key() -> str:
        char = sys.stdin.read(1)
        if char in ("\r", "\n"):
            return "enter"
        if char == "\x03":
            raise KeyboardInterrupt
        if char == "\x04":
            raise EOFError
        if char == "\x1b":
            seq = sys.stdin.read(2)
            if seq == "[A":
                return "up"
            if seq == "[B":
                return "down"
        return char

    try:
        sys.stdout.write("\x1b[?25l")
        tty.setcbreak(fd)
        while True:
            render()
            key = read_key()
            if key == "up":
                selected = (selected - 1) % len(choices)
            elif key == "down":
                selected = (selected + 1) % len(choices)
            elif key == "enter":
                name, value = choices[selected]
                if rendered_lines:
                    sys.stdout.write(f"\x1b[{rendered_lines}F\x1b[J")
                restore_terminal()
                click.echo(f"? {message} {click.style(name, fg='cyan')}")
                return value
    except KeyboardInterrupt:
        raise click.exceptions.Exit(0)
    except EOFError:
        raise click.exceptions.Exit(0)
    finally:
        restore_terminal()


def browse_models(
    *,
    provider: str | None,
    search_term: str | None,
    limit: int,
) -> None:
    with _spinner("Fetching models"):
        models = _fetch_litellm_models()

    matches = _filter_models(models, provider=provider, search_term=search_term)
    if not matches:
        click.echo(click.style("No matching models found.", fg="yellow"))
        return

    _print_model_table(matches, limit=max(1, limit))
    if len(matches) > limit:
        click.echo(
            click.style(
                f"\nShowing {limit} of {len(matches)} models. Use --search to narrow.",
                fg="yellow",
            )
        )


def _pick_model(*, provider: str | None, default: str) -> str:
    try:
        with _spinner("Fetching models"):
            models = _fetch_litellm_models()
    except click.ClickException as exc:
        click.echo(click.style(f"Could not fetch models: {exc.message}", fg="yellow"))
        return click.prompt("Model", default=default)

    search_term = default
    while True:
        matches = _filter_models(models, provider=provider, search_term=search_term)
        if not matches and search_term:
            click.echo(click.style(f"No models matched '{search_term}'.", fg="yellow"))
            search_term = ""
            continue
        if not matches:
            return click.prompt("Model", default=default)

        visible = matches[:20]
        choices = [
            (_model_choice_label(model), model.model_id)
            for model in visible
        ]
        if len(matches) > len(visible):
            choices.append(
                (
                    f"Search again ({len(matches) - len(visible)} more matches)",
                    "__SEARCH__",
                )
            )
        choices.append(("Type or paste model ID", "__CUSTOM__"))

        choice = _select_menu(f"Select Model ({len(matches)} matches)", choices)

        if choice == "__SEARCH__":
            search_term = click.prompt("Search models", default="", show_default=False)
            continue
        if choice == "__CUSTOM__":
            return click.prompt("Model", default=default)
        return choice


def _current_provider(cfg: dict[str, Any]) -> str | None:
    base_url = cfg.get("llm_base_url")
    for preset in _PROVIDER_PRESETS.values():
        if preset["base_url"] == base_url:
            return preset["litellm_provider"]
    return None


def _fetch_litellm_models() -> list[LiteLLMModel]:
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            response = client.get(_LITELLM_MODELS_URL)
    except httpx.RequestError as exc:
        raise click.ClickException(f"model registry connection failed ({exc})") from exc

    if response.status_code >= 400:
        raise click.ClickException(
            f"model registry request failed ({response.status_code})"
        )

    try:
        raw = response.json()
    except Exception as exc:
        raise click.ClickException("model registry response was not JSON") from exc

    if not isinstance(raw, dict):
        raise click.ClickException("model registry response had an unexpected shape")

    models: list[LiteLLMModel] = []
    for model_id, data in raw.items():
        if model_id == "sample_spec" or not isinstance(data, dict):
            continue
        mode = str(data.get("mode") or "chat")
        context_tokens = _optional_int(
            data.get("max_input_tokens") or data.get("max_tokens")
        )
        models.append(
            LiteLLMModel(
                model_id=str(model_id),
                provider=str(data.get("litellm_provider") or "unknown"),
                mode=mode,
                input_cost=_optional_float(data.get("input_cost_per_token")),
                output_cost=_optional_float(data.get("output_cost_per_token")),
                context_tokens=context_tokens,
            )
        )
    return sorted(models, key=lambda m: (m.provider, m.model_id))


def _filter_models(
    models: list[LiteLLMModel],
    *,
    provider: str | None,
    search_term: str | None,
) -> list[LiteLLMModel]:
    search = (search_term or "").strip().lower()
    matches = [
        m
        for m in models
        if (not provider or m.provider == provider)
        and (not m.mode or m.mode == "chat")
        and (
            not search
            or search in m.model_id.lower()
            or search in m.provider.lower()
        )
    ]
    return matches


def _print_model_table(models: list[LiteLLMModel], *, limit: int) -> None:
    from rich.console import Console
    from rich.table import Table
    import rich.box

    table = Table(
        show_header=True,
        header_style="bold cyan",
        box=rich.box.SIMPLE,
    )
    table.add_column("#", justify="right", style="yellow")
    table.add_column("Model", overflow="fold", max_width=44)
    table.add_column("Provider", style="cyan")
    table.add_column("Input")
    table.add_column("Output")
    table.add_column("Context", justify="right")

    for index, model in enumerate(models[:limit], start=1):
        table.add_row(
            str(index),
            model.model_id,
            model.provider,
            _format_cost(model.input_cost),
            _format_cost(model.output_cost),
            _format_tokens(model.context_tokens),
        )

    Console().print(table)


def _model_choice_label(model: LiteLLMModel) -> str:
    model_id = textwrap.shorten(model.model_id, width=44, placeholder="~")
    return (
        f"{model_id:<44}  "
        f"{model.provider:<12}  "
        f"in {_format_cost(model.input_cost):>10}  "
        f"out {_format_cost(model.output_cost):>10}  "
        f"ctx {_format_tokens(model.context_tokens):>6}"
    )


def _format_cost(cost: float | None) -> str:
    if cost is None:
        return "-"
    if cost == 0:
        return "Free"
    if cost < 0.000001:
        return f"${cost:.2e}"
    return f"${cost:.6f}"


def _format_tokens(tokens: int | None) -> str:
    if tokens is None:
        return "-"
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.0f}K"
    return str(tokens)


def generate_command(prompt: str, *, root_command: click.Command) -> None:
    llm = config.resolve_llm()
    if llm is None:
        click.echo(
            click.style(
                "No LLM configured. Run 'judgment ai configure' to set up.",
                fg="yellow",
            )
        )
        raise click.exceptions.Exit(1)

    click.echo(f"{click.style(llm.base_url, fg='cyan')} {click.style(llm.model, fg='yellow')}")

    account_context = _build_account_context(prompt)

    with _spinner("Thinking"):
        command = _request_command(
            llm,
            prompt,
            root_command=root_command,
            account_context=account_context,
        )

    command = _normalize_command(command)
    if not command:
        click.echo(click.style("No command generated.", fg="yellow"))
        return
    _ensure_judgment_command(command)

    click.echo(f"\n{click.style('$', fg='green')} {click.style(command, fg='cyan')}\n")

    if llm.auto_execute:
        _execute_command(command)
        return

    action = _select_action()
    if action == "run":
        _execute_command(command)
    elif action == "copy":
        if _copy_to_clipboard(command):
            click.echo(click.style("Copied to clipboard.", fg="green"))
        else:
            click.echo(click.style("No clipboard command is available on this system.", fg="yellow"))


def _request_command(
    llm: config.ResolvedLLM,
    prompt: str,
    *,
    root_command: click.Command,
    account_context: str,
) -> str:
    system_content = "\n\n".join(
        [
            _SYSTEM_PROMPT,
            "Environment:\n" + _build_environment_context(),
            "Judgment account context:\n" + account_context,
            "Judgment CLI reference:\n" + build_cli_context(root_command),
            "Judgment read-only JSON output reference:\n" + _build_output_context(),
            "Judgment command recipes:\n" + _build_recipe_context(),
        ]
    )
    payload = {
        "model": llm.model,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 512,
    }
    headers = {
        "Authorization": f"Bearer {llm.api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.post(
                f"{llm.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
    except httpx.RequestError as exc:
        raise click.ClickException(f"LLM connection failed ({exc})") from exc

    if response.status_code == 401 or response.status_code == 403:
        raise click.ClickException("LLM authentication failed.")
    if response.status_code >= 400:
        raise click.ClickException(
            f"LLM request failed ({response.status_code}): {_response_message(response)}"
        )

    try:
        data = response.json()
        content = data["choices"][0]["message"].get("content", "")
    except Exception as exc:
        raise click.ClickException("LLM response did not match the expected chat format.") from exc

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def build_cli_context(root_command: click.Command) -> str:
    """Return a compact, Judgment-specific command reference for the LLM."""
    if not isinstance(root_command, click.Group):
        return ""

    lines: list[str] = []
    for name, command in root_command.commands.items():
        if name in {"ai", "x", "completion"}:
            continue
        if isinstance(command, click.Group):
            lines.append(f"Group `judgment {name}`: {_clean_help(command.short_help)}")
            for sub_name, sub_command in command.commands.items():
                lines.append(_describe_command((name, sub_name), sub_command))
        else:
            lines.append(_describe_command((name,), command))
    return "\n".join(lines)


def _describe_command(path: tuple[str, ...], command: click.Command) -> str:
    usage = "judgment " + " ".join(path)
    option_parts: list[str] = []
    for param in command.params:
        if isinstance(param, click.Argument):
            usage += " " + _argument_usage(param)
        elif isinstance(param, click.Option) and not param.hidden:
            option_parts.append(_option_usage(param))

    if option_parts:
        usage += " " + " ".join(option_parts)

    help_text = _clean_help(command.help or command.short_help)
    if len(help_text) > 420:
        help_text = help_text[:417].rstrip() + "..."
    return f"- `{usage}`: {help_text}"


def _argument_usage(arg: click.Argument) -> str:
    name = arg.human_readable_name.upper()
    if arg.nargs == -1:
        return f"[{name}...]"
    if arg.required:
        return f"<{name}>"
    return f"[{name}]"


def _option_usage(opt: click.Option) -> str:
    flag = (opt.opts or [f"--{opt.name.replace('_', '-')}"])[0]
    value = _option_value_label(opt)
    if opt.is_bool_flag:
        rendered = flag
    elif opt.multiple:
        rendered = f"{flag} {value}..."
    else:
        rendered = f"{flag} {value}"
    if opt.required:
        return rendered
    return f"[{rendered}]"


def _option_value_label(opt: click.Option) -> str:
    if isinstance(opt.type, click.Choice):
        return "{" + "|".join(str(c) for c in opt.type.choices) + "}"
    if isinstance(opt.type, click.types.BoolParamType):
        return "{true|false}"
    if isinstance(opt.type, click.types.IntParamType):
        return "INT"
    if isinstance(opt.type, click.types.FloatParamType):
        return "NUMBER"
    return opt.name.upper().replace("-", "_")


def _clean_help(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.replace("\b", "").split())


def _build_environment_context() -> str:
    org_id = os.environ.get("JUDGMENT_ORG_ID")
    project_id = os.environ.get("JUDGMENT_PROJECT_ID")
    org_hint = 'set; use "$JUDGMENT_ORG_ID"' if org_id else "not set"
    project_hint = 'set; use "$JUDGMENT_PROJECT_ID"' if project_id else "not set"
    creds = config.resolve()
    parts = [
        f"OS: {sys.platform}",
        f"Shell: {os.environ.get('SHELL', 'unknown')}",
        f"CWD: {os.getcwd()}",
        f"Judgment API base URL: {creds.base_url}",
        f"Judgment API key configured: {'yes' if creds.api_key else 'no'}",
        f"JUDGMENT_ORG_ID: {org_hint}",
        f"JUDGMENT_PROJECT_ID: {project_hint}",
    ]
    return "\n".join(parts)


def _build_account_context(prompt: str) -> str:
    if not _should_load_account_context(prompt):
        return "Not loaded; the request does not appear to need organization or project inference."

    creds = config.resolve()
    if not creds.api_key:
        return "Not loaded; no Judgment API key is configured."

    env_org_id = os.environ.get("JUDGMENT_ORG_ID")
    env_project_id = os.environ.get("JUDGMENT_PROJECT_ID")

    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            organizations_payload = _judgment_get(client, creds, "/organizations")
            organizations = _extract_items(organizations_payload, "organizations", "data")
            project_candidates: list[ProjectCandidate] = []
            projects_by_org: dict[str, list[ProjectCandidate]] = {}

            for org in organizations:
                org_id = _first_text(org, ("organization_id", "org_id", "id"))
                if not org_id:
                    continue
                org_name = _organization_name(org) or org_id
                projects_payload = _judgment_get(
                    client,
                    creds,
                    "/projects",
                    params={"organization_id": org_id},
                )
                projects = _extract_items(projects_payload, "projects", "data")
                candidates = [
                    _project_candidate(org_id, org_name, project)
                    for project in projects
                ]
                candidates = [candidate for candidate in candidates if candidate]
                projects_by_org[org_id] = candidates
                project_candidates.extend(candidates)
    except Exception as exc:
        return f"Not loaded; Judgment API discovery failed: {exc}"

    if not projects_by_org:
        return "Loaded organizations, but no projects were found."

    org_id = env_org_id or _org_with_most_projects(projects_by_org)
    org_projects = projects_by_org.get(org_id, [])
    if not org_projects:
        org_id = _org_with_most_projects(projects_by_org)
        org_projects = projects_by_org.get(org_id, [])

    production_project = _production_project(org_projects)
    trace_heavy_project = _trace_heavy_project(org_projects)
    recommended_read_only = (
        _project_by_id(project_candidates, env_project_id)
        if env_project_id
        else trace_heavy_project or production_project
    )

    total_projects = sum(len(projects) for projects in projects_by_org.values())
    lines = [
        f"Organizations found: {len(projects_by_org)}",
        f"Projects found: {total_projects}",
        (
            f"Likely organization: {org_id}"
            + (" (from JUDGMENT_ORG_ID)" if env_org_id else " (most projects)")
        ),
    ]
    if recommended_read_only:
        reason = (
            "from JUDGMENT_PROJECT_ID"
            if env_project_id
            else "most traces in likely organization"
        )
        lines.append(
            "Recommended read-only project: "
            f"{recommended_read_only.project_id} "
            f"({recommended_read_only.project_name}, {reason}, "
            f"{recommended_read_only.total_traces} traces)"
        )
    if production_project and production_project != recommended_read_only:
        lines.append(
            "Production project candidate: "
            f"{production_project.project_id} "
            f"({production_project.project_name}, {production_project.total_traces} traces)"
        )
    if trace_heavy_project and trace_heavy_project != recommended_read_only:
        lines.append(
            "Most-traced project in likely organization: "
            f"{trace_heavy_project.project_id} "
            f"({trace_heavy_project.project_name}, {trace_heavy_project.total_traces} traces)"
        )

    top_projects = sorted(
        org_projects,
        key=lambda project: project.total_traces,
        reverse=True,
    )[:5]
    if top_projects:
        lines.append("Top projects in likely organization:")
        for project in top_projects:
            label = " production" if project.is_production else ""
            lines.append(
                f"- {project.project_id}: {project.project_name}; "
                f"{project.total_traces} traces;{label}".rstrip()
            )

    return "\n".join(lines)


def _should_load_account_context(prompt: str) -> bool:
    text = prompt.lower()
    keywords = (
        "trace",
        "traces",
        "span",
        "spans",
        "session",
        "sessions",
        "judge",
        "judges",
        "behavior",
        "behaviors",
        "automation",
        "automations",
        "prompt",
        "prompts",
        "project",
        "projects",
        "org",
        "orgs",
        "organization",
        "organizations",
    )
    return any(keyword in text for keyword in keywords)


def _judgment_get(
    client: httpx.Client,
    creds: config.ResolvedCredentials,
    path: str,
    *,
    params: dict[str, str] | None = None,
) -> object:
    headers: dict[str, str] = {}
    if creds.api_key:
        headers["Authorization"] = f"Bearer {creds.api_key}"
    response = client.get(
        f"{creds.base_url.rstrip('/')}{path}",
        headers=headers,
        params=params,
    )
    if response.status_code >= 400:
        raise click.ClickException(
            f"{path} returned {response.status_code}: {_response_message(response)}"
        )
    return response.json()


def _extract_items(payload: object, *preferred_keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in preferred_keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for value in payload.values():
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _project_candidate(
    organization_id: str,
    organization_name: str,
    project: dict[str, Any],
) -> ProjectCandidate | None:
    project_id = _first_text(project, ("project_id", "id"))
    if not project_id:
        return None
    project_name = (
        _first_text(project, ("project_name", "name", "slug"))
        or project_id
    )
    total_traces = _first_int(
        project,
        ("total_traces", "trace_count", "traces_count", "num_traces"),
    )
    return ProjectCandidate(
        organization_id=organization_id,
        organization_name=organization_name,
        project_id=project_id,
        project_name=project_name,
        total_traces=total_traces,
        is_production=_looks_like_production(project_name),
    )


def _organization_name(org: dict[str, Any]) -> str | None:
    name = _first_text(org, ("name", "organization_name", "slug"))
    if name:
        return name
    detail = org.get("detail")
    if isinstance(detail, dict):
        return _first_text(detail, ("name", "organization_name", "slug"))
    return None


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value):
            return str(value)
    return None


def _first_int(item: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        value = _optional_int(item.get(key))
        if value is not None:
            return value
    return 0


def _looks_like_production(name: str) -> bool:
    lowered = name.lower()
    tokens = lowered.replace("-", " ").replace("_", " ").split()
    return "production" in tokens or "prod" in tokens or lowered in {"production", "prod"}


def _org_with_most_projects(
    projects_by_org: dict[str, list[ProjectCandidate]],
) -> str:
    return max(
        projects_by_org,
        key=lambda org_id: len(projects_by_org.get(org_id, [])),
    )


def _production_project(
    projects: list[ProjectCandidate],
) -> ProjectCandidate | None:
    production = [project for project in projects if project.is_production]
    if not production:
        return None
    return max(production, key=lambda project: project.total_traces)


def _trace_heavy_project(
    projects: list[ProjectCandidate],
) -> ProjectCandidate | None:
    if not projects:
        return None
    return max(projects, key=lambda project: project.total_traces)


def _project_by_id(
    projects: list[ProjectCandidate],
    project_id: str | None,
) -> ProjectCandidate | None:
    if not project_id:
        return None
    return next((project for project in projects if project.project_id == project_id), None)


def _build_output_context() -> str:
    return textwrap.dedent(
        """
        General:
        - These shapes are derived from ../judgment-mono/services/cli-server and @judgment/shared return types.
        - With `-o json`, parse the raw JSON response. Table/YAML output is for humans.
        - Use the exact top-level keys below. If a command returns a bare array, the JSON root is an array. If a schema says `T|null`, handle JSON null.

        Organizations:
        - `judgment organizations list -o json` -> `{ "organizations": OrganizationMembership[] }`
        - `OrganizationMembership`: `{ "created_at": string, "onboarded": boolean, "organization_id": string, "role": "admin"|"developer"|"owner"|"viewer", "user_id": string, "detail": { "name": string, "created_at": string, "projects": [{"count": number}], "user_organizations": [{"count": number}] } }`
        - Organization display name is `organization["detail"]["name"]`. Project count is `organization["detail"]["projects"][0]["count"]` when present.

        Projects:
        - `judgment projects list ORGANIZATION_ID -o json` -> `{ "projects": ProjectSummary[] }`
        - `ProjectSummary`: `{ "organization_id": string|null, "project_id": string|null, "project_name": string|null, "first_name": string|null, "last_name": string|null, "updated_at": string|null, "total_datasets": number|null, "total_experiment_runs": number|null, "total_traces": number|null, "total_behaviors": number|null, "is_favorited": boolean }`

        Traces:
        - `judgment traces search ORG PROJECT ... -o json` -> `{ "data": TraceSearchRow[], "hasMore": boolean, "nextCursor": {"sort_value": string, "trace_id": string}|null }`
        - `TraceSearchRow`: `{ "organization_id": string, "project_id": string, "trace_id": string, "span_id": string, "created_at": string, "span_name": string|null, "customer_id": string|null, "customer_user_id": string|null, "session_id": string|null, "duration": string, "version_id": number, "input_preview": string, "output_preview": string, "error": string, "llm_cost": number, "tags": string[], "rules_invoked": string[], "behaviors": string[] }`
        - `judgment traces get ORG PROJECT TRACE_ID -o json` -> `TraceDetail|null`
        - `TraceDetail`: `{ "trace_id": string, "duration": number, "cumulative_llm_cost": number, "session_id": string|null }`
        - `judgment traces spans ORG PROJECT TRACE_ID -o json` -> `TraceSpanSummary[]`
        - `TraceSpanSummary`: `{ "organization_id": string, "project_id": string, "trace_id": string, "span_id": string, "resource_attributes": object, "timestamp": number, "duration": number|string, "span_kind": string|null, "span_name": string|null, "parent_span_id": string|null, "link_target_trace_id": string|null, "link_target_span_id": string|null, "link_source_trace_id": string|null, "link_source_span_id": string|null, "trace_state": string|null, "service_name": string|null, "status_code": number|string, "status_message": string|null, "events": object[]|string, "score_count": number }`
        - `judgment traces span ORG PROJECT --spans '[{"trace_id":"...","span_id":"..."}]' -o json` -> `(TraceSpanDetail|null)[]`
        - `TraceSpanDetail`: `TraceSpanSummary` plus `{ "span_attributes": object, "scores": SpanScore[] }`
        - `SpanScore`: `{ "span_id": string, "name": string, "score_type": "numeric"|"binary"|"categorical", "score": number, "bool_value": boolean, "str_value": string, "error": string|null, "reason": {"text": string, "citations"?: [{"span_id": string, "span_attribute": string}]}|null, "example_id": string|null }`
        - `judgment traces tags ORG PROJECT TRACE_ID -o json` -> `string[]`
        - `judgment traces behaviors ORG PROJECT TRACE_ID -o json` -> `TraceBehavior[]`
        - `TraceBehavior`: `{ "judge_name": string, "span_id": string, "value": string, "reason": {"text": string, "citations"?: [{"span_id": string, "span_attribute": string}]}|null, "score_type": string, "error": string|null, "categories": [{"id": string, "name": string, "color": string}] }`

        Sessions:
        - `judgment sessions search ORG PROJECT ... -o json` -> `{ "data": SessionSearchRow[], "hasMore": boolean, "nextCursor": {"sort_value": string, "session_id": string}|null }`
        - `SessionSearchRow`: `{ "organization_id": string, "project_id": string, "session_id": string, "first_timestamp": string, "last_end_timestamp": string, "trace_count": string, "latency_ns": string, "total_cost_usd": number, "total_input_tokens": string, "total_output_tokens": string, "behaviors": string[], "top_span_names": string[] }`
        - `judgment sessions get ORG PROJECT SESSION_ID -o json` -> `SessionInfo|null`
        - `SessionInfo`: `{ "session_id": string, "first_timestamp": string, "last_end_timestamp": string, "trace_count": string, "latency_ns": string, "total_cost_usd": number, "total_input_tokens": string, "total_output_tokens": string }`
        - `judgment sessions trace-ids ORG PROJECT SESSION_ID -o json` -> `{ "trace_ids": string[] }`
        - `judgment sessions trace-behaviors ORG PROJECT SESSION_ID -o json` -> `{ [behavior_id: string]: { "description": string|null, "trace_ids": string[] } }`

        Agent threads:
        - `judgment agent-threads list ORG PROJECT --agent-type TYPE AGENT_NAME -o json` -> `{ "threads": AgentThreadSummary[], "next_cursor": {"updated_at": string, "thread_id": string}|null }`
        - `AgentThreadSummary`: `{ "id": string, "owner_user_id"?: string|null, "agent_kind": "agent_search"|"rubric_builder"|"global_copilot"|"custom_agent", "agent_config_id": string, "agent": {"type": string, "name": string}, "title": string|null, "active_run_id": string|null, "active_run_status": "queued"|"running"|"completed"|"failed"|"cancelled"|null, "latest_run_id": string|null, "latest_run_status": "queued"|"running"|"completed"|"failed"|"cancelled"|null, "last_error": string|null, "attention": "requires_input"|null, "messages_count": number, "first_user_message": string|null, "created_at": string, "updated_at": string }`
        - `judgment agent-threads get ORG PROJECT THREAD_ID -o json` -> `AgentThreadDetail`
        - `AgentThreadDetail`: `{ "id": string, "is_owner": boolean, "owner_user_id"?: string|null, "agent_kind": string, "agent_config_id": string, "agent": {"type": string, "name": string}, "title": string|null, "messages": AgentMessage[], "metadata": object, "active_run_id": string|null, "active_run_status": string|null, "latest_run_id": string|null, "latest_run_status": string|null, "last_error": string|null, "created_at": string, "updated_at": string }`
        - `AgentMessage`: `{ "role": "user"|"assistant", "content": string, "agent_mode"?: "fast"|"deep_research", "badges"?: [{"type": string, "id": string, "name": string}], "interaction_responses"?: object[], "assistant_progress"?: object, "ui_items"?: object[], "parts"?: object[], "has_completed": boolean, "has_stream_error": boolean }`

        Automations:
        - `judgment automations list ORG PROJECT -o json` -> `{ "automations": Automation[] }`
        - `judgment automations get ORG PROJECT RULE_ID -o json` -> `{ "automation": Automation }`
        - `Automation`: `{ "rule_id": string, "project_id": string, "name": string, "description": string|null, "conditions": Condition[], "combine_type": "all"|"any"|null, "actions": Actions|null, "cooldown_period": [number, "seconds"|"minutes"|"hours"|"days"], "trigger_frequency": [number, number, "seconds"|"minutes"|"hours"|"days"], "active": boolean, "created_at": string, "updated_at": string|null }`
        - `Condition`: `{ "metric": {"scorer_type": "static"|"prompt"|"custom"|"judge"|"behavior"|"span_attribute"|"error"|"note"|"vote"|"review_session", "threshold"?: number|string|null, "name": string}, "comparison": "lt"|"gt"|"eq"|"gte"|"lte"|"fails"|"succeeds"|"chooses"|"detected"|"equals"|"contains"|"exists" }`

        Behaviors:
        - `judgment behaviors list ORG PROJECT -o json` -> `{ "behaviors": BehaviorWithStats[] }`
        - `judgment behaviors get ORG PROJECT BEHAVIOR_ID -o json` -> `{ "behavior": BehaviorWithScorer }`
        - `BehaviorWithStats`: `{ "id": string, "created_at": string, "organization_id": string, "project_id": string, "judge_name": string, "value": string, "description": string|null, "judge_id": string, "score_type": string, "categories": [{"id": string, "name": string, "color": string}], "stats": {"trace_count": number, "distribution_rate": number|null, "last_seen": string|null, "daily_counts": number[]} }`
        - `BehaviorWithScorer`: `BehaviorWithStats` plus `{ "judge": BehaviorJudge|null, "judge_siblings"?: [{"id": string, "value": string}] }`
        - `BehaviorJudge`: `{ "id": string, "name": string, "judge_type": string, "score_type": string, "prompt": string|null, "categories"?: [{"name": string, "description": string}]|null, "min_score": number, "max_score": number, "evaluation_mode": string, "sampling_rate": number, "span_triggers": SpanTrigger[], "session_scoring": boolean }`

        Judges:
        - `judgment judges list ORG PROJECT -o json` -> `{ "judges": Judge[] }`
        - `judgment judges get ORG PROJECT JUDGE_ID -o json` -> `{ "judge": JudgeDetail }`
        - `judgment judges get-settings ORG PROJECT JUDGE_ID -o json` -> `{ "evaluation_mode": string, "sampling_rate": number, "span_triggers": SpanTrigger[], "session_scoring": boolean }`
        - `judgment judges models ORG -o json` -> `{ "models": [{"id": string, "provider": string}] }`
        - `Judge`: `{ "id": string, "name": string, "judge_description": string|null, "method": "LLM"|"Code"|"Agent", "output": string, "last_updated": string, "score_type": "numeric"|"binary"|"categorical", "behaviors": string[], "model"?: string|null, "prompt"?: string|null, "description"?: string|null, "categories"?: [{"name": string, "description": string}]|null, "min_score"?: number, "max_score"?: number, "major_version"?: number, "minor_version"?: number, "prod_version"?: {"major": number, "minor": number}|null, "code"?: string|null, "dependencies"?: string|null, "prompts"?: AgentPrompt[], "custom_scorer_id"?: string|null, "entrypoint_path"?: string|null, "requirements_path"?: string|null, "online_evaluation_mode"?: string, "online_sampling_rate"?: number, "online_span_triggers"?: SpanTrigger[], "online_session_scoring"?: boolean }`
        - `JudgeDetail`: `Judge` plus `{ "versions": ScorerVersion[] }`
        - `ScorerVersion`: `{ "major_version": number, "minor_version": number, "model": string|null, "prompt": string|null, "description": string|null, "categories"?: [{"name": string, "description": string}]|null, "min_score": number, "max_score": number, "tags": string[], "created_at": string, "prompts"?: AgentPrompt[], "custom_scorer_id"?: string }`
        - `AgentPrompt`: `{ "name": string, "description": string|null, "prompt": string, "position": number, "updated_at": string }`
        - `SpanTrigger`: `{ "field": "span_name"|"span_attribute", "operator": "contains"|"equals"|"exists", "value": string, "key"?: string }`

        Prompts:
        - `judgment prompts list ORG PROJECT -o json` -> `{ "prompts": [{"name": string, "last_version_created_at": string, "versions_count": number}] }`
        - `judgment prompts get ORG PROJECT PROMPT_NAME -o json` -> `{ "commit": PromptCommit }`
        - `judgment prompts versions ORG PROJECT PROMPT_NAME -o json` -> `{ "versions": PromptCommit[] }`
        - `PromptCommit`: `{ "name": string, "prompt": string, "tags": string[], "commit_id": string, "parent_commit_id": string|null, "created_at": string, "first_name": string, "last_name": string, "user_email": string }`

        Docs:
        - `judgment docs search QUERY -o json` -> `{ "results": [{"pageTitle": string, "heading": string|null, "path": string, "slug": string|null, "content": string, "url": string}] }`
        - `judgment docs get-page PATH -o json` -> `{ "path": string, "url": string, "content": string }`
        """
    ).strip()


def _build_recipe_context() -> str:
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    start = seven_days_ago.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    end = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    org_id = (
        "ORG_ID=$(judgment organizations list -o json | "
        "python3 -c 'import json,sys; "
        "orgs=json.load(sys.stdin).get(\"organizations\", []); "
        "count=lambda o: int(((((o.get(\"detail\") or {}).get(\"projects\") or [{}])[0]).get(\"count\")) or 0); "
        "org=max(orgs, key=count) if orgs else {}; "
        "print(org.get(\"organization_id\") or org.get(\"id\") or \"\")')"
    )
    project_id = (
        "PROJECT_ID=$(judgment projects list \"$ORG_ID\" -o json | "
        "python3 -c 'import json,sys; "
        "projects=json.load(sys.stdin).get(\"projects\", []); "
        "project=max(projects, key=lambda p: int(p.get(\"total_traces\") or 0)) if projects else {}; "
        "print(project.get(\"project_id\") or project.get(\"id\") or \"\")')"
    )
    infer_ids = f"{org_id}; {project_id}"
    return "\n".join(
        [
            "Find organizations: judgment organizations list",
            f"Find projects in the likely organization: {org_id}; judgment projects list \"$ORG_ID\"",
            (
                "Return the organization with the most projects: "
                "judgment organizations list -o json | "
                "python3 -c 'import json,sys; "
                "orgs=json.load(sys.stdin).get(\"organizations\", []); "
                "count=lambda o: int(((((o.get(\"detail\") or {}).get(\"projects\") or [{}])[0]).get(\"count\")) or 0); "
                "org=max(orgs, key=count) if orgs else {}; "
                "print(json.dumps({\"organization_id\": org.get(\"organization_id\") or org.get(\"id\"), "
                "\"name\": (org.get(\"detail\") or {}).get(\"name\"), \"project_count\": count(org)}, indent=2))'"
            ),
            (
                "Return the project with the most traces in the likely organization: "
                f"{org_id}; judgment projects list \"$ORG_ID\" -o json | "
                "python3 -c 'import json,sys; projects=json.load(sys.stdin).get(\"projects\", []); "
                "project=max(projects, key=lambda p: int(p.get(\"total_traces\") or 0)) if projects else {}; "
                "print(json.dumps({\"project_id\": project.get(\"project_id\") or project.get(\"id\"), "
                "\"name\": project.get(\"project_name\") or project.get(\"name\"), "
                "\"total_traces\": project.get(\"total_traces\")}, indent=2))'"
            ),
            (
                "Find long traces over 10 seconds in the likely project over the last 7 days: "
                f"{infer_ids}; judgment traces search \"$ORG_ID\" \"$PROJECT_ID\" "
                "--filters '[{\"field\":\"duration\",\"op\":\">\",\"value\":10000000000}]' "
                "--sort-by '{\"field\":\"duration\",\"direction\":\"desc\"}' "
                f"--time-range '{{\"start_time\":\"{start}\",\"end_time\":\"{end}\"}}' "
                "--pagination '{\"limit\":25,\"cursorSortValue\":null,\"cursorItemId\":null}'"
            ),
            (
                "Find traces with errors in the likely project: "
                f"{infer_ids}; judgment traces search \"$ORG_ID\" \"$PROJECT_ID\" "
                "--filters '[{\"field\":\"error\",\"op\":\"exists\",\"value\":\"\"}]' "
                "--pagination '{\"limit\":25,\"cursorSortValue\":null,\"cursorItemId\":null}'"
            ),
            f'Inspect a trace in the likely project: {infer_ids}; judgment traces get "$ORG_ID" "$PROJECT_ID" TRACE_ID',
            f'List spans for a trace in the likely project: {infer_ids}; judgment traces spans "$ORG_ID" "$PROJECT_ID" TRACE_ID',
            f'List judges in the likely project: {infer_ids}; judgment judges list "$ORG_ID" "$PROJECT_ID"',
            f'List behaviors in the likely project: {infer_ids}; judgment behaviors list "$ORG_ID" "$PROJECT_ID"',
            'Search docs: judgment docs search "QUERY"',
        ]
    )


def _normalize_command(command: str) -> str:
    command = command.strip()
    if command.startswith("```"):
        lines = [
            line
            for line in command.splitlines()
            if not line.strip().startswith("```")
        ]
        command = "\n".join(lines).strip()
    if command.startswith("$ "):
        command = command[2:].strip()
    return command.splitlines()[0].strip() if command else ""


def _ensure_judgment_command(command: str) -> None:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise click.ClickException(f"Generated command is not valid shell syntax: {exc}") from exc
    if not parts or not any("judgment" in part for part in parts):
        raise click.ClickException(
            "Generated command did not use the Judgment CLI; refusing to run it."
        )
    blocked_tokens = {
        "curl",
        "wget",
        "rm",
        "rmdir",
        "mv",
        "dd",
        "mkfs",
        "chmod",
        "chown",
        "sudo",
    }
    if any(part in blocked_tokens for part in parts):
        raise click.ClickException(
            "Generated command included a blocked shell command; refusing to run it."
        )


def _select_action() -> str:
    if not sys.stdin.isatty():
        click.echo(
            click.style(
                "Not running because stdin is non-interactive. Re-run in a terminal or enable auto-execute.",
                fg="yellow",
            )
        )
        return "cancel"

    return _select_menu(
        "Run this command?",
        [
            ("Run", "run"),
            ("Copy to clipboard", "copy"),
            ("Cancel", "cancel"),
        ],
    )


def _execute_command(command: str) -> None:
    click.echo()
    result = subprocess.run(command, shell=True)
    if result.returncode != 0:
        click.echo(click.style(f"\nExited with code {result.returncode}", fg="red"))


def _copy_to_clipboard(command: str) -> bool:
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        subprocess.run(["pbcopy"], input=command, text=True, check=False)
        return True
    if shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=command, text=True, check=False)
        return True
    if shutil.which("xclip"):
        subprocess.run(["xclip", "-selection", "clipboard"], input=command, text=True, check=False)
        return True
    return False


def _response_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except Exception:
        return response.text.strip() or response.reason_phrase
    if isinstance(data, dict):
        for key in ("message", "error", "detail"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict) and isinstance(value.get("message"), str):
                return value["message"]
    return response.text.strip() or response.reason_phrase


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@contextmanager
def _spinner(text: str) -> Iterator[None]:
    if not sys.stdout.isatty():
        click.echo(f"{text}...")
        yield
        return

    stop = threading.Event()
    frames = ["|", "/", "-", "\\"]

    def run() -> None:
        i = 0
        while not stop.is_set():
            sys.stdout.write(f"\r{frames[i]} {text}")
            sys.stdout.flush()
            i = (i + 1) % len(frames)
            time.sleep(0.08)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=0.2)
        sys.stdout.write("\r\x1b[K")
        sys.stdout.flush()
