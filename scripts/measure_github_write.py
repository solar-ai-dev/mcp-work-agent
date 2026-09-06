"""Measure production GitHub Graph/Approval/MCP with optional live provider and Ollama.

Only the explicitly allowed private test repository is writable. Existing issues
are never mutated; UPDATE/CLOSE/REOPEN are restricted to this invocation's CREATE.
Browser/Device Flow interaction is not certified by this script.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from tests.support.fakes.langgraph_e2e import LangGraphE2EGeminiTransport
from tests.support.graph_path_recorder import GraphPathRecorder
from tests.support.langgraph_product_driver import (
    API_HEADERS,
    approve_action,
    bootstrap,
    create_conversation,
    reject_action,
    wait_for_status,
)

from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import StdioMCPClientAdapter
from google_work_agent.adapters.langgraph.main.graph import WorkflowGraphComposition
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.api import composition
from google_work_agent.api.app import create_app
from google_work_agent.api.security.cookies import local_session_cookie_name
from google_work_agent.api.security.sessions import calculate_session_digest
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandleCommand,
)
from google_work_agent.ports.connector.oauth_credential_port import OAuthEnvironment

REPOSITORY = "bonggyulim/search-save"
BOOTSTRAP_SECRET = "langgraph-real-production-e2e-bootstrap"
SERVICE_ID = "langgraph-real-production-e2e-service"


def measure_github(
    root: Path,
    *,
    live: bool,
    real_model: bool,
    resume_evidence: Path | None = None,
    resume_from: str | None = None,
) -> dict[str, Any]:
    if resume_from is not None:
        assert resume_evidence is not None
    prior: dict[str, Any] | None = None
    if resume_evidence is not None:
        assert live, "Resuming fixture REST state is unsupported"
        prior = json.loads(resume_evidence.read_text(encoding="utf-8"))
        assert prior["live_github"] and prior["repository"] == REPOSITORY
        created = prior["runs"][0]
        assert created["scenario"] == "create" and created["measurement_status"] == "PASS"
        assert created["verification"] and all(
            v["status"] == "VERIFIED" for v in created["verification"]
        )
        assert prior["created_issue"].startswith(f"https://github.com/{REPOSITORY}/issues/")
    transport = LangGraphE2EGeminiTransport(github_arguments={"repository": REPOSITORY})
    recorder = GraphPathRecorder()
    calls: list[dict[str, Any]] = []
    clients: dict[str, StdioMCPClientAdapter] = {}
    original_call = StdioMCPClientAdapter.call_tool
    original_graph = WorkflowGraphComposition.build
    original_infer = StructuredInferenceRuntimeRouter.infer
    inferred: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "live_github": live,
        "requested_model": "qwen3.5:9b" if real_model else "FAKE_EXTERNAL_LLM",
        "browser_e2e": "PENDING",
        "device_flow_login": "EXISTING_CONNECTION_REUSED",
        "repository": REPOSITORY,
        "runs": [],
        "measurement_status": "INCOMPLETE",
    }

    def observe_call(self: Any, connector: str, tool: str, args: Any, timeout: int) -> Any:
        clients[connector] = self
        event: dict[str, Any] = {"connector": connector, "tool": tool}
        if tool in {
            "github_create_issue",
            "github_update_issue",
            "github_close_issue",
            "github_reopen_issue",
        }:
            event["arguments"] = {k: v for k, v in args.items() if k != "claim_context"}
            with sqlite3.connect(root / "data/google_work_agent.db") as db:
                claim = args["claim_context"]
                row = db.execute(
                    "SELECT status FROM execution_attempts WHERE id=? AND approval_id=?",
                    (claim["execution_attempt_id"], claim["approval_id"]),
                ).fetchone()
            event["begin_committed"] = row is not None and row[0] == "EXECUTING"
            assert event["begin_committed"], "Write observed before committed BeginExecutionAttempt"
        result = original_call(self, connector, tool, args, timeout)
        event["transport_status"] = result.transport_status
        calls.append(event)
        return result

    def observe_infer(self: Any, mode: Any, prompt: Any, projection: Any, schema: Any) -> Any:
        if prompt.prompt_id == "review.inspect_goal_and_evidence":
            available = {item.get("evidence_id") for item in projection["evidence"]}
            for action in projection["planning_result"].get("actions", []):
                assert set(action["evidence_refs"]).issubset(available), (
                    "Review lost Action evidence"
                )
        result = original_infer(self, mode, prompt, projection, schema)
        if (
            prompt.prompt_id.startswith("tool_routing.")
            or prompt.prompt_id == "retrieval.assess_sufficiency"
        ):
            inferred.append({"prompt": prompt.prompt_id, "output": result.structured_output})
        return result

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition, "GeminiHTTPClient", lambda: transport)
        patch.setattr(StdioMCPClientAdapter, "call_tool", observe_call)
        patch.setattr(StructuredInferenceRuntimeRouter, "infer", observe_infer)
        patch.setattr(
            WorkflowGraphComposition,
            "build",
            lambda self: original_graph(self).with_config(
                callbacks=[recorder],
            ),
        )
        if not live:
            patch.setattr(composition, "GITHUB_MCP_MODULE", "tests.fakes.github_write_mcp")
        container = composition.build_production_runtime(
            runtime_root=root,
            working_directory=Path.cwd(),
            mcp_manifest_version="2026-08-07.p0",
            bootstrap_secret=BOOTSTRAP_SECRET,
            service_instance_id=SERVICE_ID,
            release_version="0.1.0-test",
            build_channel="TEST",
            deployment_profile="LOCAL_CAPABLE",
            oauth_environment=OAuthEnvironment.DEVELOPMENT,
            oauth_client_id="test-client-id",
            github_oauth_client_id="Iv23liYV2mScbAiVwc5Y" if live else "fixture-client-id",
            github_oauth_scope="",
            api_contract_version="1",
            policy_version="2026-08-06.p0",
            database_migration_version="development-latest",
            configuration_source="EXPLICIT_DEVELOPMENT",
            mcp_module_name="tests.fakes.langgraph_e2e_mcp_server",
            keyring_store=SessionMemorySecretStore(),
        )
        container = replace(container, client_address_resolver=lambda _request: "127.0.0.1")
        with TestClient(
            create_app(container), base_url="http://127.0.0.1:8000", headers=API_HEADERS
        ) as client:
            bootstrap(client)
            status = client.get("/api/v1/connections/github/status").json()
            report["connection"] = status
            assert status["connection_status"] == "CONNECTED", status
            listed = client.get(
                "/api/v1/connections/github/repositories",
                headers={
                    "X-API-Contract-Version": "1",
                },
            ).json()
            assert any(r["repository"] == REPOSITORY for r in listed["items"]), listed
            report["repository_list"] = listed
            number: int | None = None
            tag = uuid.uuid4().hex[:8]
            title = f"[MCP E2E 5.5 {tag}] GitHub 승인 검증"
            scenarios: tuple[str, ...] = (
                "create",
                "list",
                "read",
                "update",
                "close",
                "reopen",
                "reject",
            )
            if prior is not None:
                number = int(prior["created_issue"].rsplit("/", 1)[1])
                assert number > 0
                title = prior["runs"][0]["approvals"][0]["title"]
                assert title.startswith("[MCP E2E 5.5 ")
                report["created_issue"] = prior["created_issue"]
                report["prior_create_evidence"] = str(resume_evidence)
                scenarios = scenarios[1:]
                if all(
                    any(
                        r["scenario"] == read and r.get("measurement_status") == "PASS"
                        for r in prior["runs"]
                    )
                    for read in ("list", "read")
                ):
                    report["prior_read_evidence"] = str(resume_evidence)
                    scenarios = scenarios[2:]
            if resume_from is not None:
                scenarios = scenarios[scenarios.index(resume_from) :]
                report["resume_from"] = resume_from
            for scenario in scenarios:
                is_read = scenario in {"read", "list"}
                action_kind = "update" if scenario == "reject" else "read" if is_read else scenario
                arguments: dict[str, Any] = {"repository": REPOSITORY}
                if scenario == "create":
                    arguments.update(title=title, body="제품 승인 경로의 테스트 Issue입니다.")
                elif not is_read:
                    assert number is not None
                    arguments["issue_number"] = number
                    if action_kind == "update":
                        arguments.update(title=title + " 수정", body="승인한 수정 내용입니다.")
                transport.github_arguments = arguments
                tool = f"github_{action_kind}_issue" if not is_read else "github_get_issue"
                transport.github_tool_id = tool
                handles: list[str] = []
                before_read = None
                if number is not None and scenario != "list":
                    response = clients["github"].call_tool(
                        "github",
                        "github_get_issue",
                        {
                            "repository": REPOSITORY,
                            "issue_number": number,
                        },
                        30_000,
                    )
                    assert response.transport_status == "OK", response.error_code
                    before_read = cast(dict[str, Any], response.payload)["item"]
                    if prior is not None:
                        assert before_read["payload"]["title"] in {title, title + " 수정"}
                    cookie = client.cookies.get(
                        local_session_cookie_name(container.service_instance_id)
                    )
                    assert cookie and container.issue_selection_handle
                    handles.append(
                        container.issue_selection_handle(
                            IssueSelectionHandleCommand(
                                session_digest=calculate_session_digest(cookie),
                                account_id=status["account_id"],
                                connector_id="github",
                                resource_type="github_issue",
                                resource_id=f"{REPOSITORY}#{number}",
                                parent_resource_id=REPOSITORY,
                                version_token=before_read["version"],
                            )
                        )
                    )
                start_index, node_index = len(calls), len(recorder.path)
                inference_index = len(inferred)
                request = (
                    ("" if real_model else f"E2E:GITHUB_{action_kind.upper()} ")
                    + f"GitHub {REPOSITORY} 저장소에서 "
                    + (
                        {
                            "create": "새 Issue를 생성해줘",
                            "read": "Issue 목록을 조회해줘"
                            if scenario == "list"
                            else "선택한 Issue의 내용을 알려줘",
                            "update": "선택한 Issue의 제목과 본문을 수정해줘",
                            "close": "선택한 Issue를 닫아줘",
                            "reopen": "선택한 Issue를 다시 열어줘",
                        }[action_kind]
                    )
                    + (
                        ". 제목과 본문은 다음 값의 글자와 띄어쓰기를 그대로 사용해. 적용할 값: "
                        if action_kind in {"create", "update"}
                        else ". 대상: "
                    )
                    + (json.dumps(arguments, ensure_ascii=False) if not is_read else REPOSITORY)
                )
                started = client.post(
                    "/api/v1/runs",
                    json={
                        "api_contract_version": "1",
                        "command_id": f"start-{scenario}",
                        "conversation_id": create_conversation(client, scenario),
                        "request_text": request,
                        "entry_mode": "RESOURCE_SELECTED" if handles else "AGENT_SEARCH",
                        "selected_resource_handles": handles,
                        "requested_mode": "LOCAL_GPU" if real_model else "API_LLM",
                    },
                )
                assert started.status_code == 202, started.text
                run_id = started.json()["run_id"]
                run_report: dict[str, Any] = {"scenario": scenario, "run_id": run_id}
                report["runs"].append(run_report)
                waiting = cast(
                    dict[str, Any],
                    wait_for_status(
                        client,
                        run_id,
                        {
                            "WAITING_APPROVAL",
                            "WAITING_CONFIRMATION",
                            "COMPLETED",
                            "FAILED",
                            "BLOCKED",
                            "RECOVERY_REQUIRED",
                        },
                        timeout_seconds=300 if real_model else 40,
                    ),
                )
                run_report["before_approval"] = waiting
                run_report["semantic_decisions"] = inferred[inference_index:]
                run_report["node_path"] = recorder.path[node_index:]
                with sqlite3.connect(root / "data/google_work_agent.db") as db:
                    run_report["model_calls"] = [
                        json.loads(row[0])["attributes"]
                        for row in db.execute(
                            "SELECT payload_json FROM trace_events WHERE run_id=? "
                            "AND event_type='LLM_CALL_COMPLETED' ORDER BY created_at_ms",
                            (run_id,),
                        )
                    ]
                if real_model:
                    assert run_report["model_calls"] and all(
                        call["model"] == "qwen3.5:9b" and call["actual_runtime"] == "LOCAL_GPU"
                        for call in run_report["model_calls"]
                    ), run_report["model_calls"]
                (root / "measurement.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
                )
                assert not any("arguments" in c for c in calls[start_index:]), calls[start_index:]
                if not is_read:
                    assert waiting["run"]["status"] == "WAITING_APPROVAL", waiting
                    assert len(waiting["actions"]) == 1, waiting["actions"]
                    action = waiting["actions"][0]
                    assert action["tool_name"] == tool and action["arguments"] == arguments, action
                    if scenario == "reject":
                        reject_action(client, action, "reject-github")
                    else:
                        approve_action(client, action, f"approve-{scenario}")
                        approve_action(client, action, f"approve-{scenario}")
                else:
                    assert waiting["run"]["status"] == "COMPLETED", waiting
                final = cast(
                    dict[str, Any],
                    wait_for_status(
                        client,
                        run_id,
                        {
                            "COMPLETED",
                            "FAILED",
                            "BLOCKED",
                            "RECOVERY_REQUIRED",
                        },
                        timeout_seconds=300 if real_model else 40,
                    ),
                )
                run_report["final"] = final
                if is_read and real_model:
                    answer = "\n".join(
                        message["content"]
                        for message in final["messages"]
                        if message["role"] == "ASSISTANT"
                    )
                    assert REPOSITORY in answer and title in answer, answer
                run_report["node_path"] = recorder.path[node_index:]
                run_report["connector_path"] = calls[start_index:]
                nodes = [event["node"] for event in run_report["node_path"]]
                assert "request_understanding" in nodes
                if not is_read:
                    assert nodes.index("planning") < nodes.index("review")
                if scenario == "create":
                    assert "retrieval" not in nodes, nodes
                with sqlite3.connect(root / "data/google_work_agent.db") as db:
                    approvals = [
                        json.loads(r[0])
                        for r in db.execute(
                            "SELECT ap.arguments_snapshot_json FROM approvals ap "
                            "JOIN actions a ON a.id=ap.action_id "
                            "JOIN plans p ON p.id=a.plan_id WHERE p.run_id=?",
                            (run_id,),
                        )
                    ]
                    verifications = list(
                        db.execute(
                            "SELECT v.status,v.expected_json,v.actual_json FROM verifications v "
                            "JOIN execution_attempts ea ON ea.id=v.execution_attempt_id "
                            "JOIN approvals ap ON ap.id=ea.approval_id "
                            "JOIN actions a ON a.id=ap.action_id JOIN plans p ON p.id=a.plan_id "
                            "WHERE p.run_id=?",
                            (run_id,),
                        )
                    )
                    run_report["approvals"] = approvals
                    run_report["verification"] = [
                        {
                            "status": r[0],
                            "expected": json.loads(r[1]),
                            "actual": json.loads(r[2]) if r[2] else None,
                        }
                        for r in verifications
                    ]
                    if scenario == "create":
                        found = db.execute(
                            "SELECT resource_id FROM resource_refs WHERE run_id=? "
                            "AND connector_id='github'",
                            (run_id,),
                        ).fetchall()
                        assert len(found) == 1, found
                        number = int(found[0][0].rsplit("#", 1)[1])
                        report["created_issue"] = f"https://github.com/{REPOSITORY}/issues/{number}"
                writes = [c for c in calls[start_index:] if "arguments" in c]
                expected_count = 0 if is_read or scenario == "reject" else 1
                assert len(writes) == expected_count and all(
                    c["begin_committed"] for c in writes
                ), writes
                assert approvals == ([] if expected_count == 0 else [arguments]), approvals
                if expected_count:
                    assert verifications and all(v[0] == "VERIFIED" for v in verifications), (
                        verifications
                    )
                assert final["run"]["status"] == "COMPLETED", final
                run_report["measurement_status"] = "PASS"
                (root / "measurement.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
            if not real_model and not live:
                for scenario in (
                    "missing_repository",
                    "conflicting_repository",
                    "disconnected",
                    "google_only",
                ):
                    transport.github_arguments = (
                        {"repository": "solar-ai-dev/pv-fusion"}
                        if scenario == "conflicting_repository"
                        else {}
                    )
                    if scenario == "disconnected":
                        (root / "github-disconnected").touch()
                        transport.github_arguments = {"repository": REPOSITORY}
                    repo = transport.github_arguments.get("repository", "")
                    if scenario == "google_only":
                        transport.github_arguments = None
                    call_start, node_start = len(calls), len(recorder.path)
                    selected = handles if scenario == "conflicting_repository" else []
                    started = client.post(
                        "/api/v1/runs",
                        json={
                            "api_contract_version": "1",
                            "command_id": scenario,
                            "conversation_id": create_conversation(client, scenario),
                            "request_text": "E2E:TASKS_READ 태스크를 조회해줘"
                            if scenario == "google_only"
                            else f"E2E:GITHUB_READ {repo} 저장소의 이슈를 조회해줘",
                            "entry_mode": "RESOURCE_SELECTED" if selected else "AGENT_SEARCH",
                            "selected_resource_handles": selected,
                            "requested_mode": "API_LLM",
                        },
                    )
                    assert started.status_code == 202, started.text
                    run_id = started.json()["run_id"]
                    final = wait_for_status(
                        client,
                        run_id,
                        {
                            "WAITING_CONFIRMATION",
                            "COMPLETED",
                            "BLOCKED",
                            "FAILED",
                            "REAUTH_REQUIRED",
                        },
                    )
                    run_calls = calls[call_start:]
                    assert not any(c["tool"].startswith("github_") for c in run_calls), run_calls
                    assert cast(dict[str, Any], final["run"])["status"] == (
                        "COMPLETED"
                        if scenario in {"disconnected", "google_only"}
                        else "WAITING_CONFIRMATION"
                    ), final
                    if scenario == "google_only":
                        assert any(c["tool"] == "tasks_list_tasks" for c in run_calls), run_calls
                    report["runs"].append(
                        {
                            "scenario": scenario,
                            "run_id": run_id,
                            "final": final,
                            "node_path": recorder.path[node_start:],
                            "connector_path": run_calls,
                            "measurement_status": "PASS",
                        }
                    )
    report["measurement_status"] = "PASS"
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-github", action="store_true")
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument("--resume-evidence", type=Path)
    parser.add_argument("--resume-from", choices=("update", "close", "reopen", "reject"))
    options = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="gwa-github-closure-"))
    print(f"EVIDENCE_ROOT={root}", flush=True)
    result = measure_github(
        root,
        live=options.live_github,
        real_model=options.real_model,
        resume_evidence=options.resume_evidence,
        resume_from=options.resume_from,
    )
    evidence = root / "measurement.json"
    evidence.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": result["measurement_status"],
                "live_github": options.live_github,
                "runs": [
                    {"scenario": r["scenario"], "run_id": r["run_id"]} for r in result["runs"]
                ],
                "evidence": str(evidence),
            },
            ensure_ascii=False,
        )
    )
