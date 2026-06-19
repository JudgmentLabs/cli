from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from judgment_cli import config
from judgment_cli import context as context_store
from judgment_cli.context_resolver import (
    parse_contextual_positionals,
    resolve_context,
)
from judgment_cli.credentials import ApiKeyCredential, ResolvedCredential
from judgment_cli.main import cli


@pytest.fixture(autouse=True)
def isolate_context_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        config,
        "credentials_path",
        lambda: tmp_path / "credentials.json",
    )
    monkeypatch.delenv("JUDGMENT_ORG_ID", raising=False)
    monkeypatch.delenv("JUDGMENT_PROJECT_ID", raising=False)


class FakeClient:
    def __init__(self, responses: dict[tuple[str, str], object] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, str, dict | None, object]] = []

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: object = None,
    ) -> object:
        self.calls.append((method, path, params, json_body))
        if path == "/projects" and params:
            key = (method, f"{path}:{params.get('organization_id')}")
            if key in self.responses:
                return self.responses[key]
        return self.responses.get((method, path), {"ok": True})


def test_parse_contextual_positionals_accepts_context_forms() -> None:
    no_ids = parse_contextual_positionals(
        ("trace-1",),
        positional_names=["trace_id"],
        needs_organization_id=True,
        needs_project_id=True,
    )
    assert no_ids.organization_id is None
    assert no_ids.project_id is None
    assert no_ids.values == {"trace_id": "trace-1"}

    project_only = parse_contextual_positionals(
        ("project-1", "trace-1"),
        positional_names=["trace_id"],
        needs_organization_id=True,
        needs_project_id=True,
    )
    assert project_only.organization_id is None
    assert project_only.project_id == "project-1"
    assert project_only.values == {"trace_id": "trace-1"}

    org_and_project = parse_contextual_positionals(
        ("org-1", "project-1", "trace-1"),
        positional_names=["trace_id"],
        needs_organization_id=True,
        needs_project_id=True,
    )
    assert org_and_project.organization_id == "org-1"
    assert org_and_project.project_id == "project-1"
    assert org_and_project.values == {"trace_id": "trace-1"}


def test_resolve_context_uses_saved_context(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )
    context_store.save_context(
        context_store.ActiveContext(
            organization_id="org-saved",
            project_id="project-saved",
            organization_name="Saved Org",
            project_name="Saved Project",
        )
    )

    active = resolve_context(FakeClient(), require_project=True)

    assert active.organization_id == "org-saved"
    assert active.project_id == "project-saved"


def test_env_org_does_not_reuse_saved_project_from_other_org(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )
    monkeypatch.setenv("JUDGMENT_ORG_ID", "org-env")
    context_store.save_context(
        context_store.ActiveContext(
            organization_id="org-saved",
            project_id="project-saved",
        )
    )
    client = FakeClient(
        {
            ("GET", "/projects:org-env"): {
                "projects": [_project("project-env", "Env Project")]
            }
        }
    )

    active = resolve_context(client, require_project=True)

    assert active.organization_id == "org-env"
    assert active.project_id == "project-env"


def test_resolve_context_finds_project_name_across_orgs() -> None:
    client = FakeClient(
        {
            ("GET", "/organizations"): {
                "organizations": [
                    _organization("org-1", "First"),
                    _organization("org-2", "Second"),
                ]
            },
            ("GET", "/projects:org-1"): {"projects": []},
            ("GET", "/projects:org-2"): {
                "projects": [
                    _project("project-2", "Production", total_traces=100)
                ]
            },
        }
    )

    active = resolve_context(
        client,
        project_name="Production",
        require_project=True,
    )

    assert active.organization_id == "org-2"
    assert active.project_id == "project-2"


def test_resolve_context_matches_nested_organization_name() -> None:
    client = FakeClient(
        {
            ("GET", "/organizations"): {
                "organizations": [
                    _organization("org-1", "Nested Org"),
                ]
            }
        }
    )

    active = resolve_context(
        client,
        organization_name="Nested Org",
    )

    assert active.organization_id == "org-1"
    assert active.organization_name == "Nested Org"


def test_generated_command_uses_env_org_and_positional_project(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake = _patch_cli_client(monkeypatch)
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )
    monkeypatch.setenv("JUDGMENT_ORG_ID", "org-env")
    pagination = json.dumps({"limit": 25, "cursor": None})

    result = CliRunner().invoke(
        cli,
        ["traces", "search", "project-pos", "--pagination", pagination, "-o", "json"],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls[-1] == (
        "POST",
        "/traces/search",
        None,
        {
            "organization_id": "org-env",
            "project_id": "project-pos",
            "pagination": json.loads(pagination),
        },
    )


def test_generated_command_uses_saved_context(monkeypatch, tmp_path: Path) -> None:
    fake = _patch_cli_client(monkeypatch)
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )
    context_store.save_context(
        context_store.ActiveContext(
            organization_id="org-saved",
            project_id="project-saved",
        )
    )
    pagination = json.dumps({"limit": 25, "cursor": None})

    result = CliRunner().invoke(
        cli,
        ["traces", "search", "--pagination", pagination, "-o", "json"],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls[-1][3] == {
        "organization_id": "org-saved",
        "project_id": "project-saved",
        "pagination": json.loads(pagination),
    }


def test_agent_threads_list_accepts_plain_string_filters(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake = _patch_cli_client(monkeypatch)
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )
    monkeypatch.setenv("JUDGMENT_ORG_ID", "org-env")

    result = CliRunner().invoke(
        cli,
        ["agent-threads", "list", "project-pos", "--agent-type", "global_copilot",
         "--agent-name", "my-agent", "-o", "json"],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls[-1][3] == {
        "organization_id": "org-env",
        "project_id": "project-pos",
        "agent_type": "global_copilot",
        "agent_name": "my-agent",
    }


def test_context_set_saves_most_used_project_first(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_cli_client(
        monkeypatch,
        FakeClient(
            {
                ("GET", "/organizations"): {
                    "organizations": [_organization("org-1", "Acme")]
                },
                ("GET", "/projects:org-1"): {
                    "projects": [
                        _project("low", "Low", total_traces=1),
                        _project("high", "High", total_traces=10),
                    ]
                },
            }
        ),
    )
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )

    result = CliRunner().invoke(cli, ["context", "set"], input="1\n")

    assert result.exit_code == 0, result.output
    assert context_store.load_context()["project_id"] == "high"


def test_context_set_matches_nested_organization_name(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_cli_client(
        monkeypatch,
        FakeClient(
            {
                ("GET", "/organizations"): {
                    "organizations": [_organization("org-1", "Acme")]
                },
                ("GET", "/projects:org-1"): {
                    "projects": [_project("project-1", "Production")]
                },
            }
        ),
    )
    monkeypatch.setattr(
        config, "credentials_path", lambda: tmp_path / "credentials.json"
    )

    result = CliRunner().invoke(cli, ["context", "set", "--organization", "Acme"])

    assert result.exit_code == 0, result.output
    saved = context_store.load_context()
    assert saved["organization_name"] == "Acme"
    assert saved["project_name"] == "Production"


def _organization(organization_id: str, name: str) -> dict[str, object]:
    return {"organization_id": organization_id, "detail": {"name": name}}


def _project(
    project_id: str,
    project_name: str,
    *,
    organization_id: str = "org-1",
    total_traces: int | None = None,
    is_favorited: bool = False,
) -> dict[str, object]:
    return {
        "organization_id": organization_id,
        "project_id": project_id,
        "project_name": project_name,
        "first_name": None,
        "last_name": None,
        "updated_at": None,
        "total_datasets": None,
        "total_experiment_runs": None,
        "total_traces": total_traces,
        "total_behaviors": None,
        "negative_binary_count": None,
        "is_favorited": is_favorited,
    }


def _patch_cli_client(monkeypatch: Any, fake: FakeClient | None = None) -> FakeClient:
    fake = fake or FakeClient()
    monkeypatch.setattr(
        "judgment_cli.main.credentials.resolve",
        lambda: ResolvedCredential(
            base_url="https://example.test",
            credential=ApiKeyCredential("test-key"),
        ),
    )
    monkeypatch.setattr("judgment_cli.main.JudgmentClient", lambda **_: fake)
    return fake
