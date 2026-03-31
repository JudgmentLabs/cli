"""Hand-written CLI commands that aren't auto-generated."""

from judgment_cli.commands.traces import register_trace_commands


def register_manual_commands(cli_groups: dict) -> None:
    """Register all hand-written commands on their respective groups."""
    register_trace_commands(cli_groups["traces"])
