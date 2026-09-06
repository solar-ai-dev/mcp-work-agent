"""Measure production Calendar Graph; external LLM/MCP are explicit fixtures.

No browser, live Google WRITE or actual-model quality certification is performed.
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
    wait_for_action_status,
    wait_for_status,
)

from google_work_agent.adapters.langgraph.main.graph import WorkflowGraphComposition
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.api.app import create_app

SCENARIOS = (
    "create",
    "mail",
    "timezone",
    "attendees",
    "reject",
    "conflict",
    "freebusy_failure",
    "events_failure",
    "response_loss",
    "wrong_calendar",
    "wrong_identity",
    "wrong_time",
    "wrong_description",
    "extra_attendee",
    "missing_attendee",
    "cancelled",
    "changed_conflict",
    "confirmation",
)


def measure_calendar(scenario: str, root: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "E2E Calendar 검증" + (" RESPONSE_LOSS" if scenario == "response_loss" else ""),
        "start": "2026-09-10T10:00:00+09:00",
        "end": "2026-09-10T11:00:00+09:00",
        "description": "  메일 근거 일정\n검토할 자료  ",
    }
    if scenario == "timezone":
        payload.update(start="2026-09-10T23:30:00+09:00", end="2026-09-11T00:30:00+09:00")
    if scenario in {"attendees", "missing_attendee"}:
        payload["attendees"] = ["fixture-person@example.com"]
    transport = LangGraphE2EGeminiTransport(calendar_payload=payload)
    recorder = GraphPathRecorder()
    original_build = WorkflowGraphComposition.build
    report: dict[str, Any] = {
        "scenario": scenario,
        "verification_kind": "PRODUCTION_GRAPH_EXTERNAL_FIXTURES",
        "live_google": False,
        "actual_model": "FAKE_EXTERNAL_LLM",
        "browser_e2e": False,
    }
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            WorkflowGraphComposition,
            "build",
            lambda self: original_build(self).with_config(callbacks=[recorder]),
        )
        container = build_container(
            root, transport=transport, monkeypatch=patch, profile=GraphProfile.SIX_ROLE_BASELINE
        )
        with TestClient(
            create_app(container), base_url="http://127.0.0.1:8000", headers=API_HEADERS
        ) as client:
            bootstrap(client)
            fixture_path = root / "cache/langgraph-e2e-mcp-state.json"
            fixture = json.loads(fixture_path.read_text()) if fixture_path.exists() else {}
            fixture["calendar_fixture_mode"] = True
            if scenario == "conflict":
                fixture["calendar_busy_intervals"] = [
                    {"start": payload["start"], "end": payload["end"], "transparency": "busy"}
                ]
            failure = {
                "freebusy_failure": "calendar_query_freebusy",
                "events_failure": "calendar_list_events",
            }.get(scenario)
            if failure:
                fixture["calendar_read_failure"] = failure
            mutation = {
                "wrong_calendar": {"parent_id": "unapproved-calendar"},
                "wrong_identity": {"resource_id": "other-event"},
                "wrong_time": {"start": "2026-09-10T10:00:00Z"},
                "wrong_description": {"description": "승인하지 않은 내용"},
                "extra_attendee": {"attendees": ["unapproved@example.com"]},
                "missing_attendee": {"attendees": []},
                "cancelled": {"status": "cancelled"},
            }.get(scenario)
            if mutation:
                fixture["calendar_verification_mutation"] = mutation
            if scenario == "mail":
                fixture.setdefault("resources", {})["gmail_thread:gmail-thread-e2e"] = {
                    "fixture_snapshot_id": "mail-source",
                    "resource_type": "gmail_thread",
                    "resource_id": "gmail-thread-e2e",
                    "parent_id": None,
                    "related_resource_ids": [],
                    "version": "1",
                    "recovery_fingerprint": None,
                    "payload": {
                        "subject": "E2E 행사 안내",
                        "snippet": "수신일 2026-08-20. 행사 일정: "
                        + json.dumps(payload, ensure_ascii=False),
                    },
                }
            fixture_path.parent.mkdir(parents=True, exist_ok=True)
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            request = (
                "E2E:MAIL_CALENDAR_CREATE 메일에서 확인한 일정으로 만들어줘."
                if scenario == "mail"
                else "E2E:CALENDAR_WRITE 다음 일정 만들어줘: "
                + json.dumps(payload, ensure_ascii=False)
            )
            if scenario == "confirmation":
                request = "E2E:CALENDAR_CONFIRMATION 김대리를 참석자로 초대해줘. 이메일 확인 필요."
            run_id = start_run(client, create_conversation(client, scenario), request)
            report["run_id"] = run_id
            waiting = cast(
                dict[str, Any],
                wait_for_status(
                    client,
                    run_id,
                    {"WAITING_APPROVAL", "WAITING_CONFIRMATION", "BLOCKED", "COMPLETED"},
                    timeout_seconds=45,
                ),
            )
            if scenario == "confirmation":
                report["before_confirmation"] = waiting
                assert waiting["run"]["status"] == "WAITING_CONFIRMATION", waiting
                report["writes_before_confirmation"] = (
                    sum(e["tool_name"] == "calendar_create_event" for e in mcp_events(root))
                    if (root / "cache/langgraph-e2e-mcp-events.jsonl").exists()
                    else 0
                )
                payload["attendees"] = ["fixture-person@example.com"]
                response = client.post(
                    f"/api/v1/runs/{run_id}/confirm",
                    json={
                        "api_contract_version": "1",
                        "command_id": "confirm-attendee",
                        "expected_version": waiting["run"]["version"],
                        "interrupt_id": waiting["pending_interrupt"]["interrupt_id"],
                        "response_kind": "FREE_TEXT",
                        "selected_option": None,
                        "free_text": "김대리의 이메일은 fixture-person@example.com입니다.",
                    },
                )
                assert response.status_code == 200, response.text
                waiting = cast(
                    dict[str, Any], wait_for_status(client, run_id, {"WAITING_APPROVAL"})
                )
            report["before_approval"] = waiting
            report["writes_before_approval"] = sum(
                e["tool_name"] == "calendar_create_event" for e in mcp_events(root)
            )
            final = waiting
            if waiting["run"]["status"] == "WAITING_APPROVAL":
                action = waiting["actions"][0]
                if scenario == "reject":
                    reject_action(client, action, "reject-calendar")
                else:
                    if scenario in {"conflict", "timezone", "freebusy_failure", "events_failure"}:
                        denied = client.post(
                            f"/api/v1/actions/{action['action_id']}/approve",
                            json={
                                "api_contract_version": "1",
                                "command_id": "without-warning-ack",
                                "expected_version": action["version"],
                            },
                        )
                        report["unacknowledged_approval_status"] = denied.status_code
                        report["unacknowledged_approval_result"] = denied.json()
                    if not failure:
                        if scenario == "changed_conflict":
                            changed = json.loads(fixture_path.read_text())
                            changed["calendar_busy_intervals"] = [
                                {
                                    "start": payload["start"],
                                    "end": payload["end"],
                                    "transparency": "busy",
                                }
                            ]
                            fixture_path.write_text(json.dumps(changed), encoding="utf-8")
                        approve_action(
                            client,
                            action,
                            "approve-calendar",
                            calendar_conflict_acknowledged=scenario in {"conflict", "timezone"},
                        )
                        if scenario == "changed_conflict":
                            revised = cast(
                                dict[str, Any],
                                wait_for_action_status(
                                    client,
                                    run_id,
                                    {"MODIFIED"},
                                    required_command="APPROVE_ACTION",
                                ),
                            )
                            report["fresh_conflict_requires_reapproval"] = revised
                            report["writes_before_reapproval"] = sum(
                                e["tool_name"] == "calendar_create_event" for e in mcp_events(root)
                            )
                            approve_action(
                                client,
                                revised["actions"][0],
                                "approve-fresh-conflict",
                                calendar_conflict_acknowledged=True,
                            )
                    else:
                        reject_action(client, action, "reject-failed-precondition")
                final = wait_for_status(
                    client,
                    run_id,
                    {"COMPLETED", "RECOVERY_REQUIRED", "BLOCKED"},
                    timeout_seconds=45,
                )
            report["final"] = final
    report["node_path"] = recorder.path
    report["prompt_path"] = [e["prompt_id"] for e in transport.invocations if e["kind"] == "invoke"]
    events = cast(list[dict[str, Any]], mcp_events(root))
    report["connector_path"] = [
        {
            "tool": e["tool_name"],
            "arguments": {k: v for k, v in e["arguments"].items() if k != "claim_context"},
            "begin_committed": e.get("begin_committed_before_write"),
        }
        for e in events
    ]
    with sqlite3.connect(root / "data/google_work_agent.db") as db:
        db.row_factory = sqlite3.Row
        report["attempts"] = [
            dict(row)
            for row in db.execute(
                "SELECT id, approval_id, status, attempt_no FROM execution_attempts"
            )
        ]
        report["approvals"] = [
            json.loads(row[0])
            for row in db.execute("SELECT arguments_snapshot_json FROM approvals")
        ]
        report["verification"] = [
            {"status": r[0], "expected": json.loads(r[1]), "actual": json.loads(r[2])}
            for r in db.execute("SELECT status, expected_json, actual_json FROM verifications")
        ]
        report["evidence"] = [
            dict(row)
            for row in db.execute(
                "SELECT e.origin_type, e.excerpt, r.resource_type FROM action_evidence ae "
                "JOIN evidence e ON e.id = ae.evidence_id "
                "LEFT JOIN resource_refs r ON r.id = e.resource_ref_id"
            )
        ]
        report["audit_path"] = [
            r[0] for r in db.execute("SELECT event_type FROM audit_events ORDER BY id")
        ]
    state = json.loads((root / "cache/langgraph-e2e-mcp-state.json").read_text())
    report["created_events"] = [
        v
        for k, v in state.get("resources", {}).items()
        if k.startswith("calendar_event:event-write-")
    ]
    writes = [e for e in events if e["tool_name"] == "calendar_create_event"]
    blocked = bool(failure) or scenario == "reject"
    nodes = [e["node"] for e in recorder.path]
    expected_args = {"calendar_id": "calendar-e2e", "payload": payload}
    checks = {
        "zero_write_before_approval": report["writes_before_approval"] == 0,
        "write_count": len(writes) == (0 if blocked else 1),
        "begin_committed": all(e.get("begin_committed_before_write") is True for e in writes),
        "only_calendar_create_write": not any(
            e["tool_name"].startswith(("tasks_create", "gmail_create", "calendar_update"))
            for e in events
        ),
        "expected_request_understanding_count": nodes.count("request_understanding")
        == (2 if scenario == "confirmation" else 1),
    }
    if blocked:
        checks["no_attempt_or_approval"] = not report["attempts"] and not report["approvals"]
        checks["safe_terminal_result"] = report["final"]["terminal_result_kind"] == (
            "BLOCKED" if failure else "PARTIAL"
        )
    if not blocked:
        stages = [
            "request_understanding",
            "tool_route",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
            "waiting_approval",
            "action_execution",
            "verification",
            "response_synthesis",
            "terminal_commit",
        ]
        if mutation:
            stages = stages[:-2]
        checks.update(
            {
                "preview_arguments": bool(report["before_approval"]["actions"])
                and report["before_approval"]["actions"][0]["arguments"] == expected_args,
                "immutable_approval_arguments": report["approvals"]
                == [expected_args] * (2 if scenario == "changed_conflict" else 1),
                "dispatch_arguments": len(writes) == 1
                and {
                    k: v
                    for k, v in writes[0]["arguments"].items()
                    if k not in {"claim_context", "recovery_fingerprint"}
                }
                == {
                    **expected_args,
                    "payload": {
                        **payload,
                        "recovery_fingerprint": writes[0]["arguments"]["payload"].get(
                            "recovery_fingerprint"
                        ),
                    },
                },
                "independent_get": any(e["tool_name"] == "calendar_get_event" for e in events),
                "terminal": report["final"]["run"]["status"]
                == ("RECOVERY_REQUIRED" if mutation else "COMPLETED"),
                "verification": bool(report["verification"])
                and report["verification"][-1]["status"]
                == ("MISMATCH" if mutation else "VERIFIED"),
                "one_attempt": len(report["attempts"]) == 1,
                "single_planning": nodes.count("planning") == 1,
                "stage_order": all(stage in nodes for stage in stages)
                and all(
                    nodes.index(first) < nodes.index(second)
                    for first, second in zip(stages, stages[1:], strict=False)
                ),
                "final_result_kind": report["final"]["terminal_result_kind"]
                == ("NONE" if mutation else "SUCCESS"),
            }
        )
    if scenario in {"conflict", "timezone"} or failure:
        checks["warning_or_failure_blocks_unacknowledged_approval"] = report.get(
            "unacknowledged_approval_status"
        ) == 409 or (
            bool(failure) and report["before_approval"]["run"]["status"] != "WAITING_APPROVAL"
        )
    if scenario == "mail":
        checks["mail_evidence_preserved"] = any(
            e["resource_type"] == "gmail_thread"
            and "2026-08-20" in e["excerpt"]
            and "2026-09-10" in e["excerpt"]
            for e in report["evidence"]
        )
    if scenario == "response_loss":
        checks["lookup_without_resend"] = (
            any(e["tool_name"] == "search_by_recovery_fingerprint" for e in events)
            and len(writes) == 1
        )
    if scenario == "changed_conflict":
        checks["fresh_conflict_reapproval_without_write"] = (
            report.get("writes_before_reapproval") == 0
        )
        checks["review_back_edge"] = nodes.count("review") == 2
    if scenario == "confirmation":
        checks["unresolved_attendee_does_not_write"] = report["writes_before_confirmation"] == 0
        checks["same_run_confirmation"] = report["before_confirmation"]["run"]["run_id"] == run_id
    report["checks"] = checks
    report["measurement_status"] = "PASS" if all(checks.values()) else "FAIL"
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="create")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="gwa-calendar-closure-"))
    result = measure_calendar(args.scenario, root)
    evidence_path = root / "measurement.json"
    evidence_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: result[k] for k in ("scenario", "run_id", "checks", "measurement_status")}
            | {"evidence_path": str(evidence_path)},
            ensure_ascii=False,
        )
    )
    raise SystemExit(0 if result["measurement_status"] == "PASS" else 1)
