from __future__ import annotations

from click.testing import CliRunner

from judgment_cli import ai, config
from judgment_cli.main import cli


class _FakeResponse:
    status_code = 200
    text = ""
    reason_phrase = "OK"

    def __init__(self, command: str):
        self._command = command

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._command}}]}


class _FakeClient:
    def __init__(self, captured: dict, command: str):
        self._captured = captured
        self._command = command

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, *, headers: dict, json: dict) -> _FakeResponse:
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["json"] = json
        return _FakeResponse(self._command)


def _isolate_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "_config_dir", lambda: tmp_path)
    for name in (
        "JUDGMENT_LLM_BASE_URL",
        "JUDGMENT_LLM_API_KEY",
        "JUDGMENT_LLM_MODEL",
        "JUDGMENT_LLM_AUTO_EXECUTE",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "LLM_AUTO_EXECUTE",
        "JUDGMENT_API_KEY",
        "JUDGMENT_BASE_URL",
        "JUDGMENT_ORG_ID",
        "JUDGMENT_PROJECT_ID",
    ):
        monkeypatch.delenv(name, raising=False)


def test_x_generates_judgment_command_with_cli_context(monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("JUDGMENT_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("JUDGMENT_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("JUDGMENT_LLM_MODEL", "test-model")
    monkeypatch.setenv("JUDGMENT_ORG_ID", "org_123")
    monkeypatch.setenv("JUDGMENT_PROJECT_ID", "proj_123")

    captured: dict = {}
    command = (
        'judgment traces search "$JUDGMENT_ORG_ID" "$JUDGMENT_PROJECT_ID" '
        "--filters '[{\"field\":\"duration\",\"op\":\">\",\"value\":10000000000}]' "
        "--pagination '{\"limit\":25,\"cursorSortValue\":null,\"cursorItemId\":null}'"
    )
    monkeypatch.setattr(
        "judgment_cli.ai.httpx.Client",
        lambda *args, **kwargs: _FakeClient(captured, command),
    )
    monkeypatch.setattr("judgment_cli.ai._select_action", lambda: "cancel")

    result = CliRunner().invoke(cli, ["x", "find", "me", "long", "traces"])

    assert result.exit_code == 0, result.output
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"]["model"] == "test-model"
    assert captured["json"]["messages"][1]["content"] == "find me long traces"
    system_prompt = captured["json"]["messages"][0]["content"]
    assert "Judgment CLI reference" in system_prompt
    assert "Judgment read-only JSON output reference" in system_prompt
    assert "judgment traces search <ORGANIZATION_ID> <PROJECT_ID>" in system_prompt
    assert (
        '`judgment traces search ORG PROJECT ... -o json` -> `{ "data": TraceSearchRow[]'
        in system_prompt
    )
    assert "`judgment traces tags ORG PROJECT TRACE_ID -o json` -> `string[]`" in system_prompt
    assert "duration" in system_prompt
    assert command in result.output


def test_x_rejects_non_judgment_commands(monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("JUDGMENT_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("JUDGMENT_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("JUDGMENT_LLM_MODEL", "test-model")

    captured: dict = {}
    monkeypatch.setattr(
        "judgment_cli.ai.httpx.Client",
        lambda *args, **kwargs: _FakeClient(captured, "curl https://example.com"),
    )

    result = CliRunner().invoke(cli, ["x", "do", "something", "else"])

    assert result.exit_code != 0
    assert "did not use the Judgment CLI" in result.output


def test_x_allows_judgment_json_pipeline(monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("JUDGMENT_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("JUDGMENT_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("JUDGMENT_LLM_MODEL", "test-model")

    captured: dict = {}
    command = (
        "judgment organizations list -o json | "
        "python3 -c 'import json,sys; print(json.load(sys.stdin))'"
    )
    monkeypatch.setattr(
        "judgment_cli.ai.httpx.Client",
        lambda *args, **kwargs: _FakeClient(captured, command),
    )
    monkeypatch.setattr("judgment_cli.ai._select_action", lambda: "cancel")

    result = CliRunner().invoke(
        cli,
        ["x", "find", "me", "the", "organization", "with", "the", "most", "projects"],
    )

    assert result.exit_code == 0, result.output
    system_prompt = captured["json"]["messages"][0]["content"]
    assert "counting, sorting, ranking" in system_prompt
    assert "Return the organization with the most projects" in system_prompt
    assert "ORG_ID=$(judgment organizations list -o json" in system_prompt
    assert "PROJECT_ID=$(judgment projects list" in system_prompt
    assert '`judgment organizations list -o json` -> `{ "organizations": OrganizationMembership[] }`' in system_prompt
    assert "`organization[\"detail\"][\"projects\"][0][\"count\"]`" in system_prompt
    assert '`judgment projects list ORGANIZATION_ID -o json` -> `{ "projects": ProjectSummary[] }`' in system_prompt
    assert '(org.get("detail") or {}).get("name")' in system_prompt
    assert command in result.output


def test_llm_config_survives_login_save(monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)

    config.save(api_key="judgment-key", base_url="https://api.example")
    config.update_llm(
        base_url="https://llm.example/v1",
        api_key="llm-key",
        model="test-model",
        auto_execute=True,
    )
    config.save(api_key="new-judgment-key")

    saved = config.load()
    assert saved["api_key"] == "new-judgment-key"
    assert saved["llm_base_url"] == "https://llm.example/v1"
    assert saved["llm_api_key"] == "llm-key"
    assert saved["llm_model"] == "test-model"
    assert saved["llm_auto_execute"] is True


class _FakeDiscoveryResponse:
    status_code = 200
    text = ""
    reason_phrase = "OK"

    def __init__(self, payload: object):
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _FakeDiscoveryClient:
    def __enter__(self) -> "_FakeDiscoveryClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, url: str, *, headers: dict, params: dict | None = None):
        assert headers["Authorization"] == "Bearer judgment-key"
        if url.endswith("/organizations"):
            return _FakeDiscoveryResponse(
                {
                    "organizations": [
                        {"organization_id": "org-small", "name": "Small"},
                        {"organization_id": "org-large", "name": "Large"},
                    ]
                }
            )
        if url.endswith("/projects") and params == {"organization_id": "org-small"}:
            return _FakeDiscoveryResponse(
                {"projects": [{"project_id": "small-prod", "name": "Production"}]}
            )
        if url.endswith("/projects") and params == {"organization_id": "org-large"}:
            return _FakeDiscoveryResponse(
                {
                    "projects": [
                        {
                            "project_id": "large-prod",
                            "name": "Production",
                            "total_traces": 10,
                        },
                        {
                            "project_id": "large-staging",
                            "name": "Staging",
                            "total_traces": 500,
                        },
                    ]
                }
            )
        raise AssertionError(f"unexpected request: {url} {params}")


def test_account_context_prefers_largest_org_and_most_traced_project(
    monkeypatch,
    tmp_path,
):
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("JUDGMENT_API_KEY", "judgment-key")
    monkeypatch.setattr(
        "judgment_cli.ai.httpx.Client",
        lambda *args, **kwargs: _FakeDiscoveryClient(),
    )

    context = ai._build_account_context("find me long traces")

    assert "Likely organization: org-large" in context
    assert "Recommended read-only project: large-staging" in context
    assert "most traces in likely organization" in context
    assert "Production project candidate: large-prod" in context
