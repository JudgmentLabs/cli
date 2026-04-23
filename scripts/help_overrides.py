"""Help text overrides for generated CLI commands.

Entries are keyed by ``"<group>.<command>"``. ``COMMAND_HELP`` overrides the
command docstring; ``OPTION_HELP`` overrides individual ``--flag`` help text.
"""

from __future__ import annotations


_TRACE_FILTERS_HELP = """\
Filter expressions, ANDed together. Each item is {"field":<field>,"op":<op>,"value":<value>}. Allowed ops depend on the field's type.

\b
Op groups:
  STRING_OPS  = "=" | "!=" | "contains" | "does_not_contain" | "exists" | "is_absent"
  NUMERIC_OPS = "=" | "!=" | "<" | "<=" | ">" | ">="
  ARRAY_ANY   = "any"   (matches when the row's array overlaps the supplied values)

String fields (op in STRING_OPS, value is a string): span_name, customer_id, customer_user_id, session_id, error, dataset_id.

Numeric fields (op in NUMERIC_OPS, value is a number): duration (nanoseconds), llm_cost (USD).

Array fields (op = "any", value is an array): tags (strings), rules_invoked (rule names from this project, strings), behaviors (behavior UUIDs).

\b
Special:
  full_text_search       op = "contains", value is a string searched across span attribute text.
  span_attributes_roots  matches a single span attribute key/value:
                           {"field":"span_attributes_roots","key":"<attribute-name>","op":<STRING_OPS>,"value":"<string>"}

Example: --filters '[{"field":"span_name","op":"=","value":"agent.run"}]'
"""

_SESSION_FILTERS_HELP = """\
Filter expressions, ANDed together. Each item is {"field":<field>,"op":<op>,"value":<value>}. Allowed ops depend on the field's type.

\b
Op groups:
  STRING_OPS  = "=" | "!=" | "contains" | "does_not_contain"
  NUMERIC_OPS = "=" | "!=" | "<" | "<=" | ">" | ">="
  ARRAY_ANY   = "any"   (matches when the row's array overlaps the supplied values)

String fields (op in STRING_OPS, value is a string): session_id.

Numeric fields (op in NUMERIC_OPS, value is a number): trace_count, latency (nanoseconds), total_cost (USD).

Array fields (op = "any", value is an array): behaviors (behavior UUIDs).

Example: --filters '[{"field":"trace_count","op":">=","value":5}]'
"""

_TIME_RANGE_HELP = (
    '{"start_time":<iso8601-string>|null,"end_time":<iso8601-string>|null}. '
    "Either bound may be null to leave that side open. "
    "Invalid timestamps return 400."
)

_TRACE_SORT_BY_HELP = (
    '{"field":<sort_field>,"direction":"asc"|"desc"} where sort_field is one of: '
    "created_at, span_name, duration, llm_cost. "
    'Default when omitted: {"field":"created_at","direction":"desc"}.'
)

_SESSION_SORT_BY_HELP = (
    '{"field":<sort_field>,"direction":"asc"|"desc"} where sort_field is one of: '
    "created_at, num_traces, latency, llm_cost. "
    'Default when omitted: {"field":"created_at","direction":"desc"}.'
)

_TRACE_PAGINATION_HELP = """\
{"limit":<int 1-200>,"cursorSortValue":<string>|null,"cursorItemId":<string>|null}.

First page: pass null for both cursor fields. Each response returns nextCursor:{sort_value,trace_id} (or null when hasMore=false); copy those into cursorSortValue and cursorItemId for the next page.\
"""

_SESSION_PAGINATION_HELP = """\
{"limit":<int 1-200>,"cursorSortValue":<string>|null,"cursorItemId":<string>|null}.

First page: pass null for both cursor fields. Each response returns nextCursor:{sort_value,session_id} (or null when hasMore=false); copy those into cursorSortValue and cursorItemId for the next page.\
"""


COMMAND_HELP: dict[str, str] = {
    "traces.search": (
        "Search traces in a project.\n"
        "\n"
        "Filtering, sorting, time bounds, and pagination are passed as JSON via the body fields below — see each flag's description for its full reference.\n"
        "\n"
        "\b\n"
        'Example: judgment traces search <PROJECT_ID> \\\n'
        "  --filters '[{\"field\":\"span_name\",\"op\":\"=\",\"value\":\"agent.run\"}]' \\\n"
        '  --sort-by \'{"field":"llm_cost","direction":"desc"}\' \\\n'
        '  --pagination \'{"limit":25,"cursorSortValue":null,"cursorItemId":null}\''
    ),
    "sessions.search": (
        "Search sessions in a project.\n"
        "\n"
        "Filtering, sorting, time bounds, and pagination are passed as JSON via the body fields below — see each flag's description for its full reference.\n"
        "\n"
        "\b\n"
        'Example: judgment sessions search <PROJECT_ID> \\\n'
        "  --filters '[{\"field\":\"trace_count\",\"op\":\">=\",\"value\":5}]' \\\n"
        '  --sort-by \'{"field":"latency","direction":"desc"}\' \\\n'
        '  --pagination \'{"limit":25,"cursorSortValue":null,"cursorItemId":null}\''
    ),
}


OPTION_HELP: dict[str, dict[str, str]] = {
    "traces.search": {
        "filters": _TRACE_FILTERS_HELP,
        "sort_by": _TRACE_SORT_BY_HELP,
        "time_range": _TIME_RANGE_HELP,
        "pagination": _TRACE_PAGINATION_HELP,
    },
    "sessions.search": {
        "filters": _SESSION_FILTERS_HELP,
        "sort_by": _SESSION_SORT_BY_HELP,
        "time_range": _TIME_RANGE_HELP,
        "pagination": _SESSION_PAGINATION_HELP,
    },
}


def command_help(group: str, command: str) -> str | None:
    return COMMAND_HELP.get(f"{group}.{command}")


def option_help(group: str, command: str, option: str) -> str | None:
    return OPTION_HELP.get(f"{group}.{command}", {}).get(option)
