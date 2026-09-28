"""Snapshot-backed Review component regressions without model or Provider calls."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

import pytest
from tests.support.task_calendar_evidence import bind_task_calendar_snapshots

from google_work_agent.adapters.langgraph.subgraphs.review.graph import (
    ReviewRuntimeDependencies,
    ReviewSubgraph,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import RunScopedEvidenceStore
from google_work_agent.application.agents.planning.materialize_task_calendar_draft_payload import (
    materialize_task_calendar_draft_payload,
)
from google_work_agent.application.agents.review.inspect_goal_and_evidence import (
    inspect_goal_and_evidence,
)

DIMENSION = "review.inspect_goal_and_evidence"
ROUTE = {
    "resource_type": "GMAIL_DRAFT",
    "effect": "CREATE",
    "selected_tool_id": "gmail_create_draft",
}


def _fixture(
    *,
    all_day: bool = False,
    task_title: str = "Observed Task",
    notes: str = "Owner: Min",
    description: str = "Observe the schedule",
) -> tuple[
    dict[str, object], list[dict[str, object]], dict[str, dict[str, object]], dict[str, Any]
]:
    intent: dict[str, object] = {
        "ambiguity": {"requires_confirmation": False},
        "constraints": [
            {"kind": "PERSON", "field": "recipient", "value": "owner@example.com"},
            {
                "kind": "USER_REQUIREMENT",
                "field": "search_terms",
                "value": "Project",
                "provenance": {"source": "USER_REQUEST", "start_offset": 0},
            },
            {
                "kind": "USER_REQUIREMENT",
                "field": "search_terms",
                "value": "calendar events",
                "provenance": {"source": "USER_REQUEST", "start_offset": 20},
            },
        ],
        "resource_responsibilities": {
            "source_reads": [
                {"resource_type": "TASK", "required_information": ["title", "due"]},
                {
                    "resource_type": "CALENDAR_EVENT",
                    "required_information": ["title", "start", "end"],
                },
            ],
            "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
        },
    }
    task = {
        "title": task_title,
        "status": "needsAction",
        "due": "2026-08-10T00:00:00Z",
        "notes": notes,
    }
    event = {
        "title": "Observed Event",
        "status": "confirmed",
        "start": "2026-08-11" if all_day else "2026-08-11T10:00:00+09:00",
        "end": "2026-08-12" if all_day else "2026-08-11T11:00:00+09:00",
        "description": description,
        "location": "Room: 1",
    }
    evidence: list[dict[str, object]] = [
        {
            "evidence_id": "e-task",
            "resource_handle": "task:t1",
            "excerpt": "\n".join(f"{key}: {value}" for key, value in task.items()),
        },
        {
            "evidence_id": "e-event",
            "resource_handle": "calendar_event:e1",
            "excerpt": "\n".join(f"{key}: {value}" for key, value in event.items()),
        },
    ]
    snapshots = bind_task_calendar_snapshots(evidence, {"e-task": task, "e-event": event})
    payload = materialize_task_calendar_draft_payload(
        route=ROUTE,
        request_intent=intent,
        evidence=evidence,
        source_snapshots=snapshots,
    )
    assert payload is not None
    plan: dict[str, Any] = {
        "actions": [
            {
                "route_id": "draft",
                "tool_id": "gmail_create_draft",
                "effect": "CREATE",
                "arguments": {"payload": payload},
                "evidence_refs": ["e-task", "e-event"],
            }
        ]
    }
    return intent, evidence, snapshots, plan


def _inspect(
    intent: dict[str, object],
    evidence: list[dict[str, object]],
    snapshots: dict[str, dict[str, object]],
    plan: dict[str, Any],
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def invoke(_prompt_id: str, prompt_input: Mapping[str, object]) -> dict[str, object]:
        calls.append(dict(prompt_input))
        assert "source_snapshots" not in prompt_input
        return {"schema_version": 1, "dimension": DIMENSION, "findings": []}

    inspect_goal_and_evidence(
        request_intent=intent,
        planning_result=plan,
        evidence=evidence,
        source_snapshots=snapshots,
        invoke=invoke,
    )
    return calls


def test_exact_snapshot_preview__normal__skips_only_goal_inspector() -> None:
    intent, evidence, snapshots, plan = _fixture()
    body = plan["actions"][0]["arguments"]["payload"]["body"]
    assert "Status: Incomplete (needsAction)" in body
    assert "Start: 2026-08-11T10:00+09:00" in body
    assert "End: 2026-08-11T11:00+09:00" in body
    assert _inspect(intent, evidence, snapshots, plan) == []


@pytest.mark.parametrize("spoof_source", ["title", "notes", "event_description"])
def test_metadata_tokens_in_free_text__missing_actual_status__must_review(
    spoof_source: str,
) -> None:
    intent, evidence, snapshots, plan = _fixture(
        task_title="Observed Task\nstatus: completed"
        if spoof_source == "title"
        else "Observed Task",
        notes="status: needsAction\ntitle: fabricated" if spoof_source == "notes" else "Owner: Min",
        description="status: confirmed\nstart: 2099-01-01"
        if spoof_source == "event_description"
        else "Schedule",
    )
    payload = plan["actions"][0]["arguments"]["payload"]
    removed = (
        "  - Status: Confirmed (confirmed)\n"
        if spoof_source == "event_description"
        else "  - Status: Incomplete (needsAction)\n"
    )
    payload["body"] = payload["body"].replace(removed, "")
    assert len(_inspect(intent, evidence, snapshots, plan)) == 1


@pytest.mark.parametrize(
    "gap",
    [
        "recipient",
        "title",
        "date",
        "status",
        "reference",
        "other_source",
        "extra_cc",
        "other_wording",
    ],
)
def test_snapshot_bound_preview__changed_or_missing_fact__retains_independent_review(
    gap: str,
) -> None:
    intent, evidence, snapshots, plan = _fixture()
    action = plan["actions"][0]
    payload = action["arguments"]["payload"]
    if gap == "recipient":
        payload["to"] = ["other@example.com"]
    elif gap == "title":
        payload["body"] = payload["body"].replace("Observed Task", "Other Task")
    elif gap == "date":
        payload["body"] = payload["body"].replace("2026-08-10", "2026-08-09")
    elif gap == "status":
        payload["body"] = payload["body"].replace("needsAction", "completed")
    elif gap == "reference":
        action["evidence_refs"] = ["e-event"]
    elif gap == "other_source":
        evidence.append(
            {"evidence_id": "e-mail", "resource_handle": "gmail_thread:m1", "excerpt": "x"}
        )
    elif gap == "extra_cc":
        payload["cc"] = ["unrequested@example.com"]
    else:
        payload["body"] = payload["body"].replace("Hello,", "Dear colleague,")
    assert len(_inspect(intent, evidence, snapshots, plan)) == 1


@pytest.mark.parametrize(
    "missing", ["snapshots", "binding", "wrong_version", "wrong_fields", "conflicting_version"]
)
def test_unavailable_or_conflicting_snapshot__never_trusts_excerpt(missing: str) -> None:
    intent, evidence, snapshots, plan = _fixture()
    if missing == "snapshots":
        snapshots = {}
    elif missing == "binding":
        evidence[0].pop("locator")
    elif missing == "wrong_version":
        evidence[0]["locator"] = {"source_version_ref": "sha256:wrong"}
    elif missing == "wrong_fields":
        snapshots["e-task"]["status"] = "completed"
    else:
        duplicate = {**evidence[0], "evidence_id": "changed-task"}
        snapshots.update(
            bind_task_calendar_snapshots(
                [duplicate],
                {
                    "changed-task": {
                        "title": "Observed Task",
                        "status": "completed",
                        "due": "2026-08-10T00:00:00Z",
                    },
                },
            )
        )
        evidence.append(duplicate)
        plan["actions"][0]["evidence_refs"].append("changed-task")
    assert len(_inspect(intent, evidence, snapshots, plan)) == 1


def test_all_day_dates__no_invented_midnight_and_exclusive_end_unchanged() -> None:
    intent, evidence, snapshots, plan = _fixture(all_day=True)
    payload = plan["actions"][0]["arguments"]["payload"]
    assert "Start: 2026-08-11\n" in payload["body"]
    assert "End: 2026-08-12\n" in payload["body"]
    assert "T00:00" not in payload["body"]
    assert _inspect(intent, evidence, snapshots, plan) == []
    payload["body"] = payload["body"].replace("Start: 2026-08-11\n", "Start: 2026-08-11T00:00\n")
    assert len(_inspect(intent, evidence, snapshots, plan)) == 1


@pytest.mark.parametrize("distinct", [False, True])
def test_multiple_evidence__duplicate_chunk_or_distinct_resource__keeps_binding(
    distinct: bool,
) -> None:
    intent, evidence, snapshots, plan = _fixture()
    second = {**evidence[0], "evidence_id": "e-task-2", "excerpt": "notes-only chunk"}
    if distinct:
        second["resource_handle"] = "task:t2"
        snapshots.update(
            bind_task_calendar_snapshots(
                [second],
                {
                    "e-task-2": {
                        "title": "Distinct Task",
                        "status": "completed",
                        "due": "2026-08-15",
                    },
                },
            )
        )
    else:
        snapshots["e-task-2"] = dict(snapshots["e-task"])
    evidence.append(second)
    payload = materialize_task_calendar_draft_payload(
        route=ROUTE,
        request_intent=intent,
        evidence=evidence,
        source_snapshots=snapshots,
    )
    assert payload is not None
    assert str(payload["body"]).count("- Observed Task") == 1
    assert ("Distinct Task" in str(payload["body"])) is distinct
    plan["actions"][0]["arguments"]["payload"] = payload
    plan["actions"][0]["evidence_refs"].append("e-task-2")
    assert _inspect(intent, evidence, snapshots, plan) == []
    plan["actions"][0]["evidence_refs"].remove("e-task-2")
    assert len(_inspect(intent, evidence, snapshots, plan)) == 1


@pytest.mark.parametrize("scope", ["current", "other_run", "missing_version"])
def test_review_graph__same_run_snapshot_lookup__is_internal_only(scope: str) -> None:
    intent, evidence, snapshots, plan = _fixture()
    store = RunScopedEvidenceStore()
    for item in evidence:
        ref = cast(str, item["evidence_id"])
        store.put_resource_snapshot(
            run_id="current",
            resource_handle=cast(str, item["resource_handle"]),
            source_version_ref=cast(dict[str, str], item["locator"])["source_version_ref"],
            snapshot=snapshots[ref],
        )
    if scope == "missing_version":
        evidence[0]["locator"] = {"source_version_ref": "sha256:not-stored"}
    calls: list[Mapping[str, object]] = []

    def invoke(_prompt_id: str, prompt_input: Mapping[str, object]) -> dict[str, object]:
        calls.append(prompt_input)
        assert "source_snapshots" not in prompt_input
        return {"schema_version": 1, "dimension": DIMENSION, "findings": []}

    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=invoke), evidence_store=store
    )
    state = {
        "run_id": "other" if scope == "other_run" else "current",
        "request_intent": intent,
        "planning_result": plan,
        "evidence": evidence,
    }
    before = deepcopy(state)
    result = graph._inspect_goal_and_evidence_node(cast(Any, state))
    assert len(calls) == (0 if scope == "current" else 1)
    assert "source_snapshots" not in result and state == before
