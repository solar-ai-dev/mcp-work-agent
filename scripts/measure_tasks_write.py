"""Measure Tasks WRITE through production Graph/Router/Application and SQLite.

Only the LLM transport and external MCP service are fixtures. This is not live
Google or browser E2E certification. The MCP fixture uses production Task body
mapping, snapshot projection, wire validation and ClaimContext verification.
"""

from __future__ import annotations

import argparse
import json
import os
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
    "reject",
    "similar",
    "identical",
    "empty_notes",
    "whitespace_notes",
    "review_revision",
    "response_loss",
    "retry",
    "wrong_list",
    "wrong_notes",
    "wrong_date",
    "wrong_status",
)




def load_google_seed() -> dict[str, Any]:
    """READ only the user-designated seed through production Google operations."""
    from google_work_agent.adapters.connectors.google.tasks.tasklists.list_tasklists import (
        ListTasklistsOperation,
    )
    from google_work_agent.adapters.connectors.google.tasks.tasks.get_task import GetTaskOperation
    from google_work_agent.adapters.connectors.google.tasks.tasks.list_tasks import (
        ListTasksOperation,
    )
    from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
        credential_provider,
    )

    os.environ["GOOGLE_OAUTH_ENV"] = "DEVELOPMENT"
    provider = credential_provider.GoogleWorkspaceCredentialProvider()
    list_matches: list[dict[str, Any]] = []
    page_token = None
    for _ in range(10):
        page = cast(
            dict[str, Any],
            ListTasklistsOperation().execute(
                provider,
                {
                    "page_size": 100,
                    "page_token": page_token,
                },
            ),
        )
        list_matches.extend(
            item for item in page["items"] if item["payload"]["title"] == "GWA E2E Validation"
        )
        page_token = page["next_page_token"]
        if page_token is None:
            break
    else:
        raise AssertionError("Test Task List lookup exceeded bounded pages")
    assert len(list_matches) == 1, "Expected exactly one GWA E2E Validation Task List"
    selected_list = list_matches[0]
    task_matches: list[dict[str, Any]] = []
    for _ in range(10):
        page = cast(
            dict[str, Any],
            ListTasksOperation().execute(
                provider,
                {
                    "task_list_id": selected_list["resource_id"],
                    "page_size": 100,
                    "page_token": page_token,
                    "show_completed": False,
                },
            ),
        )
        task_matches.extend(
            item
            for item in page["items"]
            if item["payload"]["title"] == "[GWA E2E] 주간 프로젝트 회의 후속자료 정리"
        )
        page_token = page["next_page_token"]
        if page_token is None:
            break
    else:
        raise AssertionError("Seed lookup exceeded bounded pages")
    assert len(task_matches) == 1, "Expected exactly one designated incomplete seed Task"
    task = cast(
        dict[str, Any],
        GetTaskOperation().execute(
            provider,
            {
                "task_list_id": selected_list["resource_id"],
                "task_id": task_matches[0]["resource_id"],
            },
        ),
    )["item"]
    assert task["payload"] == task_matches[0]["payload"], "Google list/detail mismatch"
    assert task["payload"]["due"][:10] == "2026-09-10"
    assert task["payload"]["status"] == "needsAction"
    assert "김대리와 진행한 주간 프로젝트 회의 후속자료를 정리한다." in task["payload"]["notes"]
    return {
        "source": "LIVE_GOOGLE_READ_ONLY",
        "account_email": provider.account_email,
        "task_list": selected_list,
        "task": task,
    }


def seed_from_user_description() -> dict[str, Any]:
    """Reproduce supplied fields without claiming an observed Google resource identity."""
    task_list_id = "fixture-user-task-list"
    common = {"version": "fixture", "recovery_fingerprint": None}
    return {
        "source": "USER_PROVIDED_SEED_NOT_LIVE_VERIFIED",
        "task_list": {
            **common,
            "fixture_snapshot_id": "user-task-list",
            "resource_type": "task_list",
            "resource_id": task_list_id,
            "parent_id": None,
            "related_resource_ids": [],
            "payload": {"title": "GWA E2E Validation"},
        },
        "task": {
            **common,
            "fixture_snapshot_id": "user-seed",
            "resource_type": "task",
            "resource_id": "fixture-user-seed",
            "parent_id": task_list_id,
            "related_resource_ids": [task_list_id],
            "payload": {
                "title": "[GWA E2E] 주간 프로젝트 회의 후속자료 정리",
                "notes": "김대리와 진행한 주간 프로젝트 회의 후속자료를 정리한다.\n"
                "Google Work Agent Gmail → Task Retrieval/WRITE/Verification "
                "E2E 검증용 테스트 작업.",
                "due": "2026-09-10T00:00:00Z",
                "status": "needsAction",
            },
        },
    }


def measure(
    scenario: str, runtime_root: Path, seed: dict[str, Any] | None = None
) -> dict[str, Any]:
    title = "검증용 보고서 정리"
    mode = {
        "mail": "MAIL_TASK_CREATE",
        "response_loss": "RESPONSE_LOSS",
        "retry": "FAILED_RETRY",
        "reject": "REJECTION",
        "review_revision": "REVIEW_BACK_EDGE",
    }.get(scenario, "APPROVED_WRITE")
    if scenario in {"response_loss", "retry"}:
        title += f" {mode}"
    payload: dict[str, object] = {
        "title": title,
        "notes": "검증용 메모\n메일 근거 확인",
        "scheduled_date": "2026-09-08",
    }
    if scenario == "empty_notes":
        payload = {"title": title}
    if scenario == "whitespace_notes":
        payload["notes"] = "  검증용 메모\n메일 근거 확인  \n"
    task_list_id = "task-list-e2e"
    if seed:
        task_list_id = seed["task_list"]["resource_id"]
        if scenario == "identical":
            source = seed["task"]["payload"]
            payload = {
                "title": source["title"],
                "notes": source["notes"],
                "scheduled_date": source["due"][:10],
            }
        elif scenario == "create":
            payload = {
                "title": "[GWA E2E] 김대리 회의록 검토 결과 공유",
                "notes": "김대리와 진행한 주간 프로젝트 회의의 회의록을 검토하고 결과를 공유한다.",
                "scheduled_date": "2026-09-11",
            }
        else:
            raise ValueError("Seed replay supports identical/create scenarios only")
        title = str(payload["title"])
    transport = LangGraphE2EGeminiTransport(task_payload=payload)
    recorder = GraphPathRecorder()
    build = WorkflowGraphComposition.build
    report: dict[str, Any] = {
        "scenario": scenario,
        "verification_kind": "PRODUCTION_GRAPH_EXTERNAL_FIXTURES",
        "product_e2e": False,
        "live_google": False,
        "runtime_root": str(runtime_root),
        "seed_provenance": seed,
    }
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            WorkflowGraphComposition,
            "build",
            lambda self: build(self).with_config(callbacks=[recorder]),
        )
        container = build_container(
            runtime_root,
            transport=transport,
            monkeypatch=patch,
            profile=GraphProfile.SIX_ROLE_BASELINE,
        )
        with TestClient(
            create_app(container), base_url="http://127.0.0.1:8000", headers=API_HEADERS
        ) as client:
            bootstrap(client, task_list_id=task_list_id)
            fixture_path = runtime_root / "cache/langgraph-e2e-mcp-state.json"
            fixture = json.loads(fixture_path.read_text()) if fixture_path.exists() else {}
            fixture["task_fixture_mode"] = True
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
                        "subject": "E2E 보고서 요청",
                        "snippet": f"제목: {title}. 메모: {payload['notes']}. 예정일: 2026-09-08.",
                    },
                }
            if seed:
                fixture["task_list_snapshot"] = seed["task_list"]
                fixture.setdefault("resources", {})[f"task:{seed['task']['resource_id']}"] = seed[
                    "task"
                ]
            elif scenario in {"similar", "identical"}:
                fixture.setdefault("resources", {})["task:existing"] = {
                    "fixture_snapshot_id": "existing",
                    "resource_type": "task",
                    "resource_id": "existing",
                    "parent_id": "task-list-e2e",
                    "related_resource_ids": ["task-list-e2e"],
                    "version": "1",
                    "recovery_fingerprint": None,
                    "payload": {
                        "title": title,
                        "notes": "기존 테스트 자료",
                        "status": "needsAction",
                        "due": "2026-09-08T00:00:00Z"
                        if scenario == "identical"
                        else "2026-09-09T00:00:00Z",
                    },
                }
            mutation = {
                "wrong_list": {"parent_id": "unapproved-list"},
                "wrong_notes": {"notes": "승인하지 않은 메모"},
                "wrong_date": {"due": "2026-09-09T00:00:00Z"},
                "wrong_status": {"status": "completed"},
            }.get(scenario)
            if mutation:
                fixture["task_verification_mutation"] = mutation
            fixture_path.parent.mkdir(parents=True, exist_ok=True)
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            if seed:
                containers = client.get("/api/v1/resources/task-lists")
                assert containers.status_code == 200, containers.text
                assert any(
                    item["tasklist_id"] == task_list_id
                    and item["title"] == seed["task_list"]["payload"]["title"]
                    for item in containers.json()["items"]
                )
                browse = client.get(
                    "/api/v1/resources/tasks", params={"task_list_id": task_list_id}
                )
                assert browse.status_code == 200, browse.text
                item = next(
                    item for item in browse.json()["items"]
                    if item["resource_id"] == seed["task"]["resource_id"]
                )
                detail = client.get(
                    f"/api/v1/resources/tasks/{item['resource_id']}",
                    params={"selection_handle": item["selection_handle"]},
                )
                assert detail.status_code == 200, detail.text
                expected = {
                    "tasklist_id": task_list_id,
                    "title": seed["task"]["payload"]["title"],
                    "scheduled_date": seed["task"]["payload"]["due"][:10],
                    "task_status": "incomplete",
                }
                assert all(item[key] == value for key, value in expected.items())
                assert all(detail.json()[key] == value for key, value in expected.items())
                assert detail.json()["notes"] == seed["task"]["payload"]["notes"]
                report["seed_browse_detail"] = detail.json()
            request_text = (
                "E2E:MAIL_TASK_CREATE 보고서 요청 메일을 찾아 그 내용으로 태스크를 만들어줘."
                if scenario == "mail"
                else f"E2E:{mode} 태스크를 만들어줘. 승인할 업무 값: "
                + json.dumps(payload, ensure_ascii=False)
            )
            run_id = start_run(
                client,
                create_conversation(client, scenario),
                request_text,
            )
            report["run_id"] = run_id
            waiting = cast(
                dict[str, Any],
                wait_for_status(
                    client,
                    run_id,
                    {"WAITING_APPROVAL", "BLOCKED", "COMPLETED", "WAITING_CONFIRMATION"},
                    timeout_seconds=45,
                ),
            )
            report["before_approval"] = waiting
            report["writes_before_approval"] = sum(
                item["tool_name"] == "tasks_create_task" for item in mcp_events(runtime_root)
            )
            if waiting["run"]["status"] == "WAITING_APPROVAL":
                action = waiting["actions"][0]
                if scenario == "identical":
                    denied = client.post(
                        f"/api/v1/actions/{action['action_id']}/approve",
                        json={
                            "api_contract_version": "1",
                            "command_id": "approve-without-override",
                            "expected_version": action["version"],
                        },
                    )
                    report["duplicate_guard"] = denied.json()
                    assert denied.status_code == 409, denied.text
                    assert not any(
                        event["tool_name"] == "tasks_create_task"
                        for event in mcp_events(runtime_root)
                    )
                    reject_action(client, action, "reject-duplicate")
                elif scenario == "reject":
                    reject_action(client, action, "reject-task")
                else:
                    if scenario == "similar":
                        denied = client.post(
                            f"/api/v1/actions/{action['action_id']}/approve",
                            json={
                                "api_contract_version": "1",
                                "command_id": "approve-without-ack",
                                "expected_version": action["version"],
                            },
                        )
                        report["duplicate_guard"] = denied.json()
                        assert denied.status_code == 409, denied.text
                    command = {
                        "api_contract_version": "1",
                        "command_id": "approve-task",
                        "expected_version": action["version"],
                        "duplicate_acknowledged": scenario == "similar",
                    }
                    approval = client.post(
                        f"/api/v1/actions/{action['action_id']}/approve", json=command
                    )
                    report["approval_status"] = approval.status_code
                    assert approval.status_code == 200, approval.text
                    replay = client.post(
                        f"/api/v1/actions/{action['action_id']}/approve", json=command
                    )
                    report["duplicate_approval_status"] = replay.status_code
                    assert replay.status_code == 200, replay.text
                    if scenario == "retry":
                        failed = cast(
                            dict[str, Any], wait_for_action_status(client, run_id, {"FAILED"})
                        )["actions"][0]
                        prepared = client.post(
                            f"/api/v1/actions/{failed['action_id']}/prepare-retry",
                            json={
                                "api_contract_version": "1",
                                "command_id": "prepare-task-retry",
                                "expected_version": failed["version"],
                            },
                        )
                        assert prepared.status_code == 200, prepared.text
                        retry = cast(
                            dict[str, Any],
                            wait_for_action_status(
                                client,
                                run_id,
                                {"MODIFIED"},
                                required_command="APPROVE_ACTION",
                            ),
                        )["actions"][0]
                        approval = client.post(
                            f"/api/v1/actions/{retry['action_id']}/approve",
                            json={
                                "api_contract_version": "1",
                                "command_id": "approve-task-retry",
                                "expected_version": retry["version"],
                            },
                        )
                        assert approval.status_code == 200, approval.text
                final = wait_for_status(
                    client, run_id, {"COMPLETED", "RECOVERY_REQUIRED", "BLOCKED"}
                )
            else:
                final = waiting
            report["final"] = final
    report["node_path"] = recorder.path
    report["prompt_path"] = [
        item["prompt_id"] for item in transport.invocations if item["kind"] == "invoke"
    ]
    events = cast(list[dict[str, Any]], mcp_events(runtime_root))
    report["connector_path"] = [
        {
            "tool": item["tool_name"],
            "arguments": {
                key: value for key, value in item["arguments"].items() if key != "claim_context"
            },
            "begin_committed": item.get("begin_committed_before_write"),
        }
        for item in events
    ]
    with sqlite3.connect(runtime_root / "data/google_work_agent.db") as db:
        db.row_factory = sqlite3.Row
        report["attempts"] = [
            dict(row)
            for row in db.execute(
                "SELECT id, approval_id, attempt_no, status, error_code FROM execution_attempts"
            )
        ]
        report["action_evidence"] = [
            dict(row)
            for row in db.execute(
                "SELECT e.id, e.origin_type, e.excerpt, r.resource_type FROM action_evidence ae "
                "JOIN evidence e ON e.id = ae.evidence_id "
                "LEFT JOIN resource_refs r ON r.id = e.resource_ref_id"
            )
        ]
        report["approvals"] = [
            json.loads(row[0])
            for row in db.execute("SELECT arguments_snapshot_json FROM approvals")
        ]
        report["verification"] = [
            {"status": row[0], "expected": json.loads(row[1]), "actual": json.loads(row[2])}
            for row in db.execute("SELECT status, expected_json, actual_json FROM verifications")
        ]
        report["audit_path"] = [
            row[0] for row in db.execute("SELECT event_type FROM audit_events ORDER BY id")
        ]
    state = json.loads((runtime_root / "cache/langgraph-e2e-mcp-state.json").read_text())
    report["created_tasks"] = [
        item
        for key, item in state.get("resources", {}).items()
        if key.startswith("task:task-write-")
    ]
    writes = [item for item in events if item["tool_name"] == "tasks_create_task"]
    status = report["final"]["run"]["status"]
    mismatch = scenario.startswith("wrong_")
    no_write = scenario in {"reject", "identical"}
    report["checks"] = {
        "no_write_before_approval": report["writes_before_approval"] == 0,
        "expected_write_count": len(writes) == (0 if no_write else 2 if scenario == "retry" else 1),
        "begin_committed": all(item.get("begin_committed_before_write") is True for item in writes),
        "only_intended_task_created": len(report["created_tasks"]) == (0 if no_write else 1),
        "terminal_or_safe_block": status == ("RECOVERY_REQUIRED" if mismatch else "COMPLETED"),
        "independent_verification": no_write or bool(report["verification"]),
        "verification_outcome": no_write
        or bool(report["verification"])
        and report["verification"][-1]["status"] == ("MISMATCH" if mismatch else "VERIFIED"),
        "production_node_path_observed": bool(recorder.path),
        "seed_api_projection_matches_google": seed is None
        or bool(report.get("seed_browse_detail")),
    }
    expected_arguments = {"payload": payload, "task_list_id": task_list_id}
    nodes = [event["node"] for event in recorder.path]
    audit = report["audit_path"]
    tools = [event["tool_name"] for event in events]
    write_arguments = []
    for event in writes:
        arguments = dict(event["arguments"])
        arguments.pop("claim_context", None)
        arguments["payload"] = {
            key: value
            for key, value in arguments["payload"].items()
            if key != "recovery_fingerprint"
        }
        write_arguments.append(arguments)
    ordered_nodes = [
        "initialize",
        "request_understanding",
        "tool_route",
        "context_retriever",
        "planning",
        "review",
        "domain_validation",
        "waiting_approval",
    ]
    ordered_audit = [
        "ACTION_APPROVED",
        "APPROVAL_CONSUMED",
        "EXECUTION_CLAIMED",
        "EXECUTION_DISPATCH_STARTED",
    ]
    report["checks"].update(
        {
            "requested_values_in_preview": report["before_approval"]["actions"][0]["arguments"]
            == expected_arguments,
            "approved_values_unchanged": no_write
            or all(item == expected_arguments for item in report["approvals"]),
            "dispatch_preserves_business_arguments": all(
                item == expected_arguments for item in write_arguments
            ),
            "ordered_production_stages": all(node in nodes for node in ordered_nodes)
            and [nodes.index(node) for node in ordered_nodes]
            == sorted(nodes.index(node) for node in ordered_nodes),
            "approval_claim_begin_order": no_write
            or all(item in audit for item in ordered_audit)
            and [audit.index(item) for item in ordered_audit]
            == sorted(audit.index(item) for item in ordered_audit),
            "no_unnecessary_replanning": nodes.count("planning")
            == (2 if scenario == "review_revision" else 1)
            and nodes.count("request_understanding") == 1,
            "independent_get_after_write": no_write
            or all(
                any(
                    index > tools.index("tasks_create_task")
                    and event["tool_name"] == "tasks_get_task"
                    and event["arguments"].get("task_id") == task["resource_id"]
                    for index, event in enumerate(events)
                )
                for task in report["created_tasks"]
            ),
            "attempt_count": len(report["attempts"])
            == (0 if no_write else 2 if scenario == "retry" else 1),
            "only_tasks_write": all(
                tool == "tasks_create_task"
                for tool in tools
                if any(verb in tool for verb in ("_create_", "_update_", "_delete_", "_send"))
            ),
            "no_deadline_promotion": all(
                "business_deadline" not in item["payload"] for item in write_arguments
            ),
            "terminal_result_truth": report["final"]["terminal_result_kind"]
            == ("NONE" if mismatch else "PARTIAL" if no_write else "SUCCESS"),
            "mail_evidence_persisted": scenario != "mail"
            or any(
                item["resource_type"] == "gmail_thread"
                and title in item["excerpt"]
                and "2026-09-08" in item["excerpt"]
                for item in report["action_evidence"]
            ),
            "response_loss_recovered_without_resend": scenario != "response_loss"
            or ("search_by_recovery_fingerprint" in tools and len(writes) == 1),
            "retry_reenters_review": scenario != "retry" or nodes.count("review") == 2,
            "seed_preserved": seed is None
            or state["resources"][f"task:{seed['task']['resource_id']}"] == seed["task"],
            "review_revision_back_edge": scenario != "review_revision"
            or (
                "review.recheck_affected_dimensions" in report["prompt_path"]
                and nodes.count("review") == 2
            ),
        }
    )
    report["measurement_status"] = "PASS" if all(report["checks"].values()) else "FAIL"
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="create")
    seed_options = parser.add_mutually_exclusive_group()
    seed_options.add_argument(
        "--seed-from-google",
        action="store_true",
        help="Read designated seed, replay inside Graph; no live WRITE",
    )
    seed_options.add_argument(
        "--seed-from-prompt",
        action="store_true",
        help="Replay user-supplied seed fields; not live Google evidence",
    )
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="gwa-tasks-closure-"))
    seed = (
        load_google_seed()
        if args.seed_from_google
        else seed_from_user_description()
        if args.seed_from_prompt
        else None
    )
    result = measure(args.scenario, root, seed)
    evidence_path = root / "measurement.json"
    evidence_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "scenario",
                    "run_id",
                    "verification_kind",
                    "checks",
                    "measurement_status",
                )
            }
            | {"evidence_path": str(evidence_path)},
            ensure_ascii=False,
            default=str,
        )
    )
    raise SystemExit(0 if result["measurement_status"] == "PASS" else 1)
