"""V16 vocabulary consistency only: fake inference, no semantic or Provider execution."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, cast

import pytest
from evaluation.request_semantic_authority_candidate import (
    GOAL_OUTPUT_MODALITY_PROMPT_PATH,
    _goal_output_modality_schema,
)
from scripts.ru_scope_authority_candidate import (
    SCOPE_FIELD_DESCRIPTION,
    ScopeAuthorityCandidate,
    scope_authority_candidate,
    scope_authority_instruction,
    scope_constraints_description,
)
from scripts.ru_source_scope_candidate import source_scope_candidate

from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1


def _without_descriptions(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_descriptions(item) for key, item in value.items() if key != "description"
        }
    if isinstance(value, list):
        return [_without_descriptions(item) for item in value]
    return value


def _schema() -> Any:
    return _goal_output_modality_schema(
        work_unit_ids=("work-1", "work-2"),
        output_candidates=({"resource_type": "TASK", "allowed_output_effects": ["CREATE"]},),
    )


def _goal(*additional: dict[str, Any]) -> dict[str, Any]:
    constraints: dict[str, Any] = {
        name: []
        for name in (
            "search_terms",
            "business_concepts",
            "person",
            "sender",
            "recipient",
            "subject",
            "period",
        )
    }
    constraints["coverage_requirement"] = {"value": "NOT_COLLECTION", "work_unit_ids": ["work-1"]}
    constraints["additional_constraints"] = list(additional)
    return {
        "goal": "사용자가 요청한 정보를 확인한다.",
        "completion_conditions": ["근거로 답한다."],
        "constraints": constraints,
        "analysis_requirement": "NONE",
        "requested_outputs": [],
        "requested_result_mode": "ANSWER_ONLY",
    }


def test_prompt_changes_only_one_existing_ownership_sentence() -> None:
    original = GOAL_OUTPUT_MODALITY_PROMPT_PATH.read_text(encoding="utf-8").strip()
    revised = scope_authority_instruction(original)
    assert len(original.splitlines()) == len(revised.splitlines())
    changed = [
        (before, after)
        for before, after in zip(original.splitlines(), revised.splitlines(), strict=True)
        if before != after
    ]
    assert changed == [
        (
            "- Source, Tool, Query, 승인, 실행 순서는 판단하지 않는다.",
            "- Source responsibility와 capability 선택, Tool, Query, "
            "승인, 실행 순서는 판단하지 않는다.",
        )
    ]


@pytest.mark.parametrize("copies", [0, 2])
def test_prompt_replacement_fails_if_existing_boundary_drifted(copies: int) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        scope_authority_instruction(
            "- Source, Tool, Query, 승인, 실행 순서는 판단하지 않는다.\n" * copies
        )


@pytest.mark.parametrize("copies", [0, 2])
def test_constraint_description_replacement_rejects_upstream_drift(copies: int) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        scope_constraints_description("그 밖의 명시적 실행 값은 additional_constraints" * copies)


def test_v16_preserves_v14_schema_keys_allowed_values_and_cardinalities() -> None:
    product_before = deepcopy(goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema)
    with source_scope_candidate():
        v14 = deepcopy(_schema().json_schema)
    with scope_authority_candidate():
        candidate = ScopeAuthorityCandidate(
            delegate=_NoDelegate(),
            tool_catalog=load_development_tool_registry(),
            model_id="test",
            sampling_seed=4,
        )
        context_schema_before = deepcopy(_schema().json_schema)
        v16 = cast(
            dict[str, Any],
            deepcopy(
                candidate._build_goal_output_schema(
                    work_unit_ids=("work-1", "work-2"),
                    output_candidates=(
                        {"resource_type": "TASK", "allowed_output_effects": ["CREATE"]},
                    ),
                ).json_schema
            ),
        )
        assert _schema().json_schema == context_schema_before
        item = v16["properties"]["constraints"]["properties"]["additional_constraints"]["items"]
        assert item["properties"]["field"]["description"] == SCOPE_FIELD_DESCRIPTION
    assert goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema == product_before
    assert _without_descriptions(v16) == _without_descriptions(v14)
    item14 = v14["properties"]["constraints"]["properties"]["additional_constraints"]["items"]
    item14["properties"]["field"]["description"] = SCOPE_FIELD_DESCRIPTION
    constraints14 = v14["properties"]["constraints"]
    constraints14["description"] = constraints14["description"].replace(
        "그 밖의 명시적 실행 값은 additional_constraints",
        "그 밖의 명시적 업무값과 Source 범위 제약은 additional_constraints",
        1,
    )
    assert v16 == v14
    assert (
        candidate.binding["scope_constraints_description_sha256"]
        == hashlib.sha256(
            v16["properties"]["constraints"]["description"].encode("utf-8")
        ).hexdigest()
    )
    assert "배타적" in SCOPE_FIELD_DESCRIPTION
    assert "단순히 필요한 Source 목록이 아니다" in SCOPE_FIELD_DESCRIPTION
    assert "category 전체의 조회 제외" in SCOPE_FIELD_DESCRIPTION
    assert "선택 identity" in SCOPE_FIELD_DESCRIPTION


def test_schema_and_normalizer_mapping_restore_after_failure() -> None:
    before = deepcopy(goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema)
    fields = deepcopy(goal_schema._ADDITIONAL_CONSTRAINT_FIELD_KINDS)
    with pytest.raises(RuntimeError), scope_authority_candidate():
        raise RuntimeError("test failure")
    assert goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema == before
    assert fields == goal_schema._ADDITIONAL_CONSTRAINT_FIELD_KINDS


class _NoDelegate:
    def infer(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Goal must use one existing candidate call, not an additional owner")


@pytest.mark.parametrize(
    "user_text,selected",
    [
        ("메일과 작업을 근거로 진행 상황을 알려줘.", []),
        (
            "선택한 메일을 읽고 다른 메일은 검색하지 마.",
            [{"resource_type": "gmail_thread", "resource_id": "selected-mail"}],
        ),
        (
            "선택한 일정의 시간을 알려줘. 다른 캘린더는 검색하지 마.",
            [
                {
                    "resource_type": "calendar_event",
                    "resource_id": "selected-event",
                    "parent_id": "parent",
                }
            ],
        ),
    ],
)
def test_candidate_does_not_turn_source_need_or_identity_scope_into_category_ban(
    monkeypatch: pytest.MonkeyPatch, user_text: str, selected: list[dict[str, str]]
) -> None:
    candidate = ScopeAuthorityCandidate(
        delegate=_NoDelegate(),
        tool_catalog=load_development_tool_registry(),
        model_id="test",
        sampling_seed=4,
    )
    projection = {
        "user_request": user_text,
        "selected_resource_refs": selected,
        "requested_work": {"work_units": [{"unit_id": "work-1"}]},
    }
    original = deepcopy(projection)
    calls: list[dict[str, Any]] = []
    raw = _goal()

    def invoke(**kwargs: Any) -> Any:
        calls.append(deepcopy(kwargs))
        assert not validate_output_schema(raw, kwargs["schema"].json_schema)
        return (
            deepcopy(raw),
            StructuredInferenceResultV1(
                schema_version=1,
                structured_output=deepcopy(raw),
                provider="TEST",
                model="test",
                actual_runtime="LOCAL_GPU",
                input_tokens=10,
                output_tokens=20,
                latency_ms=30,
                fallback_reason=None,
            ),
            [{"attempt": "FIRST", "structured_output": deepcopy(raw), "schema_errors": []}],
        )

    monkeypatch.setattr(candidate, "_invoke_candidate", invoke)
    prompt = PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.identify_goal",
        prompt_version="test",
        content_hash="test",
        agent_role="test",
        subgraph_name="test",
        node_name="test",
        node_state="test",
        purpose="test",
        input_schema_version="test",
        output_schema_version="test",
    )
    with scope_authority_candidate():
        result = candidate.infer(
            "LOCAL_GPU", prompt, projection, goal_schema.identify_goal_output_schema(("work-1",))
        )
    assert len(calls) == 1
    assert projection == original
    assert calls[0]["prompt_input"]["user_request"] == user_text
    assert calls[0]["prompt_input"]["selected_resource_refs"] == selected
    assert result.structured_output["constraints"] == raw["constraints"]
    assert candidate.events[0]["raw_output"] == raw
    assert candidate.binding["goal_output_prompt_sha256"] == calls[0]["prompt_ref"].content_hash
    assert (
        candidate.binding["goal_output_prompt_sha256"]
        == hashlib.sha256(calls[0]["instruction"].encode("utf-8")).hexdigest()
    )
    assert (
        candidate.binding["baseline_goal_output_prompt_sha256"]
        == hashlib.sha256(
            GOAL_OUTPUT_MODALITY_PROMPT_PATH.read_text(encoding="utf-8").strip().encode("utf-8")
        ).hexdigest()
    )
    assert (
        candidate.binding["scope_field_description_sha256"]
        == hashlib.sha256(SCOPE_FIELD_DESCRIPTION.encode("utf-8")).hexdigest()
    )
    assert (
        candidate.binding["scope_constraints_description_sha256"]
        == hashlib.sha256(
            calls[0]["schema"]
            .json_schema["properties"]["constraints"]["description"]
            .encode("utf-8")
        ).hexdigest()
    )
