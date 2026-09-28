"""Shape/handoff checks only; manually selected branches are not model-quality evidence."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, cast

import pytest
from scripts.answer_fact_selection_candidate import bind_fact_selection_schema
from scripts.answer_rendering_choice_candidate import (
    bind_answer_rendering_choice_schema,
    materialize_answer_rendering_choice,
)
from tests.support.task_calendar_evidence import bind_task_calendar_snapshots

from google_work_agent.application.agents.planning.compose_answer import (
    answer_draft_output_schema,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def _input() -> tuple[dict[str, Any], dict[str, dict[str, object]]]:
    evidence: list[dict[str, object]] = [
        {"evidence_id": "e-task", "resource_handle": "task:one", "excerpt": "작업의 확인 항목"}
    ]
    snapshots = bind_task_calendar_snapshots(
        evidence,
        {
            "e-task": {
                "title": "온보딩 확인",
                "status": "needsAction",
                "due": "2026-08-10T00:00:00.000Z",
                "notes": "계정 발급 여부 확인. 장비 수령 여부 확인.",
            }
        },
    )
    return {
        "user_request": "선택한 작업의 상태와 기한을 알려줘. 새 작업은 만들지 마.",
        "answer_outline": {"sections": ["확인 정보"], "evidence_refs": ["e-task"]},
        "evidence": evidence,
        "request_intent": {"requested_effect_hints": ["READ"], "analysis_requirement": "NONE"},
    }, snapshots


def _facts(*fields: str) -> dict[str, object]:
    return {
        "mode": "FACT_REFERENCES",
        "items": [{"evidence_ref": "e-task", "field": field} for field in fields],
    }


def _prose(answer: str = "상태와 기한을 확인한 답변") -> dict[str, object]:
    return {
        "mode": "PROSE",
        "schema_version": 2,
        "answer": answer,
        "evidence_refs": ["e-task"],
    }


def _without_mode(branch: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(branch)
    del result["properties"]["mode"]
    result["required"].remove("mode")
    return result


def test_bind_choice__valid_catalog__retains_both_existing_branch_contracts() -> None:
    prompt, snapshots = _input()
    before = deepcopy((prompt, snapshots))
    schema = bind_answer_rendering_choice_schema(prompt, source_snapshots=snapshots)
    branches = cast(list[dict[str, Any]], schema["oneOf"])
    assert len(branches) == 2
    fact_branch, prose_branch = branches
    assert _without_mode(fact_branch) == bind_fact_selection_schema(
        prompt, source_snapshots=snapshots
    )
    assert _without_mode(prose_branch) == answer_draft_output_schema(["e-task"]).json_schema
    assert not validate_output_schema(_facts("status", "due"), schema)
    assert not validate_output_schema(_prose(), schema)
    assert (prompt, snapshots) == before
    serialized = json.dumps(schema, ensure_ascii=False)
    assert "계정 발급" not in serialized and "2026-08-10" not in serialized


@pytest.mark.parametrize("snapshots_kind", ["missing", "stale", "hash_mismatch"])
def test_bind_choice__invalid_catalog__retains_only_prose(snapshots_kind: str) -> None:
    prompt, snapshots = _input()
    if snapshots_kind == "missing":
        snapshots = {}
    elif snapshots_kind == "stale":
        prompt["evidence"][0]["locator"]["source_version_ref"] = "sha256:other"
    else:
        snapshots["e-task"]["status"] = "completed"
    schema = bind_answer_rendering_choice_schema(prompt, source_snapshots=snapshots)
    assert cast(dict[str, object], schema["properties"])["mode"] == {"const": "PROSE"}
    assert not validate_output_schema(_prose(), schema)
    assert validate_output_schema(_facts(), schema)
    assert materialize_answer_rendering_choice(
        _prose(), prompt_input=prompt, source_snapshots=snapshots
    ) == {key: value for key, value in _prose().items() if key != "mode"}
    with pytest.raises(ValueError, match="invalid answer rendering choice"):
        materialize_answer_rendering_choice(
            _facts("status"), prompt_input=prompt, source_snapshots=snapshots
        )


@pytest.mark.parametrize(
    "value",
    [
        {**_facts("status"), "answer": "임의 답변"},
        {**_prose(), "items": []},
        {**_prose(), "mode": "AUTOMATIC"},
        {key: value for key, value in _prose().items() if key != "mode"},
        {**_prose(), "evidence_refs": ["foreign"]},
        {**_prose(), "schema_version": 1},
        {"mode": "FACT_REFERENCES", "items": [{"evidence_ref": "foreign", "field": "status"}]},
        {"mode": "FACT_REFERENCES", "items": [{"evidence_ref": "e-task", "field": "progress"}]},
        {
            "mode": "FACT_REFERENCES",
            "items": [{"evidence_ref": "e-task", "field": "status", "value": "completed"}],
        },
        _facts("status", "status"),
    ],
)
def test_materialize_choice__mixed_or_invalid_response__rejects_without_fallback(
    value: dict[str, Any],
) -> None:
    prompt, snapshots = _input()
    before = deepcopy((value, prompt, snapshots))
    with pytest.raises(ValueError, match="invalid answer rendering choice"):
        materialize_answer_rendering_choice(
            value, prompt_input=prompt, source_snapshots=snapshots
        )
    assert (value, prompt, snapshots) == before


def test_materialize_choice__fact_selection__uses_081_values_and_current_citations() -> None:
    prompt, snapshots = _input()
    value = _facts("status", "due")
    before = deepcopy((value, prompt, snapshots))
    result = materialize_answer_rendering_choice(
        value, prompt_input=prompt, source_snapshots=snapshots
    )
    assert result == {
        "schema_version": 2,
        "answer": "상태: 미완료\n\n예정일: 2026-08-10",
        "evidence_refs": ["e-task"],
    }
    assert (value, prompt, snapshots) == before


def test_materialize_choice__empty_selection__does_not_claim_missing_search_or_prose() -> None:
    prompt, snapshots = _input()
    assert materialize_answer_rendering_choice(
        _facts(), prompt_input=prompt, source_snapshots=snapshots
    ) is None


def test_materialize_choice__prose_with_catalog__preserves_answer_without_correction() -> None:
    prompt, snapshots = _input()
    value = _prose("사용자가 요청한 정리문. 이 내용의 사실성은 별도 검수한다.")
    before = deepcopy((value, prompt, snapshots))
    result = materialize_answer_rendering_choice(
        value, prompt_input=prompt, source_snapshots=snapshots
    )
    assert result == {key: item for key, item in value.items() if key != "mode"}
    assert result is not value and result["evidence_refs"] is not value["evidence_refs"]
    assert (value, prompt, snapshots) == before


def test_materialize_choice__quote_forbidden_request__does_not_hide_wrong_mode_semantics() -> None:
    prompt, snapshots = _input()
    prompt["user_request"] = "메모의 확인할 항목을 정리해 줘. 원문 문장은 그대로 인용하지 마."
    before = deepcopy((prompt, snapshots))
    selected = materialize_answer_rendering_choice(
        _facts("notes"), prompt_input=prompt, source_snapshots=snapshots
    )
    # Structurally legal, semantically wrong for this request; no lexical repair.
    assert selected is not None and "메모(원문):\n> " in selected["answer"]
    prose = _prose("확인할 항목은 계정 발급 여부와 장비 수령 여부입니다.")
    assert materialize_answer_rendering_choice(
        prose, prompt_input=prompt, source_snapshots=snapshots
    ) == {key: value for key, value in prose.items() if key != "mode"}
    assert (prompt, snapshots) == before


def test_materialize_choice__missing_requested_field__does_not_complete_answer() -> None:
    prompt, snapshots = _input()
    selected = materialize_answer_rendering_choice(
        _facts("status"), prompt_input=prompt, source_snapshots=snapshots
    )
    assert selected is not None and selected["answer"] == "상태: 미완료"


def test_bind_choice__provided_material_without_evidence__keeps_prose_contract() -> None:
    prompt = {"user_request": "제공한 문장을 요약해 줘.", "answer_outline": {"evidence_refs": []}}
    schema = bind_answer_rendering_choice_schema(prompt, source_snapshots=None)
    value = {**_prose("제공한 내용 요약"), "evidence_refs": []}
    assert not validate_output_schema(value, schema)
    assert materialize_answer_rendering_choice(
        value, prompt_input=prompt, source_snapshots=None
    ) == {key: item for key, item in value.items() if key != "mode"}


def test_bind_choice__multiple_approved_resources__does_not_generalize_fact_renderer() -> None:
    prompt, snapshots = _input()
    other: dict[str, object] = {
        "evidence_id": "e-other",
        "resource_handle": "task:two",
        "excerpt": "다른 작업",
    }
    prompt["evidence"].append(other)
    prompt["answer_outline"]["evidence_refs"].append("e-other")
    snapshots.update(bind_task_calendar_snapshots([other], {"e-other": {"status": "completed"}}))
    schema = bind_answer_rendering_choice_schema(prompt, source_snapshots=snapshots)
    assert cast(dict[str, object], schema["properties"])["mode"] == {"const": "PROSE"}
    assert not validate_output_schema(_prose(), schema)
    assert validate_output_schema(_facts("status"), schema)


@pytest.mark.parametrize("refs", [None, "e-task", [None], [""]])
def test_bind_choice__malformed_outline__does_not_infer_allowed_citations(refs: object) -> None:
    prompt, snapshots = _input()
    prompt["answer_outline"]["evidence_refs"] = refs
    with pytest.raises(ValueError, match="answer_outline.evidence_refs"):
        bind_answer_rendering_choice_schema(prompt, source_snapshots=snapshots)
