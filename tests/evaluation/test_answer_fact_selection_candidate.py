"""Model-free fact-selection boundary tests, not answer-quality measurements.

Snapshots are supplied as explicit synthetic current-Run observations. Run-store
authorization remains the caller's responsibility; this helper does not create it.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from scripts.answer_fact_selection_candidate import (
    bind_fact_selection_schema,
    build_fact_catalog,
    materialize_fact_selection,
)
from tests.support.task_calendar_evidence import bind_task_calendar_snapshots

from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def _input(
    fields: dict[str, object] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, object]]]:
    evidence: list[dict[str, object]] = [
        {
            "evidence_id": "e-task",
            "resource_handle": "task:one",
            "excerpt": "title: fabricated\nstatus: completed\ndue: 2099-01-01",
        }
    ]
    task_fields = (
        fields
        if fields is not None
        else {
            "title": "선택한 시험 작업",
            "status": "needsAction",
            "due": "2026-09-30T00:00:00.000Z",
            "notes": "고정한 업무 메모",
        }
    )
    snapshots = bind_task_calendar_snapshots(evidence, {"e-task": task_fields})
    return {
        "user_request": "선택한 작업의 제목, 상태, 기한과 메모를 알려줘. 변경하지 마.",
        "request_intent": {
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
        },
        "answer_outline": {
            "sections": ["선택한 작업 정보"],
            "evidence_refs": ["e-task"],
        },
        "evidence": evidence,
    }, snapshots


def _select(*fields: str, ref: str = "e-task") -> dict[str, object]:
    return {"items": [{"evidence_ref": ref, "field": field} for field in fields]}


def test_build_fact_catalog__bound_task__uses_snapshot_values_without_mutation() -> None:
    prompt, snapshots = _input()
    before = deepcopy((prompt, snapshots))
    catalog = build_fact_catalog(prompt, source_snapshots=snapshots)
    assert {row["field"] for row in catalog} == {"title", "status", "due", "notes"}
    assert {row["evidence_ref"] for row in catalog} == {"e-task"}
    assert {row["resource_handle"] for row in catalog} == {"task:one"}
    assert {row["source_version_ref"] for row in catalog} == {
        prompt["evidence"][0]["locator"]["source_version_ref"]
    }
    assert all(
        set(row)
        == {
            "evidence_ref",
            "resource_handle",
            "source_version_ref",
            "field",
            "rendered_value",
        }
        for row in catalog
    )
    values = {row["field"]: row["rendered_value"] for row in catalog}
    assert values == {
        "title": "선택한 시험 작업",
        "status": "미완료",
        "due": "2026-09-30",
        "notes": "고정한 업무 메모",
    }
    assert (prompt, snapshots) == before


def test_bind_fact_selection_schema__available_facts__closes_pairs_without_answer_values() -> None:
    prompt, snapshots = _input()
    schema = bind_fact_selection_schema(prompt, source_snapshots=snapshots)
    assert schema is not None
    assert not validate_output_schema(_select("title", "status", "due", "notes"), schema)
    assert not validate_output_schema(_select(), schema)
    serialized = json.dumps(schema, ensure_ascii=False)
    for value in ("선택한 시험 작업", "미완료", "2026-09-30", "고정한 업무 메모"):
        assert value not in serialized


@pytest.mark.parametrize(
    "value",
    [
        {"items": [{"evidence_ref": "foreign", "field": "status"}]},
        {"items": [{"evidence_ref": "e-task", "field": "unregistered"}]},
        {"items": [{"evidence_ref": "e-task", "field": "status", "value": "completed"}]},
        {"items": [], "answer": "저장했습니다"},
        {"items": [], "approval": "APPROVED"},
        {"items": [{"evidence_ref": "e-task", "field": "status"}] * 2},
        {"items": [{"field": "status"}]},
        {"items": "status"},
    ],
)
def test_materialize_fact_selection__invalid_or_free_text_fields__rejects(
    value: dict[str, Any],
) -> None:
    prompt, snapshots = _input()
    before = deepcopy((value, prompt, snapshots))
    schema = bind_fact_selection_schema(prompt, source_snapshots=snapshots)
    assert schema is not None
    assert validate_output_schema(value, schema)
    with pytest.raises(ValueError):
        materialize_fact_selection(value, prompt_input=prompt, source_snapshots=snapshots)
    assert (value, prompt, snapshots) == before


@pytest.mark.parametrize("status, rendered", [("needsAction", "미완료"), ("completed", "완료")])
def test_materialize_fact_selection__known_status_and_due__uses_existing_renderer(
    status: str,
    rendered: str,
) -> None:
    prompt, snapshots = _input(
        {
            "title": "작업",
            "status": status,
            "due": "2026-09-30T00:00:00.000Z",
        }
    )
    selection = _select("status", "due")
    before = deepcopy((selection, prompt, snapshots))
    draft = materialize_fact_selection(selection, prompt_input=prompt, source_snapshots=snapshots)
    assert draft is not None
    assert set(draft) == {"schema_version", "answer", "evidence_refs"}
    assert draft["schema_version"] == 2
    assert draft["evidence_refs"] == ["e-task"]
    assert rendered in draft["answer"] and "2026-09-30" in draft["answer"]
    assert "진행 중" not in draft["answer"]
    assert "2099" not in draft["answer"]
    assert (selection, prompt, snapshots) == before


@pytest.mark.parametrize("status", [None, "inProgress", "", "MISSING"])
def test_build_fact_catalog__unknown_status__omits_only_unavailable_fact(
    status: str | None,
) -> None:
    fields: dict[str, object] = {"title": "작업", "due": "2026-09-30", "notes": "메모"}
    if status != "MISSING":
        fields["status"] = status
    prompt, snapshots = _input(fields)
    catalog = build_fact_catalog(prompt, source_snapshots=snapshots)
    assert {row["field"] for row in catalog} == {"title", "due", "notes"}
    with pytest.raises(ValueError):
        materialize_fact_selection(
            _select("status"), prompt_input=prompt, source_snapshots=snapshots
        )


@pytest.mark.parametrize("due", [None, "", "tomorrow", "2026-02-30", "2026-13-01"])
def test_build_fact_catalog__invalid_due__does_not_invent_date(due: str | None) -> None:
    prompt, snapshots = _input({"title": "작업", "status": "needsAction", "due": due})
    assert {row["field"] for row in build_fact_catalog(prompt, source_snapshots=snapshots)} == {
        "title",
        "status",
    }
    with pytest.raises(ValueError):
        materialize_fact_selection(_select("due"), prompt_input=prompt, source_snapshots=snapshots)


def test_build_fact_catalog__notes_contain_metadata_text__never_reinterprets_body() -> None:
    notes = "status: completed\ndue: 2099-01-01\ntitle: 가짜 제목"
    prompt, snapshots = _input({"title": "진짜 제목", "notes": notes})
    catalog = build_fact_catalog(prompt, source_snapshots=snapshots)
    assert {row["field"] for row in catalog} == {"title", "notes"}
    escaped_notes = "status: completed\ndue: 2099\\-01\\-01\ntitle: 가짜 제목"
    assert {row["field"]: row["rendered_value"] for row in catalog} == {
        "title": "진짜 제목",
        "notes": escaped_notes,
    }
    draft = materialize_fact_selection(
        _select("notes"), prompt_input=prompt, source_snapshots=snapshots
    )
    assert draft is not None
    assert draft["answer"] == "메모(원문):\n" + "\n".join(
        f"> {line}" for line in escaped_notes.split("\n")
    )
    with pytest.raises(ValueError):
        materialize_fact_selection(
            _select("status"), prompt_input=prompt, source_snapshots=snapshots
        )


@pytest.mark.parametrize(
    "drift",
    ["snapshot_missing", "hash", "stale", "handle", "not_approved", "no_evidence", "conflict"],
)
def test_bind_fact_selection_schema__unbound_or_conflicting_source__returns_no_candidate(
    drift: str,
) -> None:
    prompt, snapshots = _input()
    if drift == "snapshot_missing":
        snapshots.clear()
    elif drift == "hash":
        snapshots["e-task"]["status"] = "completed"
    elif drift == "stale":
        prompt["evidence"][0]["locator"]["source_version_ref"] = "sha256:stale"
    elif drift == "handle":
        prompt["evidence"][0]["resource_handle"] = "task:another"
    elif drift == "not_approved":
        prompt["answer_outline"]["evidence_refs"] = []
    elif drift == "no_evidence":
        prompt["evidence"] = []
    else:
        peer = {**deepcopy(prompt["evidence"][0]), "evidence_id": "e-conflict"}
        prompt["evidence"].append(peer)
        prompt["answer_outline"]["evidence_refs"].append("e-conflict")
        snapshots.update(
            bind_task_calendar_snapshots(
                [peer],
                {
                    "e-conflict": {
                        "title": "다른 버전",
                        "status": "completed",
                    }
                },
            )
        )
    before = deepcopy((prompt, snapshots))
    assert build_fact_catalog(prompt, source_snapshots=snapshots) == []
    assert bind_fact_selection_schema(prompt, source_snapshots=snapshots) is None
    assert (
        materialize_fact_selection(_select(), prompt_input=prompt, source_snapshots=snapshots)
        is None
    )
    with pytest.raises(ValueError):
        materialize_fact_selection(
            _select("status"), prompt_input=prompt, source_snapshots=snapshots
        )
    assert (prompt, snapshots) == before


def test_materialize_fact_selection__empty_selection__defers_without_empty_answer_claim() -> None:
    prompt, snapshots = _input()
    assert (
        materialize_fact_selection(_select(), prompt_input=prompt, source_snapshots=snapshots)
        is None
    )


def test_build_fact_catalog__empty_literal_fields__distinguishes_present_from_missing() -> None:
    prompt, snapshots = _input({"title": "", "notes": ""})
    assert {
        row["field"]: row["rendered_value"]
        for row in build_fact_catalog(prompt, source_snapshots=snapshots)
    } == {"title": "", "notes": ""}


def test_build_fact_catalog__unapproved_peer__cannot_replace_approved_snapshot() -> None:
    prompt, snapshots = _input()
    peer = {**deepcopy(prompt["evidence"][0]), "evidence_id": "e-hidden"}
    prompt["evidence"].append(peer)
    snapshots.update(bind_task_calendar_snapshots([peer], {"e-hidden": {"status": "completed"}}))
    catalog = build_fact_catalog(prompt, source_snapshots=snapshots)
    assert {row["evidence_ref"] for row in catalog} == {"e-task"}
    assert next(row["rendered_value"] for row in catalog if row["field"] == "status") == "미완료"


def test_bind_fact_selection_schema__multiple_tasks__does_not_expand_lookup_scope() -> None:
    prompt, snapshots = _input()
    other: dict[str, object] = {
        "evidence_id": "e-other",
        "resource_handle": "task:two",
        "excerpt": "another",
    }
    prompt["evidence"].append(other)
    prompt["answer_outline"]["evidence_refs"].append("e-other")
    snapshots.update(bind_task_calendar_snapshots([other], {"e-other": {"status": "completed"}}))
    assert build_fact_catalog(prompt, source_snapshots=snapshots) == []
    assert bind_fact_selection_schema(prompt, source_snapshots=snapshots) is None


def test_build_fact_catalog__same_snapshot_chunks__preserves_approved_citation_choices() -> None:
    prompt, snapshots = _input()
    peer = {**deepcopy(prompt["evidence"][0]), "evidence_id": "e-peer"}
    prompt["evidence"].extend([deepcopy(prompt["evidence"][0]), peer])
    prompt["answer_outline"]["evidence_refs"].append("e-peer")
    snapshots["e-peer"] = deepcopy(snapshots["e-task"])
    catalog = build_fact_catalog(prompt, source_snapshots=snapshots)
    assert len(catalog) == 8
    assert len({(row["evidence_ref"], row["field"]) for row in catalog}) == 8
    selection = {
        "items": [
            {"evidence_ref": "e-task", "field": "status"},
            {"evidence_ref": "e-peer", "field": "due"},
        ]
    }
    draft = materialize_fact_selection(selection, prompt_input=prompt, source_snapshots=snapshots)
    assert draft is not None
    assert draft["evidence_refs"] == ["e-task", "e-peer"]
    assert "미완료" in draft["answer"] and "2026-09-30" in draft["answer"]


def test_build_fact_catalog__no_valid_fact__does_not_claim_available_evidence_answer() -> None:
    prompt, snapshots = _input({"status": "UNKNOWN", "due": "invalid", "notes": None})
    assert build_fact_catalog(prompt, source_snapshots=snapshots) == []
    assert bind_fact_selection_schema(prompt, source_snapshots=snapshots) is None


def test_materialize_fact_selection__html_and_markdown_literal__remains_quoted_data() -> None:
    prompt, snapshots = _input({"notes": "<img src=x>\n[link](https://example.invalid)"})
    draft = materialize_fact_selection(
        _select("notes"), prompt_input=prompt, source_snapshots=snapshots
    )
    assert draft is not None
    assert "<img" not in draft["answer"]
    assert "[link](" not in draft["answer"]
    assert draft["answer"].startswith("메모(원문):\n> &lt;img src\\=x&gt;")
