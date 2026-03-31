"""Hand-written trace commands (search/filter).

Maps flat CLI flags into the POST /projects/{project_id}/traces/ request body,
which expects { filters, sort_by, time_range, pagination }.
"""

from __future__ import annotations

import json
import sys

import click


def _read_body(data_str: str | None, file_path: str | None) -> dict | None:
    if data_str is not None:
        if data_str == "-":
            return json.load(sys.stdin)
        return json.loads(data_str)
    if file_path is not None:
        with open(file_path) as f:
            return json.load(f)
    return None


def _add_filter(filters: list, field: str, op: str, value: object) -> None:
    filters.append({"field": field, "op": op, "value": value})


def register_trace_commands(traces_group: click.Group) -> None:
    @traces_group.command("list")
    @click.argument("project_id")
    # ── filters ──
    @click.option("--search", default=None, help="Full-text search across trace content.")
    @click.option("--span-name", default=None, help="Filter by root span name (exact match).")
    @click.option("--customer-id", default=None, help="Filter by customer ID.")
    @click.option("--session-id", default=None, help="Filter by session ID.")
    @click.option("--error", default=None, help="Filter by error message (contains).")
    @click.option("--tag", multiple=True, help="Filter by tag (repeatable).")
    @click.option("--dataset-id", default=None, help="Filter by dataset ID.")
    @click.option("--min-duration", type=float, default=None, help="Min duration (nanoseconds).")
    @click.option("--max-duration", type=float, default=None, help="Max duration (nanoseconds).")
    @click.option("--min-cost", type=float, default=None, help="Min LLM cost.")
    @click.option("--max-cost", type=float, default=None, help="Max LLM cost.")
    # ── sorting ──
    @click.option(
        "--sort-field",
        type=click.Choice(["created_at", "span_name", "duration", "llm_cost"]),
        default=None,
        help="Field to sort by.",
    )
    @click.option(
        "--sort-dir",
        type=click.Choice(["asc", "desc"]),
        default=None,
        help="Sort direction.",
    )
    # ── time range ──
    @click.option("--start-time", default=None, help="Start time (ISO 8601).")
    @click.option("--end-time", default=None, help="End time (ISO 8601).")
    # ── pagination ──
    @click.option("--limit", type=int, default=25, show_default=True, help="Max results to return.")
    @click.option("--cursor-sort-value", default=None, help="Pagination cursor sort value.")
    @click.option("--cursor-item-id", default=None, help="Pagination cursor item ID.")
    # ── raw body override ──
    @click.option("-d", "--data", "request_data", default=None,
                  help="Full JSON body (overrides all other options; use - for stdin).")
    @click.option("-f", "--file", "request_file", type=click.Path(exists=True), default=None,
                  help="Path to a JSON file for the request body.")
    @click.pass_context
    def traces_list(
        ctx,
        project_id,
        search,
        span_name,
        customer_id,
        session_id,
        error,
        tag,
        dataset_id,
        min_duration,
        max_duration,
        min_cost,
        max_cost,
        sort_field,
        sort_dir,
        start_time,
        end_time,
        limit,
        cursor_sort_value,
        cursor_item_id,
        request_data,
        request_file,
    ):
        """Search and filter traces in a project."""
        body = _read_body(request_data, request_file)
        if body is not None:
            result = ctx.obj["client"].request(
                "POST", f"/projects/{project_id}/traces/", json_body=body,
            )
            click.echo(json.dumps(result, indent=2, default=str))
            return

        filters: list[dict] = []

        if search is not None:
            _add_filter(filters, "full_text_search", "contains", search)
        if span_name is not None:
            _add_filter(filters, "span_name", "=", span_name)
        if customer_id is not None:
            _add_filter(filters, "customer_id", "=", customer_id)
        if session_id is not None:
            _add_filter(filters, "session_id", "=", session_id)
        if error is not None:
            _add_filter(filters, "error", "contains", error)
        if tag:
            _add_filter(filters, "tags", "any", list(tag))
        if dataset_id is not None:
            _add_filter(filters, "dataset_id", "=", dataset_id)
        if min_duration is not None:
            _add_filter(filters, "duration", ">=", min_duration)
        if max_duration is not None:
            _add_filter(filters, "duration", "<=", max_duration)
        if min_cost is not None:
            _add_filter(filters, "llm_cost", ">=", min_cost)
        if max_cost is not None:
            _add_filter(filters, "llm_cost", "<=", max_cost)

        body = {
            "pagination": {
                "limit": limit,
                "cursorSortValue": cursor_sort_value,
                "cursorItemId": cursor_item_id,
            },
        }

        if filters:
            body["filters"] = filters

        if sort_field or sort_dir:
            body["sort_by"] = {
                "field": sort_field or "created_at",
                "direction": sort_dir or "desc",
            }

        if start_time or end_time:
            body["time_range"] = {
                "start_time": start_time,
                "end_time": end_time,
            }

        result = ctx.obj["client"].request(
            "POST", f"/projects/{project_id}/traces/", json_body=body,
        )
        click.echo(json.dumps(result, indent=2, default=str))
