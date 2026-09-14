"""Initial missing LLM capability terminates through the production Graph and Domain."""

from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from tests.support.fakes import FakeOllamaTransport
from tests.support.langgraph_product_driver import API_HEADERS, create_conversation, wait_for_status
from tests.support.production_runtime import build_test_production_container

from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.api import composition
from google_work_agent.api.app import create_app
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)


@pytest.mark.parametrize(
    ("mode", "consent", "message"),
    [
        ("LOCAL_GPU", False, "로컬 AI 모델"),
        ("API_LLM", False, "외부 AI 전송 동의"),
        ("API_LLM", True, "API AI 연결"),
        ("LOCAL_GPU", False, None),
    ],
)
def test_initial_runtime_prerequisite__blocks_once__and_preserves_history_and_new_requests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str, consent: bool, message: str | None
) -> None:
    transport = FakeOllamaTransport()
    monkeypatch.setattr(composition, "OllamaHTTPClient", lambda: transport)
    container = build_test_production_container(
        runtime_root=tmp_path,
        bootstrap_secret="startup-test-bootstrap-secret-32-characters",
        mcp_module_name="tests.fakes.google_workspace_mcp_server",
        keyring_store=SessionMemorySecretStore(),
    )
    container = replace(container, client_address_resolver=lambda _: "127.0.0.1")
    if message is None:
        # A provider failure with the same code must not acquire admission semantics.
        monkeypatch.setattr(
            container.structured_inference_port,
            "infer",
            Mock(side_effect=LLMInvocationError(LLMErrorCode.LOCAL_UNAVAILABLE, "provider failed")),
        )
    with TestClient(create_app(container), base_url="http://127.0.0.1:8000") as client:
        client.headers.update({**API_HEADERS, "X-API-Contract-Version": "1"})
        response = client.post(
            "/api/v1/session/bootstrap",
            json={
                "schema_version": 1,
                "bootstrap_secret": "startup-test-bootstrap-secret-32-characters",
                "frontend_api_contract_version": "1",
            },
        )
        assert response.status_code == 200, response.text
        response = client.put(
            "/api/v1/settings",
            json={
                "schema_version": 1,
                "command_id": "startup-settings",
                "settings_patch": {"schema_version": 1, "external_llm_consent": consent},
            },
        )
        assert response.status_code == 200, response.text
        conversation_id = create_conversation(client, "runtime-unavailable")
        request: dict[str, Any] = {
            "api_contract_version": "1",
            "command_id": "missing-runtime",
            "conversation_id": conversation_id,
            "request_text": "회의 준비 방법을 설명해 줘",
            "entry_mode": "AGENT_SEARCH",
            "selected_resource_handles": [],
            "requested_mode": mode,
        }
        response = client.post("/api/v1/runs", json=request)
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        snapshot = cast(
            dict[str, Any], wait_for_status(client, run_id, {"BLOCKED", "RECOVERY_REQUIRED"})
        )
        if message is None:
            assert snapshot["run"]["status"] == "RECOVERY_REQUIRED"
            assert snapshot["actions"] == []
            return
        assert snapshot["run"]["status"] == "BLOCKED"
        assert snapshot["actions"] == []
        history = client.get(f"/api/v1/conversations/{conversation_id}/history").json()
        assistant = [item for item in history["messages"] if item["role"] == "ASSISTANT"]
        assert len(assistant) == 1 and message in assistant[0]["content"]
        assert "새로 요청" in assistant[0]["content"]
        replay = client.post("/api/v1/runs", json=request)
        assert replay.json()["run_id"] == run_id
        history = client.get(f"/api/v1/conversations/{conversation_id}/history").json()
        assert len([item for item in history["messages"] if item["role"] == "ASSISTANT"]) == 1
        assert client.get("/health/ready").json()["status"] == "READY"
        next_run = client.post("/api/v1/runs", json={**request, "command_id": "new-request"})
        assert next_run.status_code == 202 and next_run.json()["run_id"] != run_id
        assert (
            cast(
                dict[str, Any],
                wait_for_status(
                    client, next_run.json()["run_id"], {"BLOCKED", "RECOVERY_REQUIRED"}
                ),
            )["run"]["status"]
            == "BLOCKED"
        )
        assert not [call for call in transport.invocations if call["kind"] != "probe"]
