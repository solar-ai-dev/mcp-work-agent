"""Shared driver for production Graph/API tests; only external boundaries are faked."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.api import composition
from google_work_agent.api.container import ApiContainer
from tests.support.fakes.langgraph_e2e import LangGraphE2EGeminiTransport
from tests.support.production_runtime import build_test_production_container

_BOOTSTRAP_SECRET = "langgraph-real-production-e2e-bootstrap"
_SERVICE_INSTANCE_ID = "langgraph-real-production-e2e-service"
API_HEADERS = {
    "Origin": "http://127.0.0.1:8000",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


def build_container(
    runtime_root: Path,
    *,
    transport: LangGraphE2EGeminiTransport,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> ApiContainer:
    monkeypatch.setattr(composition, "GeminiHTTPClient", lambda: transport)
    container = build_test_production_container(
        runtime_root=runtime_root,
        bootstrap_secret=_BOOTSTRAP_SECRET,
        service_instance_id=_SERVICE_INSTANCE_ID,
        mcp_module_name="tests.fakes.langgraph_e2e_mcp_server",
        keyring_store=SessionMemorySecretStore(),
        graph_profile=profile,
    )
    return replace(container, client_address_resolver=lambda _request: "127.0.0.1")


def bootstrap(
    client: TestClient,
    *,
    command_suffix: str = "initial",
    task_list_id: str = "task-list-e2e",
    github_repositories: tuple[str, ...] | None = None,
) -> None:
    bootstrap = client.post(
        "/api/v1/session/bootstrap",
        json={
            "schema_version": 1,
            "bootstrap_secret": _BOOTSTRAP_SECRET,
            "frontend_api_contract_version": "1",
        },
    )
    assert bootstrap.status_code == 200, bootstrap.text
    credential = client.put(
        "/api/v1/credentials/llm/gemini",
        json={
            "schema_version": 1,
            "command_id": f"e2e-store-gemini-{command_suffix}",
            "api_key": "e2e-gemini-key",
            "storage_mode": "SESSION_ONLY",
        },
    )
    assert credential.status_code == 200, credential.text
    settings = client.put(
        "/api/v1/settings",
        headers={"X-API-Contract-Version": "1"},
        json={
            "schema_version": 1,
            "command_id": "e2e-settings",
            "settings_patch": {
                "schema_version": 1,
                "preferred_llm_mode": "API_LLM",
                "external_llm_consent": True,
                "selected_tasklist_ids": [task_list_id],
                "selected_calendar_ids": ["calendar-e2e"],
                "selected_github_repositories": github_repositories,
            },
        },
    )
    assert settings.status_code == 200, settings.text


def create_conversation(client: TestClient, suffix: str) -> str:
    response = client.post(
        "/api/v1/conversations",
        json={
            "schema_version": 1,
            "command_id": f"create-conversation-{suffix}",
            "title": f"E2E {suffix}",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["conversation_id"])


def start_run(
    client: TestClient,
    conversation_id: str,
    request_text: str,
    *,
    entry_mode: str = "AGENT_SEARCH",
    selected_resource_handles: list[str] | None = None,
) -> str:
    response = client.post(
        "/api/v1/runs",
        json={
            "api_contract_version": "1",
            "command_id": f"start-{request_text.split(':', maxsplit=1)[-1].split()[0].lower()}",
            "conversation_id": conversation_id,
            "request_text": request_text,
            "entry_mode": entry_mode,
            "selected_resource_handles": selected_resource_handles or [],
            "requested_mode": "API_LLM",
        },
    )
    assert response.status_code == 202, response.text
    return str(response.json()["run_id"])


def approve_action(
    client: TestClient,
    action: dict[str, object],
    command_id: str,
    *,
    calendar_conflict_acknowledged: bool = False,
) -> None:
    response = client.post(
        f"/api/v1/actions/{action['action_id']}/approve",
        json={
            "api_contract_version": "1",
            "command_id": command_id,
            "expected_version": action["version"],
            "calendar_conflict_acknowledged": calendar_conflict_acknowledged,
        },
    )
    assert response.status_code == 200, response.text


def reject_action(client: TestClient, action: dict[str, object], command_id: str) -> None:
    response = client.post(
        f"/api/v1/actions/{action['action_id']}/reject",
        json={
            "api_contract_version": "1",
            "command_id": command_id,
            "expected_version": action["version"],
            "reason_code": "USER_REJECTED",
        },
    )
    assert response.status_code == 200, response.text


def wait_for_status(
    client: TestClient,
    run_id: str,
    expected: set[str],
    *,
    timeout_seconds: float = 20,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v1/runs/{run_id}",
            headers={"X-API-Contract-Version": "1"},
        )
        assert response.status_code == 200, response.text
        last = cast(dict[str, object], response.json())
        run = last.get("run")
        if isinstance(run, dict) and run.get("status") in expected:
            return last
        time.sleep(0.02)
    raise AssertionError(f"run did not reach {sorted(expected)}: {last}")


def wait_for_action_status(
    client: TestClient,
    run_id: str,
    expected: set[str],
    *,
    timeout_seconds: float = 20,
    required_command: str | None = None,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v1/runs/{run_id}",
            headers={"X-API-Contract-Version": "1"},
        )
        assert response.status_code == 200, response.text
        last = cast(dict[str, object], response.json())
        actions = last.get("actions")
        if isinstance(actions, list) and any(
            isinstance(action, dict)
            and action.get("status") in expected
            and (
                required_command is None
                or required_command in action.get("next_allowed_commands", [])
            )
            for action in actions
        ):
            return last
        time.sleep(0.02)
    raise AssertionError(f"action did not reach {sorted(expected)}: {last}")


def mcp_events(runtime_root: Path) -> list[dict[str, object]]:
    path = runtime_root / "cache" / "langgraph-e2e-mcp-events.jsonl"
    assert path.is_file(), f"MCP event log was not created: {path}"
    return [cast(dict[str, object], json.loads(line)) for line in path.read_text().splitlines()]
