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


_AUTOMATION_CONDITIONS_HELP = """\
JSON array of rule conditions. Each condition references a named metric/scorer on the project and a comparison. Items are ANDed or ORed together based on the COMBINE_TYPE positional argument ("all" vs "any").

\b
Condition shape:
  {
    "metric": {
      "scorer_type": "behavior" | "judge" | "prompt" | "custom" | "static" | "span_attribute" | "error",
      "name": "<scorer or metric name>",
      "threshold": <number | string | null>?
    },
    "comparison": "lt" | "gt" | "eq" | "gte" | "lte" | "fails" | "succeeds" | "chooses" | "detected" | "equals" | "contains" | "exists"
  }

\b
Common scorer_type values:
  behavior        Judge-scored behavior (name = behavior name, e.g. "Relevance")
  static          Built-in metrics like "duration" (ms) or "llm_cost" (USD)
  prompt/custom   Prompt or custom scorer by name
  span_attribute  Arbitrary span attribute key (name = attribute key)
  error           Span error condition

Example: --conditions '[{"metric":{"scorer_type":"behavior","name":"Relevance","threshold":0.7},"comparison":"gte"}]'\
"""

_AUTOMATION_ACTIONS_HELP = """\
JSON object describing what happens when the automation fires. All top-level keys are optional — include only the actions you want configured.

\b
Shape:
  {
    "notification": {
      "enabled": <bool>?,
      "communication_methods": ["email" | "slack" | "pagerduty"],
      "email_addresses": ["<addr>", ...]?,
      "pagerduty_config": {"routing_key":"<key>","severity":"critical"|"error"|"warning"|"info"}?
    }?,
    "dataset_addition": {
      "enabled": <bool>?,
      "dataset_name": "<dataset>",
      "metadata_fields": <any>?
    }?,
    "behavior_evaluation": {
      "enabled": <bool>?,
      "behavior_judge_names": ["<judge_name>", ...]
    }?
  }

Slack notifications are configured per-organization in the Judgment UI; pass "slack" in communication_methods to use them. Example: --actions '{"notification":{"communication_methods":["slack"]}}'\
"""

_AUTOMATION_TRIGGER_FREQUENCY_HELP = """\
JSON 3-tuple [count, period, unit] describing the rate-limit window. Pass null to disable frequency limiting.

\b
Shape: [<max_trigger_count:number>, <period:number>, <unit:"seconds"|"minutes"|"hours"|"days">]

Example: --trigger-frequency '[5, 1, "hours"]'  (max 5 triggers per 1 hour)\
"""

_AUTOMATION_COOLDOWN_HELP = """\
JSON 2-tuple [period, unit] describing the minimum wait between triggers. Pass null to clear the cooldown.

\b
Shape: [<period:number>, <unit:"seconds"|"minutes"|"hours"|"days">]

Example: --cooldown-period '[15, "minutes"]'  (at least 15 min between triggers)\
"""

_BEHAVIOR_ADVANCED_SETTINGS_HELP = """\
JSON object overriding the judge's online-evaluation configuration. All four fields are required when this flag is supplied.

\b
Shape:
  {
    "online_evaluation_mode": "continuous" | "on_demand",
    "online_sampling_rate": <number 0-100>,
    "online_span_triggers": [
      {"field":"span_name"|"span_attribute","operator":"contains"|"equals"|"exists","value":"<string>","key":"<attr-key>"?}
    ],
    "online_session_scoring": <bool>
  }

"continuous" runs the judge automatically on qualifying spans; "on_demand" requires a manual `judgment traces evaluate` call. online_sampling_rate is a percent of matching spans to score.

Example: --advanced-settings '{"online_evaluation_mode":"continuous","online_sampling_rate":10,"online_span_triggers":[],"online_session_scoring":false}'\
"""

_BEHAVIOR_CATEGORY_IDS_HELP = (
    "UUID of a category to attach the behavior to. Repeat the flag to attach "
    "multiple categories: --category-ids <uuid1> --category-ids <uuid2>."
)

_CLASSIFIER_OPTIONS_HELP = """\
JSON array of the allowed output categories the classifier judge can return. Must contain at least one option.

\b
Shape:
  [
    {"name":"<label>", "description":"<optional human description>", "category_ids":["<uuid>", ...]},
    ...
  ]

Example: --options '[{"name":"Good","description":"helpful response"},{"name":"Bad","description":"unhelpful or incorrect"}]'\
"""

_JUDGE_SPAN_TRIGGERS_HELP = """\
JSON array of span filters that restrict which spans the judge evaluates. Pass [] to evaluate all spans.

\b
Shape:
  [
    {
      "field": "span_name" | "span_attribute",
      "operator": "contains" | "equals" | "exists",
      "value": "<string>",
      "key": "<attribute key>"?
    },
    ...
  ]

Use "field":"span_name" to match on span names; "field":"span_attribute" with "key":"<attr>" to match on a span attribute's value. Triggers are ANDed together — a span must match every entry to be evaluated.

Example: --span-triggers '[{"field":"span_name","operator":"equals","value":"agent.run"}]'\
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
    "automations.create": (
        "Create an automation (rule) in a project.\n"
        "\n"
        "An automation watches behavior/latency/cost metrics on the project and fires actions when its conditions match. Requires the developer role.\n"
        "\n"
        "\b\n"
        "Example: judgment automations create <PROJECT_ID> my-rule any \\\n"
        "  --description 'Alert on low relevance scores' \\\n"
        "  --conditions '[{\"metric\":{\"scorer_type\":\"behavior\",\"name\":\"Relevance\",\"threshold\":0.7},\"comparison\":\"lt\"}]' \\\n"
        "  --actions '{\"notification\":{\"communication_methods\":[\"slack\"]}}' \\\n"
        "  --cooldown-period 5 --cooldown-period-unit minutes"
    ),
    "automations.update": (
        "Update an existing automation. All fields other than the positional arguments are optional — only supplied flags are applied.\n"
        "\n"
        "Use --active true/false to enable or disable without changing other fields. Requires the developer role.\n"
        "\n"
        "\b\n"
        "Example: judgment automations update <PROJECT_ID> <RULE_ID> --active false"
    ),
    "automations.delete": (
        "Delete an automation. Requires the admin role.\n"
        "\n"
        "\b\n"
        "Example: judgment automations delete <PROJECT_ID> <RULE_ID>"
    ),
    "automations.get": (
        "Fetch the full definition of a single automation by ID.\n"
        "\n"
        "\b\n"
        "Example: judgment automations get <PROJECT_ID> <RULE_ID>"
    ),
    "behaviors.create-binary": (
        "Create a binary (Yes/No) behavior backed by a prompt judge.\n"
        "\n"
        'Scores each trace/span as "Yes" (true) or "No" (false) using the prompt you supply. Pass --judge-id to attach to an existing judge instead of creating a new prompt scorer. Requires the developer role.\n'
        "\n"
        "\b\n"
        "Example: judgment behaviors create-binary <PROJECT_ID> 'Relevance' \\\n"
        "  'Was the assistant response relevant to the user message?' \\\n"
        "  --description 'Binary relevance check' --model gpt-5.2"
    ),
    "behaviors.create-classifier": (
        "Create a categorical (multi-class) behavior backed by a prompt judge.\n"
        "\n"
        "Scores each trace/span into one of the --options categories. Pass --judge-id to attach to an existing classifier judge instead of creating a new one. Requires the developer role.\n"
        "\n"
        "\b\n"
        "Example: judgment behaviors create-classifier <PROJECT_ID> 'Sentiment' \\\n"
        "  'Classify the assistant response tone.' \\\n"
        "  --options '[{\"name\":\"Positive\"},{\"name\":\"Neutral\"},{\"name\":\"Negative\"}]'"
    ),
    "behaviors.update": (
        "Update a behavior's description. Requires the developer role.\n"
        "\n"
        "\b\n"
        "Example: judgment behaviors update <PROJECT_ID> <BEHAVIOR_ID> --description 'New description'"
    ),
    "behaviors.delete": (
        "Delete a behavior. Requires the admin role.\n"
        "\n"
        "Binary behaviors always delete both the true and false rows. For classifier behaviors, pass --delete-all-values true to delete every category row for the judge at once. Pass --delete-scorer true to also delete the underlying prompt scorer when no other behaviors reference it.\n"
        "\n"
        "\b\n"
        "Example: judgment behaviors delete <PROJECT_ID> <BEHAVIOR_ID> --delete-scorer true"
    ),
    "judges.update-settings": (
        "Update a judge's online-evaluation configuration.\n"
        "\n"
        "Applies to all behaviors backed by the judge. EVALUATION_MODE selects whether the judge runs continuously on every matching span (\"continuous\") or only when explicitly invoked (\"on_demand\"); SAMPLING_RATE is a percentage (0-100) of qualifying spans to score. Requires the developer role.\n"
        "\n"
        "\b\n"
        "Example: judgment judges update-settings <PROJECT_ID> <JUDGE_ID> continuous 10 \\\n"
        "  --span-triggers '[{\"field\":\"span_name\",\"operator\":\"equals\",\"value\":\"agent.run\"}]'"
    ),
    "projects.create": (
        "Create a new project in your organization. Requires the developer role.\n"
        "\n"
        "\b\n"
        "Example: judgment projects create my-new-project"
    ),
    "projects.add-favorite": (
        "Mark a project as a favorite for your user so it appears pinned in the UI.\n"
        "\n"
        "\b\n"
        "Example: judgment projects add-favorite <PROJECT_ID>"
    ),
    "projects.remove-favorite": (
        "Remove a project from your user's favorites.\n"
        "\n"
        "\b\n"
        "Example: judgment projects remove-favorite <PROJECT_ID>"
    ),
    "traces.add-tags": (
        "Attach one or more string tags to an existing trace.\n"
        "\n"
        "Tags are additive — existing tags on the trace are preserved. Repeat --tags to add multiple tags.\n"
        "\n"
        "\b\n"
        "Example: judgment traces add-tags <PROJECT_ID> <TRACE_ID> \\\n"
        "  --tags regression --tags investigate"
    ),
    "traces.evaluate": (
        "Queue traces for re-evaluation by the project's judges.\n"
        "\n"
        "Pass specific trace IDs with --trace-ids (repeat the flag) or use --evaluate-all true to re-evaluate every trace in the project. Use --specific-judge-names to restrict which judges run (repeat the flag). Requires the developer role.\n"
        "\n"
        "\b\n"
        "Example: judgment traces evaluate <PROJECT_ID> \\\n"
        "  --trace-ids <TRACE_ID_1> --trace-ids <TRACE_ID_2> \\\n"
        "  --specific-judge-names Relevance"
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
    "automations.create": {
        "description": "Human-readable description shown in the UI.",
        "conditions": _AUTOMATION_CONDITIONS_HELP,
        "actions": _AUTOMATION_ACTIONS_HELP,
        "cooldown_period": "Cooldown duration as a plain number. Paired with --cooldown-period-unit. Example: --cooldown-period 15 --cooldown-period-unit minutes.",
        "cooldown_period_unit": "Unit for --cooldown-period: seconds | minutes | hours | days.",
        "trigger_frequency_count": "Maximum triggers allowed within the window defined by --trigger-frequency-period and --trigger-frequency-period-unit.",
        "trigger_frequency_period": "Window length for the trigger-frequency limit. Paired with --trigger-frequency-period-unit.",
        "trigger_frequency_period_unit": "Unit for --trigger-frequency-period: seconds | minutes | hours | days.",
    },
    "automations.update": {
        "name": "New name for the automation.",
        "description": "New description for the automation.",
        "conditions": _AUTOMATION_CONDITIONS_HELP,
        "actions": _AUTOMATION_ACTIONS_HELP,
        "active": "Enable (true) or disable (false) the automation without modifying other fields.",
        "cooldown_period": _AUTOMATION_COOLDOWN_HELP,
        "trigger_frequency": _AUTOMATION_TRIGGER_FREQUENCY_HELP,
    },
    "behaviors.create-binary": {
        "description": "Human-readable description shown in the UI.",
        "model": 'LLM model ID used by the judge prompt. Defaults to "gpt-5.2" when omitted.',
        "category_ids": _BEHAVIOR_CATEGORY_IDS_HELP,
        "advanced_settings": _BEHAVIOR_ADVANCED_SETTINGS_HELP,
        "judge_id": "Attach the new behavior to an existing judge instead of creating one. The judge must be score_type=binary and have no existing behaviors.",
    },
    "behaviors.create-classifier": {
        "options": _CLASSIFIER_OPTIONS_HELP,
        "model": 'LLM model ID used by the judge prompt. Defaults to "gpt-5.2" when omitted.',
        "category_ids": _BEHAVIOR_CATEGORY_IDS_HELP,
        "advanced_settings": _BEHAVIOR_ADVANCED_SETTINGS_HELP,
        "judge_id": "Attach the new behavior to an existing judge instead of creating one. The judge must be score_type=categorical and have no existing behaviors.",
    },
    "behaviors.update": {
        "description": "New human-readable description for the behavior. Pass null to clear it.",
    },
    "behaviors.delete": {
        "delete_scorer": "When true, also delete the underlying prompt scorer if no other behaviors reference it.",
        "delete_all_values": "For classifier behaviors, when true deletes every category row for this judge (not just the provided BEHAVIOR_ID). Ignored for binary behaviors (those always delete both rows).",
    },
    "judges.update-settings": {
        "span_triggers": _JUDGE_SPAN_TRIGGERS_HELP,
        "session_scoring": "When true, run the judge at session granularity instead of per-span.",
    },
    "traces.add-tags": {
        "tags": "Tag string to attach to the trace. Repeat --tags to attach multiple tags: --tags a --tags b.",
    },
    "traces.evaluate": {
        "evaluate_all": "When true, re-evaluate every trace in the project. Mutually exclusive with --trace-ids.",
        "trace_ids": "Trace UUID to re-evaluate. Repeat --trace-ids to evaluate multiple: --trace-ids <id1> --trace-ids <id2>.",
        "specific_judge_names": "Restrict evaluation to judges with these names. Repeat the flag to pass multiple. Omit to run every applicable judge.",
    },
}


def command_help(group: str, command: str) -> str | None:
    return COMMAND_HELP.get(f"{group}.{command}")


def option_help(group: str, command: str, option: str) -> str | None:
    return OPTION_HELP.get(f"{group}.{command}", {}).get(option)
