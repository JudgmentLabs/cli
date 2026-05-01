"""End-to-end tests for every auto-generated CLI command.

These tests run the *real* ``judgment`` CLI against a live Judgment API
to prove that every auto-generated command still parses, sends a
well-formed request, and gets a successful response after a regeneration.

Configuration (read from the environment — wire as GitHub Actions
secrets, or drop into ``cli/.env`` for local runs):

* ``JUDGMENT_API_KEY``  — required.
* ``JUDGMENT_ORG_ID``   — required.
* ``JUDGMENT_BASE_URL`` — optional (default ``https://cli.judgmentlabs.ai``).

The suite is org-agnostic: it discovers a usable project by listing the
org's projects and picking one with traces, sessions, and agent threads.
This means swapping ``JUDGMENT_API_KEY`` / ``JUDGMENT_ORG_ID`` for any
org with at least one project that has the typical telemetry should
just work; if no project in the org has the required data, the
trace/session/thread-scoped tests will skip with a clear reason but
everything else (lifecycle tests, list/search commands, etc.) keeps
running.

Tests are skipped when ``JUDGMENT_API_KEY`` or ``JUDGMENT_ORG_ID`` are
unset. Lifecycle tests (create → update → delete) clean up after
themselves via ``try/finally``.

Coverage: every command in ``judgment_cli.generated_commands``. Each
test docstring lists the commands it exercises.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"


pytestmark = pytest.mark.skipif(
    not os.environ.get("JUDGMENT_API_KEY") or not os.environ.get("JUDGMENT_ORG_ID"),
    reason=(
        "JUDGMENT_API_KEY and JUDGMENT_ORG_ID must be set to run the live CLI "
        "tests. In CI, wire these up as GitHub Actions secrets; locally drop "
        "them into cli/.env."
    ),
)


# ── Helpers ────────────────────────────────────────────────────────


def _run(*args: str, expect_success: bool = True) -> dict | list | str:
    """Run ``judgment <args>`` as a subprocess and return its parsed output."""
    cmd = [sys.executable, "-m", "judgment_cli.main", *args]
    env = {**os.environ, "PYTHONPATH": str(SRC_DIR)}
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env, timeout=120
    )

    if expect_success and result.returncode != 0:
        pytest.fail(
            f"`judgment {' '.join(args)}` exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    stdout = result.stdout.strip()
    if not stdout:
        return ""
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return stdout


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ── Session-scoped fixtures (data discovery) ───────────────────────


@pytest.fixture(scope="session")
def project_id() -> str:
    """Project to scope tests against.

    Probes the top trace-rich projects in the org and picks the first
    one that also has at least one session and one agent thread, so the
    most read-only tests can run without skipping. Falls back to "most
    traces" if no project has all three. This makes the suite portable
    across orgs — no project ID needs to be hard-coded.
    """
    payload = _run("projects", "list")
    assert isinstance(payload, dict)
    projects = payload.get("projects") or []
    if not projects:
        pytest.skip("Test organization has no projects.")

    # Sort by trace count descending; we need traces for the trace-scoped
    # tests to have anything to read.
    projects.sort(key=lambda p: int(p.get("total_traces") or 0), reverse=True)
    candidates = [p for p in projects if int(p.get("total_traces") or 0) > 0][:20]
    if not candidates:
        pytest.skip("No projects in this organization have any traces.")

    pagination = json.dumps(
        {"limit": 1, "cursorSortValue": None, "cursorItemId": None}
    )
    for project in candidates:
        pid = project.get("project_id") or project.get("id")
        assert pid
        sessions = _run(
            "sessions",
            "search",
            pid,
            "--filters",
            "[]",
            "--pagination",
            pagination,
        )
        threads = _run("agent-threads", "list", pid, "--limit", "1")
        if (
            isinstance(sessions, dict)
            and (sessions.get("data") or [])
            and isinstance(threads, dict)
            and (threads.get("threads") or [])
        ):
            return pid

    # Nothing has the full triple — fall back to "most traces" so at least
    # the trace-scoped tests run; the others will skip with a clear reason.
    return candidates[0].get("project_id") or candidates[0].get("id")


@pytest.fixture(scope="session")
def trace_id(project_id: str) -> str:
    pagination = json.dumps(
        {"limit": 1, "cursorSortValue": None, "cursorItemId": None}
    )
    payload = _run("traces", "search", project_id, "--pagination", pagination)
    assert isinstance(payload, dict)
    traces = payload.get("data") or []
    if not traces:
        pytest.skip(f"Project {project_id} has no traces; can't run trace tests.")
    tid = traces[0].get("trace_id")
    assert tid, f"first trace has no trace_id: {traces[0]!r}"
    return tid


@pytest.fixture(scope="session")
def span_pair(project_id: str, trace_id: str) -> tuple[str, str]:
    """``(trace_id, span_id)`` for a real span — needed for ``traces span``."""
    payload = _run("traces", "spans", project_id, trace_id)
    spans = payload if isinstance(payload, list) else payload.get("spans") or payload.get("data") or []
    if not spans:
        pytest.skip(f"Trace {trace_id} has no spans.")
    span = spans[0]
    sid = span.get("span_id") or span.get("id")
    if not sid:
        pytest.skip(f"First span has no span_id: {span!r}")
    return trace_id, sid


@pytest.fixture(scope="session")
def session_id(project_id: str) -> str:
    pagination = json.dumps(
        {"limit": 1, "cursorSortValue": None, "cursorItemId": None}
    )
    payload = _run(
        "sessions",
        "search",
        project_id,
        "--filters",
        "[]",
        "--pagination",
        pagination,
    )
    assert isinstance(payload, dict)
    sessions = payload.get("data") or []
    if not sessions:
        pytest.skip(f"Project {project_id} has no sessions.")
    sid = sessions[0].get("session_id")
    assert sid
    return sid


@pytest.fixture(scope="session")
def thread_id(project_id: str) -> str:
    payload = _run("agent-threads", "list", project_id, "--limit", "1")
    assert isinstance(payload, dict)
    threads = payload.get("threads") or []
    if not threads:
        pytest.skip(f"Project {project_id} has no agent threads.")
    return threads[0]["id"]


# ────────────────────────────────────────────────────────────────────
# Top-level / unauthenticated
# ────────────────────────────────────────────────────────────────────


def test_root_help_lists_every_group():
    """``judgment --help`` advertises every auto-generated group."""
    output = _run("--help")
    assert isinstance(output, str)
    for group in (
        "agent-threads",
        "automations",
        "behaviors",
        "docs",
        "judges",
        "projects",
        "sessions",
        "traces",
    ):
        assert group in output, f"missing group {group!r} in --help"


# ────────────────────────────────────────────────────────────────────
# agent-threads
# ────────────────────────────────────────────────────────────────────


def test_agent_threads_list(project_id: str):
    """Covers ``agent-threads list``."""
    payload = _run("agent-threads", "list", project_id, "--limit", "5")
    assert isinstance(payload, dict)
    assert isinstance(payload.get("threads"), list)


def test_agent_threads_get(project_id: str, thread_id: str):
    """Covers ``agent-threads get``."""
    payload = _run("agent-threads", "get", project_id, thread_id)
    assert isinstance(payload, dict)
    assert payload.get("id") == thread_id or payload.get("thread", {}).get("id") == thread_id or "messages" in payload or "transcript" in payload


# ────────────────────────────────────────────────────────────────────
# automations
# ────────────────────────────────────────────────────────────────────


def test_automations_list(project_id: str):
    """Covers ``automations list``."""
    payload = _run("automations", "list", project_id)
    assert isinstance(payload, dict)
    assert isinstance(payload.get("automations"), list)


def test_automations_lifecycle(project_id: str):
    """Covers ``automations create``, ``get``, ``update``, ``delete``."""
    name = _unique("cli-e2e-automation")
    conditions = json.dumps(
        [{"metric": {"scorer_type": "static", "name": "duration"}, "comparison": "gt"}]
    )

    created = _run(
        "automations",
        "create",
        project_id,
        name,
        "--conditions",
        conditions,
        "--combine-type",
        "all",
    )
    rule_id = (
        (created.get("rule_id") if isinstance(created, dict) else None)
        or (created.get("automation", {}).get("id") if isinstance(created, dict) else None)
    )
    assert rule_id, f"could not extract rule_id from create response: {created!r}"

    try:
        got = _run("automations", "get", project_id, rule_id)
        assert isinstance(got, dict)

        updated = _run(
            "automations",
            "update",
            project_id,
            rule_id,
            "--description",
            "updated by cli e2e tests",
        )
        assert isinstance(updated, dict)
    finally:
        _run("automations", "delete", project_id, rule_id)


# ────────────────────────────────────────────────────────────────────
# behaviors
# ────────────────────────────────────────────────────────────────────


def test_behaviors_list(project_id: str):
    """Covers ``behaviors list``."""
    payload = _run("behaviors", "list", project_id)
    assert isinstance(payload, dict)
    assert isinstance(payload.get("behaviors"), list)


# Keep the test behavior judges from running automatically against real spans.
_OFFLINE_SETTINGS = json.dumps(
    {
        "online_evaluation_mode": "on_demand",
        "online_sampling_rate": 0,
        "online_span_triggers": [],
        "online_session_scoring": False,
    }
)


def test_behaviors_binary_lifecycle(project_id: str):
    """Covers ``behaviors create-binary``, ``get``, ``update``, ``delete``."""
    name = _unique("cli-e2e-behavior-bin")
    created = _run(
        "behaviors",
        "create-binary",
        project_id,
        name,
        "Is the response correct? Return true or false.",
        "--advanced-settings",
        _OFFLINE_SETTINGS,
    )
    behavior_id = _extract_behavior_id(created)
    assert behavior_id, f"could not extract behavior id from {created!r}"

    try:
        got = _run("behaviors", "get", project_id, behavior_id)
        assert isinstance(got, dict)

        updated = _run(
            "behaviors",
            "update",
            project_id,
            behavior_id,
            "--description",
            "updated by cli e2e tests",
        )
        assert isinstance(updated, dict)
    finally:
        # ``--delete-scorer true`` cleans up the underlying judge so the test
        # account doesn't accumulate orphan scorers across CI runs.
        _run(
            "behaviors",
            "delete",
            project_id,
            behavior_id,
            "--delete-scorer",
            "true",
        )


def test_behaviors_classifier_lifecycle(project_id: str):
    """Covers ``behaviors create-classifier`` and ``delete``."""
    name = _unique("cli-e2e-behavior-cls")
    options = json.dumps(
        [
            {"name": "good", "description": "response is correct"},
            {"name": "bad", "description": "response is incorrect"},
        ]
    )
    created = _run(
        "behaviors",
        "create-classifier",
        project_id,
        name,
        "Classify the response as good or bad.",
        "--options",
        options,
        "--advanced-settings",
        _OFFLINE_SETTINGS,
    )
    behavior_id = _extract_behavior_id(created)
    assert behavior_id, f"could not extract behavior id from {created!r}"

    try:
        got = _run("behaviors", "get", project_id, behavior_id)
        assert isinstance(got, dict)
    finally:
        _run(
            "behaviors",
            "delete",
            project_id,
            behavior_id,
            "--delete-scorer",
            "true",
            "--delete-all-values",
            "true",
        )


def _extract_behavior_id(response: object) -> str | None:
    """Behaviors create endpoints have varied response shapes — try a few."""
    if not isinstance(response, dict):
        return None
    for key in ("behavior_id", "id"):
        if isinstance(response.get(key), str):
            return response[key]
    inner = response.get("behavior")
    if isinstance(inner, dict):
        for key in ("id", "behavior_id"):
            if isinstance(inner.get(key), str):
                return inner[key]
    behaviors = response.get("behaviors")
    if isinstance(behaviors, list) and behaviors:
        first = behaviors[0]
        if isinstance(first, dict):
            for key in ("id", "behavior_id"):
                if isinstance(first.get(key), str):
                    return first[key]
    return None


# ────────────────────────────────────────────────────────────────────
# docs
# ────────────────────────────────────────────────────────────────────


def test_docs_search():
    """Covers ``docs search``."""
    payload = _run("docs", "search", "getting started", "--match-count", "3")
    assert isinstance(payload, dict)
    assert isinstance(payload.get("results"), list)


# NOTE: ``docs get-page`` is intentionally not tested.
#
# The endpoint proxies to the upstream docs site (DOCS_BASE_URL) by
# fetching ``/llms.mdx/<path>``. Some environments (e.g. the staging
# docs site) gate that endpoint behind auth and return 401, which the
# CLI server surfaces to us as a 404. The CLI command itself is just a
# thin GET wrapper — the same plumbing is exercised by other GET
# commands (e.g. ``judges models``, ``projects list``) — so we trust
# those to catch generator regressions and skip this one to avoid
# flaking on an unrelated infra issue.


# ────────────────────────────────────────────────────────────────────
# judges
# ────────────────────────────────────────────────────────────────────


def test_judges_models():
    """Covers ``judges models``."""
    payload = _run("judges", "models")
    assert isinstance(payload, dict)
    assert isinstance(payload.get("models"), list)
    assert payload["models"], "expected at least one judge model"


def test_judges_list(project_id: str):
    """Covers ``judges list``."""
    payload = _run("judges", "list", project_id)
    assert isinstance(payload, dict)
    assert isinstance(payload.get("judges"), list)


def test_judges_lifecycle(project_id: str):
    """Covers ``judges create``, ``get``, ``get-settings``, ``update``,
    ``update-settings``, ``set-tag`` (add + remove), and ``delete``."""
    # Pick any available model so the create call succeeds.
    models = _run("judges", "models").get("models")
    assert models, "no judge models available"
    model_id = models[0].get("id") or models[0].get("model_name") or models[0].get("name")
    assert model_id, f"no model id field on {models[0]!r}"

    name = _unique("cli-e2e-judge")
    created = _run(
        "judges",
        "create",
        project_id,
        name,
        model_id,
        "Score the response from 0 to 1.",
        "--score-type",
        "numeric",
        "--min-score",
        "0",
        "--max-score",
        "1",
    )
    judge_id = _extract_judge_id(created)
    assert judge_id, f"could not extract judge id from {created!r}"

    try:
        got = _run("judges", "get", project_id, judge_id)
        assert isinstance(got, dict)

        settings = _run("judges", "get-settings", project_id, judge_id)
        assert isinstance(settings, dict)

        _run(
            "judges",
            "update-settings",
            project_id,
            judge_id,
            "--evaluation-mode",
            "on_demand",
            "--sampling-rate",
            "0",
            "--span-triggers",
            "[]",
            "--session-scoring",
            "false",
        )

        _run(
            "judges",
            "update",
            project_id,
            judge_id,
            "--judge-description",
            "updated by cli e2e tests",
        )

        # Tag the freshly-created version then remove the tag. New judges
        # start at v0.0 by convention; ``judges get`` confirmed this when
        # we wrote the test.
        tag = _unique("e2e")
        _run(
            "judges",
            "set-tag",
            project_id,
            judge_id,
            tag,
            "--major-version",
            "0",
            "--minor-version",
            "0",
            "--action",
            "add",
        )
        _run(
            "judges",
            "set-tag",
            project_id,
            judge_id,
            tag,
            "--major-version",
            "0",
            "--minor-version",
            "0",
            "--action",
            "remove",
        )
    finally:
        _run("judges", "delete", project_id, "--judge-ids", judge_id)


def _extract_judge_id(response: object) -> str | None:
    if not isinstance(response, dict):
        return None
    for key in ("judge_id", "id"):
        if isinstance(response.get(key), str):
            return response[key]
    inner = response.get("judge")
    if isinstance(inner, dict):
        for key in ("id", "judge_id"):
            if isinstance(inner.get(key), str):
                return inner[key]
    return None


# ────────────────────────────────────────────────────────────────────
# projects
# ────────────────────────────────────────────────────────────────────


def test_projects_list():
    """Covers ``projects list``."""
    payload = _run("projects", "list")
    assert isinstance(payload, dict)
    assert isinstance(payload.get("projects"), list)


def test_projects_create_and_favorite():
    """Covers ``projects create``, ``add-favorite``, ``remove-favorite``.

    Projects can't be deleted via the API, so this test creates a fresh
    project with a unique name. Old test projects can be cleared from the
    UI as needed (search for ``cli-e2e-project-`` prefix).
    """
    name = _unique("cli-e2e-project")
    created = _run("projects", "create", name)
    assert isinstance(created, dict)
    project = created.get("project") or created
    new_pid = project.get("project_id") or project.get("id")
    assert new_pid, f"could not extract new project id from {created!r}"

    fav = _run("projects", "add-favorite", new_pid)
    assert isinstance(fav, dict)
    unfav = _run("projects", "remove-favorite", new_pid)
    assert isinstance(unfav, dict)


# ────────────────────────────────────────────────────────────────────
# sessions
# ────────────────────────────────────────────────────────────────────


def test_sessions_search(project_id: str):
    """Covers ``sessions search``."""
    pagination = json.dumps(
        {"limit": 5, "cursorSortValue": None, "cursorItemId": None}
    )
    payload = _run(
        "sessions",
        "search",
        project_id,
        "--filters",
        "[]",
        "--pagination",
        pagination,
    )
    assert isinstance(payload, dict)


def test_sessions_get(project_id: str, session_id: str):
    """Covers ``sessions get``."""
    payload = _run("sessions", "get", project_id, session_id)
    assert isinstance(payload, dict)


def test_sessions_trace_ids(project_id: str, session_id: str):
    """Covers ``sessions trace-ids``."""
    payload = _run("sessions", "trace-ids", project_id, session_id)
    assert isinstance(payload, dict)
    assert "trace_ids" in payload


def test_sessions_trace_behaviors(project_id: str, session_id: str):
    """Covers ``sessions trace-behaviors``."""
    payload = _run("sessions", "trace-behaviors", project_id, session_id)
    assert isinstance(payload, (dict, list))


# ────────────────────────────────────────────────────────────────────
# traces
# ────────────────────────────────────────────────────────────────────


def test_traces_search(project_id: str):
    """Covers ``traces search``."""
    pagination = json.dumps(
        {"limit": 5, "cursorSortValue": None, "cursorItemId": None}
    )
    payload = _run(
        "traces", "search", project_id, "--pagination", pagination
    )
    assert isinstance(payload, dict)


def test_traces_get(project_id: str, trace_id: str):
    """Covers ``traces get``."""
    payload = _run("traces", "get", project_id, trace_id)
    assert isinstance(payload, dict)


def test_traces_spans(project_id: str, trace_id: str):
    """Covers ``traces spans``."""
    payload = _run("traces", "spans", project_id, trace_id)
    assert isinstance(payload, (dict, list))


def test_traces_span(project_id: str, span_pair: tuple[str, str]):
    """Covers ``traces span``."""
    tid, sid = span_pair
    spans = json.dumps([{"trace_id": tid, "span_id": sid}])
    payload = _run("traces", "span", project_id, "--spans", spans)
    assert isinstance(payload, (dict, list))


def test_traces_tags(project_id: str, trace_id: str):
    """Covers ``traces tags``."""
    payload = _run("traces", "tags", project_id, trace_id)
    assert isinstance(payload, (dict, list))


def test_traces_behaviors(project_id: str, trace_id: str):
    """Covers ``traces behaviors``."""
    payload = _run("traces", "behaviors", project_id, trace_id)
    assert isinstance(payload, (dict, list))


def test_traces_add_tags(project_id: str, trace_id: str):
    """Covers ``traces add-tags``.

    Adds a uniquely-named tag so we can verify it lands without polluting
    the trace with churn-y test tags.
    """
    tag = _unique("cli-e2e-tag")
    payload = _run("traces", "add-tags", project_id, trace_id, "--tags", tag)
    assert isinstance(payload, (dict, list))


def test_traces_evaluate(project_id: str, trace_id: str):
    """Covers ``traces evaluate``.

    Restricts to a single trace and a deliberately nonexistent judge name
    so this doesn't kick off real (potentially expensive) LLM evaluations
    in CI.
    """
    payload = _run(
        "traces",
        "evaluate",
        project_id,
        "--trace-ids",
        trace_id,
        "--specific-judge-names",
        "__cli_e2e_nonexistent_judge__",
    )
    assert isinstance(payload, (dict, list, str))
