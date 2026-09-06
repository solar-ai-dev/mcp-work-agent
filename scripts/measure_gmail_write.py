"""Execute production Gmail LangGraph; only external LLM/MCP are fixtures.

No live mail is sent. Reports contain fixture-only content and never claim
cross-account receipt, actual-model quality, or browser E2E certification.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
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
    mcp_events,
    reject_action,
    start_run,
    wait_for_status,
)

from google_work_agent.adapters.langgraph.main.graph import WorkflowGraphComposition
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.api.app import create_app
from google_work_agent.api.security.cookies import local_session_cookie_name
from google_work_agent.api.security.sessions import calculate_session_digest
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandleCommand,
)

SCENARIOS = (
    "draft",
    "send",
    "reply",
    "confirmation",
    "reject",
    "response_loss",
    "wrong_body",
    "extra_recipient",
    "wrong_thread",
    "not_sent",
    "update",
    "draft_send",
)


def measure_gmail(scenario: str, root: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "to": ["fixture-recipient@example.com"],
        "cc": ["fixture-cc@example.com"],
        "bcc": [],
        "subject": "E2E mail",
        "body": "검토 결과를 공유합니다.",
        "attachments": [],
        "thread_id": None,
        "in_reply_to": None,
        "references": None,
    }
    if scenario in {"reply", "wrong_thread"}:
        payload.update(
            thread_id="gmail-thread-e2e",
            in_reply_to="<source@example.com>",
            references="<source@example.com>",
        )
    if scenario == "response_loss":
        payload["subject"] += " RESPONSE_LOSS"
    arguments: dict[str, object] = {"payload": payload}
    if scenario in {"update", "draft_send"}:
        arguments["draft_id"] = "draft-existing"
    transport = LangGraphE2EGeminiTransport(gmail_arguments=arguments)
    recorder = GraphPathRecorder()
    original_build = WorkflowGraphComposition.build
    tool = (
        "gmail_create_draft"
        if scenario == "draft"
        else "gmail_update_draft"
        if scenario == "update"
        else "gmail_send"
    )
    report: dict[str, Any] = {
        "scenario": scenario,
        "verification_kind": "PRODUCTION_GRAPH_EXTERNAL_FIXTURES",
        "actual_model": "FAKE_EXTERNAL_LLM",
        "live_google": False,
        "browser_e2e": False,
        "cross_account": "PENDING",
    }
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            WorkflowGraphComposition,
            "build",
            lambda self: original_build(self).with_config(callbacks=[recorder]),
        )
        container = build_container(
            root,
            transport=transport,
            monkeypatch=patch,
            profile=GraphProfile.SIX_ROLE_BASELINE,
        )
        with TestClient(
            create_app(container), base_url="http://127.0.0.1:8000", headers=API_HEADERS
        ) as client:
            bootstrap(client)
            fixture_path = root / "cache/langgraph-e2e-mcp-state.json"
            fixture = json.loads(fixture_path.read_text()) if fixture_path.exists() else {}
            fixture["gmail_fixture_mode"] = True
            handles = []
            if scenario in {"update", "draft_send"}:
                fixture.setdefault("resources", {})["gmail_draft:draft-existing"] = {
                    "fixture_snapshot_id": "draft-existing",
                    "resource_type": "gmail_draft",
                    "resource_id": "draft-existing",
                    "parent_id": None,
                    "version": "v1",
                    "related_resource_ids": [],
                    "recovery_fingerprint": None,
                    "payload": {**payload, "body": "기존 초안 본문", "sent": False},
                }
                token = client.cookies.get(local_session_cookie_name(container.service_instance_id))
                assert token and container.issue_selection_handle
                account_id = container.current_account_id_provider()
                assert account_id
                handles.append(
                    container.issue_selection_handle(
                        IssueSelectionHandleCommand(
                            session_digest=calculate_session_digest(token),
                            account_id=account_id,
                            connector_id="google_workspace",
                            resource_type="gmail_draft",
                            resource_id="draft-existing",
                            parent_resource_id=None,
                            version_token="v1",
                        )
                    )
                )
            mutation = {
                "wrong_body": {"body": "unapproved body"},
                "extra_recipient": {"cc": ["unapproved@example.com"]},
                "wrong_thread": {"thread_id": "different-thread"},
                "not_sent": {"sent": False},
            }.get(scenario)
            if mutation:
                fixture["gmail_verification_mutation"] = mutation
            fixture_path.parent.mkdir(parents=True, exist_ok=True)
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            tag = {
                "draft": "GMAIL_DRAFT_CREATE",
                "reply": "GMAIL_REPLY",
                "wrong_thread": "GMAIL_REPLY",
                "update": "GMAIL_DRAFT_UPDATE",
                "confirmation": "GMAIL_CONFIRMATION",
            }.get(scenario, "GMAIL_SEND")
            request = (
                f"E2E:{tag} 다음 메일을 {'초안으로 작성' if scenario == 'draft' else '전송'}해줘: "
            )
            run_id = start_run(
                client,
                create_conversation(client, scenario),
                request + json.dumps(payload, ensure_ascii=False),
                entry_mode="RESOURCE_SELECTED" if handles else "AGENT_SEARCH",
                selected_resource_handles=handles,
            )
            report["run_id"] = run_id
            waiting = cast(
                dict[str, Any],
                wait_for_status(
                    client,
                    run_id,
                    {
                        "WAITING_APPROVAL",
                        "WAITING_CONFIRMATION",
                        "BLOCKED",
                        "COMPLETED",
                        "FAILED",
                    },
                    timeout_seconds=45,
                ),
            )
            if scenario == "confirmation":
                report["before_confirmation"] = waiting
                assert waiting["run"]["status"] == "WAITING_CONFIRMATION", waiting
                response = client.post(
                    f"/api/v1/runs/{run_id}/confirm",
                    json={
                        "api_contract_version": "1",
                        "command_id": "confirm-recipient",
                        "expected_version": waiting["run"]["version"],
                        "interrupt_id": waiting["pending_interrupt"]["interrupt_id"],
                        "response_kind": "FREE_TEXT",
                        "selected_option": None,
                        "free_text": "fixture-recipient@example.com에게 보내세요.",
                    },
                )
                assert response.status_code == 200, response.text
                waiting = cast(
                    dict[str, Any], wait_for_status(client, run_id, {"WAITING_APPROVAL", "BLOCKED"})
                )
            report["before_approval"] = waiting
            before_events = (
                mcp_events(root) if (root / "cache/langgraph-e2e-mcp-events.jsonl").exists() else []
            )
            report["writes_before_approval"] = sum(e["tool_name"] == tool for e in before_events)
            final = waiting
            if waiting["run"]["status"] == "WAITING_APPROVAL":
                action = waiting["actions"][0]
                if scenario == "reject":
                    reject_action(client, action, "reject-gmail")
                else:
                    approve_action(client, action, "approve-gmail")
                final = cast(
                    dict[str, Any],
                    wait_for_status(
                        client,
                        run_id,
                        {
                            "COMPLETED",
                            "RECOVERY_REQUIRED",
                            "BLOCKED",
                            "FAILED",
                        },
                        timeout_seconds=45,
                    ),
                )
                # Replaying the approval command must never dispatch another email.
                if scenario != "reject":
                    replay = client.post(
                        f"/api/v1/actions/{action['action_id']}/approve",
                        json={
                            "api_contract_version": "1",
                            "command_id": "approve-gmail",
                            "expected_version": action["version"],
                            "calendar_conflict_acknowledged": False,
                        },
                    )
                    report["approval_replay_http"] = replay.status_code
            report["final"] = final
    report["node_path"] = recorder.path
    report["prompt_path"] = [e["prompt_id"] for e in transport.invocations if e["kind"] == "invoke"]
    events = (
        cast(list[dict[str, Any]], mcp_events(root))
        if (root / "cache/langgraph-e2e-mcp-events.jsonl").exists()
        else []
    )
    report["connector_path"] = [
        {
            "tool": e["tool_name"],
            "begin_committed": e.get("begin_committed_before_write"),
            "arguments": {k: v for k, v in e["arguments"].items() if k != "claim_context"},
        }
        for e in events
    ]
    with sqlite3.connect(root / "data/google_work_agent.db") as db:
        db.row_factory = sqlite3.Row
        report["attempts"] = [
            dict(r)
            for r in db.execute(
                "SELECT id, approval_id, status, attempt_no FROM execution_attempts"
            )
        ]
        report["approvals"] = [
            json.loads(r[0]) for r in db.execute("SELECT arguments_snapshot_json FROM approvals")
        ]
        report["verification"] = [
            {
                "status": r[0],
                "expected": json.loads(r[1]),
                "actual": json.loads(r[2]) if r[2] else None,
            }
            for r in db.execute("SELECT status, expected_json, actual_json FROM verifications")
        ]
        report["audit_path"] = [
            r[0] for r in db.execute("SELECT event_type FROM audit_events ORDER BY id")
        ]
        report["delivery_certainty"] = [
            {"event": r[0], "delivery_certainty": metadata["delivery_certainty"]}
            for r in db.execute("SELECT event_type, metadata_json FROM audit_events ORDER BY id")
            if "delivery_certainty" in (metadata := json.loads(r[1]).get("attributes", {}))
        ]
    writes = [
        e
        for e in events
        if e["tool_name"] in {"gmail_send", "gmail_create_draft", "gmail_update_draft"}
    ]
    nodes = [str(e["node"]) for e in recorder.path]
    expected_order = [
        "request_understanding",
        "tool_route",
        "planning",
        "review",
        "domain_validation",
        "waiting_approval",
    ]
    if scenario != "reject":
        expected_order += ["action_execution", "verification"]
    cursor = iter(nodes)
    ordered = all(any(node == expected for node in cursor) for expected in expected_order)
    success = scenario not in {
        "reject",
        "response_loss",
        "wrong_body",
        "extra_recipient",
        "wrong_thread",
        "not_sent",
    }
    checks = {
        "reached_approval": report["before_approval"]["run"]["status"] == "WAITING_APPROVAL",
        "no_write_before_approval": report["writes_before_approval"] == 0,
        "exact_write_count": len(writes) == (0 if scenario == "reject" else 1),
        "no_hidden_draft_or_send": all(e["tool_name"] == tool for e in writes),
        "begin_committed": all(e.get("begin_committed_before_write") is True for e in writes),
        "node_order": ordered,
        "no_unnecessary_work_analysis": "work_analysis" not in nodes,
        "planning_count": nodes.count("planning") == 1,
        "review_count": nodes.count("review") == 1,
        "approved_arguments": report["approvals"] == ([] if scenario == "reject" else [arguments]),
        "execution_arguments": all(
            {
                **{
                    k: v for k, v in e["arguments"].items() if k not in {"claim_context", "payload"}
                },
                "payload": {
                    k: v
                    for k, v in e["arguments"]["payload"].items()
                    if k != "recovery_fingerprint"
                },
            }
            == arguments
            for e in writes
        ),
        "approval_replay": scenario == "reject" or report.get("approval_replay_http") == 200,
        "retrieval_skipped_when_unneeded": (
            "retrieval" not in nodes
            if scenario in {"draft", "send", "confirmation", "reject"}
            else True
        ),
        "read_scope": (
            any(e["tool_name"] == "gmail_search_threads" for e in events)
            if scenario == "reply"
            else True
        ),
        "typed_planning": any(
            "planning_result" in cast(dict[str, object], e.get("typed_results", {}))
            for e in recorder.path
        ),
    }
    if success:
        checks.update(
            verified=any(v["status"] == "VERIFIED" for v in report["verification"]),
            completed=report["final"]["run"]["status"] == "COMPLETED",
        )
    if mutation:
        checks["mismatch_detected"] = any(v["status"] == "MISMATCH" for v in report["verification"])
    if scenario == "response_loss":
        checks["unknown_not_resent"] = len(report["attempts"]) == 1 and len(writes) == 1
        checks["response_loss_recorded"] = any(
            e["delivery_certainty"] == "SENT_RESPONSE_LOST" for e in report["delivery_certainty"]
        )
        checks["recovered_by_read"] = any(
            e["tool_name"] == "search_by_recovery_fingerprint" for e in events
        ) and any(v["status"] == "VERIFIED" for v in report["verification"])
    if scenario == "confirmation":
        checks["same_run_continuation"] = report["before_confirmation"]["run"]["run_id"] == run_id
        checks["confirmation_before_planning"] = (
            report["before_confirmation"]["run"]["status"] == "WAITING_CONFIRMATION"
            and nodes.count("request_understanding") == 2
            and nodes.index("request_understanding", nodes.index("request_understanding") + 1)
            < nodes.index("planning")
        )
    report["checks"] = checks
    report["measurement_status"] = "PASS" if all(checks.values()) else "FAIL"
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=SCENARIOS, default="send")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="gwa-gmail-closure-"))
    result = measure_gmail(args.scenario, root)
    path = root / "measurement.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {k: result[k] for k in ("scenario", "run_id", "checks", "measurement_status")},
            ensure_ascii=False,
        )
    )
    print(path)
    raise SystemExit(0 if result["measurement_status"] == "PASS" else 1)
