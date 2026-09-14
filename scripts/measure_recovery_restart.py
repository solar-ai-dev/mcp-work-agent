"""Controlled faults through production Graph/API/persistence; no live provider writes.

Crash scenarios terminate the worker process after committed BeginExecutionAttempt.
Only external LLM/MCP boundaries are faked; startup reconciliation is production code.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import asdict, replace
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
    build_container,
    create_conversation,
    start_run,
    wait_for_status,
)

from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import StdioMCPClientAdapter
from google_work_agent.adapters.langgraph.main.graph import WorkflowGraphComposition
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.api import composition
from google_work_agent.api.app import create_app
from google_work_agent.application.use_cases.sse_event.list_run_events import ListRunEventsQuery
from google_work_agent.ports.connector.mcp_client_port import MCPToolCallResultV1

SCENARIOS = (
    "response_loss",
    "lookup_unavailable",
    "restart_approval",
    "restart_terminal",
    "crash_before_write",
    "crash_after_write",
    "cancel_before_write",
    "cancel_after_write",
    "reauth_verification",
    "verification_mismatch",
)


def measure(
    root: Path, connector: str, scenario: str, *, restarted: bool = False
) -> dict[str, Any]:
    evidence_path = root / "measurement.json"
    report: dict[str, Any] = (
        json.loads(evidence_path.read_text(encoding="utf-8"))
        if restarted
        else {
            "connector": connector,
            "scenario": scenario,
            "validation": "CONTROLLED_FAULT",
            "external_provider": "FAKE",
            "model": "FAKE_EXTERNAL_LLM",
            "browser_e2e": "DEFERRED",
            "measurement_status": "INCOMPLETE",
            "calls": [],
        }
    )
    recorder = GraphPathRecorder()
    database = root / "data/google_work_agent.db"
    transport = LangGraphE2EGeminiTransport(
        task_payload={
            "title": "Settlement fixture",
            "notes": "Approved",
            "scheduled_date": "2026-09-10",
        },
        github_arguments={
            "repository": "bonggyulim/search-save",
            "title": "Settlement fixture",
            "body": "Approved",
        },
    )
    if connector == "google_workspace":
        transport.github_arguments = None
    else:
        transport.task_payload = None
    original_call, original_graph = StdioMCPClientAdapter.call_tool, WorkflowGraphComposition.build
    write_tool = "github_create_issue" if connector == "github" else "tasks_create_task"
    active_client: TestClient | None = None

    def save() -> None:
        report["node_path"] = report.get("prior_node_path", []) + recorder.path
        evidence_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

    def cancel() -> None:
        assert active_client is not None
        snapshot = active_client.get(f"/api/v1/runs/{report['run_id']}").json()
        response = active_client.post(
            f"/api/v1/runs/{report['run_id']}/cancel",
            json={
                "api_contract_version": "1",
                "command_id": "cancel-recovery-fixture",
                "expected_version": snapshot["run"]["version"],
            },
        )
        report["cancel_response"] = response.json()
        assert response.status_code == 200, response.text

    def call(self: Any, owner: str, tool: str, args: Any, timeout: int) -> Any:
        event: dict[str, Any] = {"connector": owner, "tool": tool, "after_restart": restarted}
        report["calls"].append(event)
        if (
            scenario == "reauth_verification"
            and tool == ("github_get_issue" if connector == "github" else "tasks_get_task")
            and not report.get("reauth_completed")
        ):
            event["status"] = "AUTH_REQUIRED"
            return MCPToolCallResultV1(
                1, tool, "ERROR", {"delivery_certainty": "NOT_SENT"}, "AUTH_REQUIRED"
            )
        if tool == write_tool:
            with sqlite3.connect(database) as db:
                row = db.execute(
                    "SELECT status FROM execution_attempts WHERE id=?",
                    (args["claim_context"]["execution_attempt_id"],),
                ).fetchone()
            assert row == ("EXECUTING",), row
            event["begin_committed"] = True
            save()
            if scenario == "crash_before_write" and not restarted:
                os._exit(86)
        result = original_call(self, owner, tool, args, timeout)
        event["status"] = result.transport_status
        if scenario == "verification_mismatch" and tool == (
            "github_get_issue" if connector == "github" else "tasks_get_task"
        ):
            observed = json.loads(json.dumps(result.payload))
            observed["item"]["payload"]["title"] = "Unexpected provider result"
            return replace(result, payload=observed)
        if tool == write_tool:
            assert result.transport_status == "OK", result
            event["external_response_received"] = True
            save()
            if scenario == "crash_after_write" and not restarted:
                os._exit(86)
            if scenario == "cancel_after_write":
                cancel()
            if scenario in {"response_loss", "lookup_unavailable"}:
                return replace(
                    result,
                    transport_status="TIMEOUT",
                    error_code="TIMEOUT",
                    payload={"delivery_certainty": "SENT_RESPONSE_LOST"},
                )
        return result

    def open_client(patch: pytest.MonkeyPatch, suffix: str) -> tuple[Any, TestClient]:
        container = build_container(
            root, transport=transport, monkeypatch=patch, profile=GraphProfile.SIX_ROLE_BASELINE
        )
        client = TestClient(
            create_app(container=container), base_url="http://127.0.0.1:8000", headers=API_HEADERS
        )
        client.__enter__()
        bootstrap(
            client,
            command_suffix=suffix,
            github_repositories=("bonggyulim/search-save",) if connector == "github" else None,
        )
        if connector == "google_workspace":
            path = root / "cache/langgraph-e2e-mcp-state.json"
            fixture = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            fixture["task_fixture_mode"] = True
            path.write_text(json.dumps(fixture), encoding="utf-8")
        return container, client

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition, "GITHUB_MCP_MODULE", "tests.fakes.github_write_mcp")
        patch.setattr(StdioMCPClientAdapter, "call_tool", call)
        patch.setattr(
            WorkflowGraphComposition,
            "build",
            lambda self: original_graph(self).with_config(callbacks=[recorder]),
        )
        if scenario == "lookup_unavailable":
            assert connector == "github"
            (root / "github-lookup-unavailable").touch()
        container, active_client = open_client(patch, "restart" if restarted else "initial")
        try:
            if not restarted:
                request = (
                    "E2E:GITHUB_CREATE GitHub bonggyulim/search-save 이슈 생성"
                    if connector == "github"
                    else "E2E:APPROVED_WRITE 태스크를 만들어줘. 승인할 업무 값: "
                    + json.dumps(transport.task_payload, ensure_ascii=False)
                )
                conversation = create_conversation(active_client, "recovery")
                run_id = start_run(active_client, conversation, request)
                # Exact command replay must return the original Run, not allocate another.
                assert start_run(active_client, conversation, request) == run_id
                report["run_id"] = run_id
                waiting = cast(
                    dict[str, Any],
                    wait_for_status(
                        active_client, run_id, {"WAITING_APPROVAL"}, timeout_seconds=40
                    ),
                )
                report["before_approval"] = waiting
                report["action"] = waiting["actions"][0]
                assert not any(c["tool"] == write_tool for c in report["calls"])
                save()
                if scenario == "restart_approval":
                    active_client.__exit__(None, None, None)
                    container, active_client = open_client(patch, "approval-restart")
                    refreshed = active_client.get(f"/api/v1/runs/{run_id}").json()
                    assert refreshed["actions"] == waiting["actions"]
                if scenario == "cancel_before_write":
                    cancel()
                else:
                    approve_action(active_client, report["action"], "approve-recovery")
                    approve_action(active_client, report["action"], "approve-recovery")
            run_id = report["run_id"]
            if scenario == "reauth_verification":
                paused = cast(
                    dict[str, Any],
                    wait_for_status(
                        active_client,
                        run_id,
                        {"REAUTH_REQUIRED", "RECOVERY_REQUIRED"},
                        timeout_seconds=20,
                    ),
                )
                report["reauth_pause"] = paused
                assert paused["run"]["status"] == "REAUTH_REQUIRED", paused
                report["reauth_completed"] = True
                resumed = active_client.post(
                    f"/api/v1/runs/{run_id}/resume",
                    json={
                        "api_contract_version": "1",
                        "command_id": "reauth-completed",
                        "expected_version": paused["run"]["version"],
                        "resume_kind": "REAUTH_COMPLETED",
                    },
                )
                report["reauth_response"] = resumed.json()
                assert resumed.status_code == 200, resumed.text
            final = cast(
                dict[str, Any],
                wait_for_status(
                    active_client,
                    run_id,
                    {"COMPLETED", "RECOVERY_REQUIRED", "CANCELLED", "FAILED", "BLOCKED"}
                    | (
                        {"WAITING_APPROVAL"}
                        if restarted and scenario == "crash_before_write"
                        else set()
                    ),
                    timeout_seconds=40,
                ),
            )
            report["final"] = final
            if scenario == "lookup_unavailable":
                for index in range(2):
                    before_recheck = len(report["calls"])
                    current = active_client.get(f"/api/v1/runs/{run_id}").json()
                    response = active_client.post(
                        f"/api/v1/runs/{run_id}/resume",
                        json={
                            "api_contract_version": "1",
                            "command_id": f"recheck-{index}",
                            "expected_version": current["run"]["version"],
                            "resume_kind": "RECOVERY_RECHECK",
                        },
                    )
                    report.setdefault("rechecks", []).append(response.json())
                    assert response.json()["result_code"] == "NO_PROGRESS", response.text
                    if index == 1:
                        assert len(report["calls"]) == before_recheck
                assert len([c for c in report["calls"] if c["tool"] == write_tool]) == 1
            if scenario != "cancel_before_write":
                approve_action(active_client, report["action"], "approve-recovery")
            events = container.list_run_events_handler(ListRunEventsQuery(run_id))
            report["sse"] = asdict(events)
            if events.events:
                resumed_events = container.list_run_events_handler(
                    ListRunEventsQuery(run_id, events.events[-1].event_id)
                )
                report["sse_reconnect"] = asdict(resumed_events)
                assert {e.event_id for e in events.events}.isdisjoint(
                    e.event_id for e in resumed_events.events
                )
            snapshot = active_client.get(f"/api/v1/runs/{run_id}").json()
            assert snapshot["messages"] == final["messages"]
            if scenario == "restart_terminal":
                assert events.events
                cursor = events.events[-1].event_id
                calls_before_restart = len(report["calls"])
                active_client.__exit__(None, None, None)
                container, active_client = open_client(patch, "terminal-restart")
                after = active_client.get(f"/api/v1/runs/{run_id}").json()
                assert after["messages"] == final["messages"]
                assert after["run"] == final["run"]
                replay = container.list_run_events_handler(ListRunEventsQuery(run_id, cursor))
                report["sse_after_restart"] = asdict(replay)
                assert replay.cursor_status == "CURSOR_EXPIRED"
                assert not any(
                    c["tool"] == write_tool for c in report["calls"][calls_before_restart:]
                )
            with sqlite3.connect(database) as db:
                db.row_factory = sqlite3.Row
                report["attempts"] = [
                    dict(r)
                    for r in db.execute(
                        "SELECT id,status,response_metadata_json,error_code,error_detail_json "
                        "FROM execution_attempts"
                    )
                ]
                report["verification"] = [
                    dict(r)
                    for r in db.execute(
                        "SELECT status,expected_json,actual_json FROM verifications"
                    )
                ]
                report["handoffs"] = [
                    dict(r)
                    for r in db.execute(
                        "SELECT handoff_id,status,checkpoint_id FROM workflow_handoffs"
                    )
                ]
                report["terminal_messages"] = db.execute(
                    "SELECT COUNT(*) FROM messages WHERE run_id=? AND role='ASSISTANT'", (run_id,)
                ).fetchone()[0]
                report["llm_calls"] = [
                    json.loads(r[0])["attributes"]
                    for r in db.execute(
                        "SELECT payload_json FROM trace_events "
                        "WHERE run_id=? AND event_type='LLM_CALL_COMPLETED' ORDER BY id",
                        (run_id,),
                    )
                ]
            writes = [c for c in report["calls"] if c["tool"] == write_tool]
            expected = 0 if scenario == "cancel_before_write" else 1
            assert len(writes) == expected, writes
            assert len(report["attempts"]) == expected
            if connector == "github":
                path = root / "github-fixture-issues.json"
                resources = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                report["external_effect_count"] = len(resources)
            else:
                resources = json.loads(
                    (root / "cache/langgraph-e2e-mcp-state.json").read_text(encoding="utf-8")
                )
                report["external_effect_count"] = len(
                    [
                        r
                        for r in resources.get("resources", {}).values()
                        if r["resource_type"] == "task"
                        and r["payload"].get("title") == "Settlement fixture"
                    ]
                )
            assert report["external_effect_count"] == (
                0 if scenario == "crash_before_write" else expected
            )
            assert final["run"]["actual_runtime"] == "API_LLM"
            nodes = [e["node"] for e in report.get("prior_node_path", []) + recorder.path]
            assert nodes.count("planning") == nodes.count("review") == 1
            assert nodes.index("planning") < nodes.index("review")
            assert all(c.get("begin_committed") for c in writes)
            if scenario in {"lookup_unavailable", "crash_before_write", "verification_mismatch"}:
                if final["run"]["status"] == "WAITING_APPROVAL":
                    assert scenario == "crash_before_write"
                    assert report["attempts"][0]["status"] == "FAILED"
                    assert report["attempts"][0]["error_code"] == "RECOVERY_CONFIRMED_NOT_EXECUTED"
                    assert "PREPARE_WRITE_RETRY" in final["actions"][0]["next_allowed_commands"]
                    report["continuation"] = "FAILWAIT_USER_DECISION_NO_AUTOMATIC_RETRY"
                else:
                    assert final["run"]["status"] in {"RECOVERY_REQUIRED", "FAILED"}, final
                assert not any(v["status"] == "VERIFIED" for v in report["verification"])
                if scenario == "verification_mismatch":
                    assert any(v["status"] == "MISMATCH" for v in report["verification"])
            elif scenario != "cancel_before_write":
                assert any(v["status"] == "VERIFIED" for v in report["verification"]), report[
                    "verification"
                ]
                assert final["run"]["status"] in {"COMPLETED", "CANCELLED"}, final
            if restarted and scenario == "crash_after_write":
                assert not any(e["node"] == "action_execution" for e in recorder.path), (
                    recorder.path
                )
            assert report["terminal_messages"] <= 1
            if final["run"]["status"] in {"COMPLETED", "CANCELLED", "FAILED"}:
                assert report["terminal_messages"] == 1
            report["measurement_status"] = "PASS"
        finally:
            save()
            active_client.__exit__(None, None, None)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="response_loss")
    parser.add_argument("--connector", choices=("github", "google_workspace"), default="github")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    root = args.root or Path(tempfile.mkdtemp(prefix="gwa-recovery-closure-"))
    restart = False
    if args.scenario.startswith("crash_") and not args.worker:
        worker = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.measure_recovery_restart",
                "--root",
                str(root),
                "--scenario",
                args.scenario,
                "--connector",
                args.connector,
                "--worker",
            ],
            check=False,
        )
        assert worker.returncode == 86, worker.returncode
        previous = json.loads((root / "measurement.json").read_text(encoding="utf-8"))
        previous["prior_node_path"] = previous["node_path"]
        (root / "measurement.json").write_text(json.dumps(previous), encoding="utf-8")
        restart = True
    result = measure(root, args.connector, args.scenario, restarted=restart)
    print(
        json.dumps(
            {k: result[k] for k in ("run_id", "scenario", "connector", "measurement_status")}
            | {"evidence_path": str(root / "measurement.json")},
            ensure_ascii=False,
        )
    )
