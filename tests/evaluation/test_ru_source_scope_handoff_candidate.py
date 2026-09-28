"""Connected contract tests, not model semantic scores; no Provider or model I/O."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast

import pytest
from scripts.ru_scope_authority_candidate import ScopeAuthorityCandidate
from scripts.ru_source_scope_handoff_candidate import (
    SOURCE_SCOPE_CONTRACT,
    SourceScopeHandoffCandidate,
    source_scope_handoff_candidate,
)

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.agents.request_understanding import (
    identify_goal as goal_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.request_understanding import (
    preserve_explicit_search_anchors as projection_ops,
)
from google_work_agent.application.agents.request_understanding import (
    validate_intent as intent_ops,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.agents.tool_routing.resolve_policy_preconditions import (
    ScopeExpansionResolver,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

REQUEST = "작업과 일정만 근거로 현황을 알려줘. 별도로 메일만 확인해 담당자를 알려줘."
UNITS = ("work-1", "work-2")


def _scope(
    field: str = "required_sources",
    value: Any = None,
    span: str = "작업과 일정만",
    unit: str = "work-1",
    source: str = "USER_REQUEST",
) -> dict[str, Any]:
    return {
        "field": field,
        "value": ["TASK", "CALENDAR"] if value is None else value,
        "work_unit_ids": [unit],
        "provenance": {"source": source, "source_text": span},
    }


def _raw(*additional: Any) -> dict[str, Any]:
    constraints = {
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
    return {
        "goal": REQUEST,
        "completion_conditions": ["근거로 답한다."],
        "constraints": {
            **constraints,
            "coverage_requirement": {"value": "NOT_COLLECTION", "work_unit_ids": list(UNITS)},
            "additional_constraints": list(additional),
        },
        "analysis_requirement": "NONE",
    }


def _work(request: str = REQUEST) -> dict[str, Any]:
    return {
        "work_units": [
            {
                "unit_id": unit,
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": 0,
                        "end_offset": len(request),
                        "source_text": request,
                    }
                ],
            }
            for unit in UNITS
        ],
        "work_relations": [],
    }


def _normalize(raw: Any, *, request: str = REQUEST, confirmation: str | None = None) -> Any:
    sources = {"USER_REQUEST": request}
    if confirmation is not None:
        sources["CONFIRMATION_RESPONSE"] = confirmation
    return goal_schema.validate_request_goal_candidate(
        raw,
        resource_responsibilities={
            "source_reads": [
                {
                    "resource_type": "TASK",
                    "required_information": ["상태"],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": ["work-1"],
                }
            ],
            "outputs": [],
        },
        effect_prohibitions={"effect_prohibitions": []},
        requested_work=_work(request),
        work_unit_ids=UNITS,
        provenance_sources=sources,
        schema=goal_schema.identify_goal_output_schema(UNITS),
    )


def _finalize(candidate: Any, *, request: str = REQUEST, confirmation: str | None = None) -> Any:
    return finalize_intent(
        candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-scope-handoff",
        user_request=request,
        confirmation_response_text=confirmation,
    )


def test_goal_provenance_source_projection_final_intent_and_route_keep_same_work_scope() -> None:
    raw = _raw(_scope(), _scope(value="EMAIL", span="메일만", unit="work-2"))
    original = deepcopy(raw)
    seen = []
    source_candidates = tuple(
        {
            "resource_type": resource,
            "read_tool_ids": [f"read-{resource}"],
            "owned_fact_kinds": ["identity", "body"],
        }
        for resource in ("TASK", "CALENDAR_EVENT", "GMAIL_THREAD")
    )
    source_output = {
        "source_dependencies": [
            {
                "resource_type": "TASK",
                "dependency": "SOURCE_REQUIRED",
                "required_information": ["상태"],
                "target_scope": "CRITERIA",
                "work_unit_ids": ["work-1"],
            },
            {"resource_type": "CALENDAR_EVENT", "dependency": "SOURCE_NOT_REQUIRED"},
            {
                "resource_type": "GMAIL_THREAD",
                "dependency": "SOURCE_REQUIRED",
                "required_information": ["담당자"],
                "target_scope": "CRITERIA",
                "work_unit_ids": ["work-2"],
            },
        ]
    }

    class Runtime:
        def infer(self, _mode: Any, _prompt: Any, projection: Any, schema: Any) -> Any:
            seen.append(deepcopy(projection))
            assert not validate_output_schema(source_output, schema.json_schema)
            return SimpleNamespace(structured_output=deepcopy(source_output))

    with source_scope_handoff_candidate(user_request=REQUEST, work_unit_ids=UNITS) as session:
        schema = goal_schema.identify_goal_output_schema(UNITS)
        assert not validate_output_schema(raw, schema.json_schema)
        projected = projection_ops.project_extractive_source_goal(raw, request_text=REQUEST)
        result = source_ops.identify_source_dependencies(
            llm_runtime=cast(Any, Runtime()),
            requested_mode="LOCAL_GPU",
            prompt_ref=cast(Any, None),
            prompt_input={"user_request": REQUEST, "requested_work": _work()},
            goal_candidate=projected,
            source_candidates=cast(Any, source_candidates),
            work_unit_ids=UNITS,
        )
        candidate = _normalize(raw)
        intent = _finalize(candidate)
        scopes = [item for item in intent["constraints"] if item["field"] == "required_sources"]
        assert scopes == projected["constraints"]["additional_constraints"]
        assert scopes[0]["value"] == ["TASK", "CALENDAR"]
        assert scopes[0]["provenance"]["source_text"] == "작업과 일정만"
        assert scopes[1]["work_unit_ids"] == ["work-2"]
        allowed = ("google_workspace", "GMAIL_THREAD", "SOURCE_DEPENDENCY")
        assert (
            ScopeExpansionResolver().out_of_scope_reads(
                request_intent=intent,
                required_reads=[allowed],
                category_of=coarse_resource_category,
                required_work_unit_bindings={allowed: ("work-2",)},
            )
            == ()
        )
        assert ScopeExpansionResolver().out_of_scope_reads(
            request_intent=intent,
            required_reads=[allowed],
            category_of=coarse_resource_category,
            required_work_unit_bindings={allowed: ("work-1",)},
        ) == (allowed,)
        assert session.events[0]["scope_hash"] == session.events[1]["scope_hash"]
    assert len(seen) == 1  # Existing Source operation only; no new scope inference.
    assert seen[0]["source_candidates"] == list(source_candidates)  # No prefiltered capability set.
    assert result == source_output  # Allowed CALENDAR is not forced into a required READ.
    assert raw == original


@pytest.mark.parametrize(
    "mutate",
    [
        lambda scope: scope.pop("provenance"),
        lambda scope: scope["provenance"].update(source_text="없는 근거"),
        lambda scope: scope["provenance"].update(source_text="  "),
        lambda scope: scope["provenance"].update(source="CONFIRMATION_RESPONSE"),
        lambda scope: scope.update(value=["GMAIL_THREAD"]),
        lambda scope: scope.update(value=["TASK", "TASK"]),
        lambda scope: scope.update(work_unit_ids=["foreign-work"]),
        lambda scope: scope.update(work_unit_ids=[]),
    ],
)
def test_invalid_scope_fails_before_source_operation(mutate: Any) -> None:
    scope = _scope()
    mutate(scope)
    with (
        source_scope_handoff_candidate(user_request=REQUEST, work_unit_ids=UNITS),
        pytest.raises(ValueError, match="Source scope"),
    ):
        projection_ops.project_extractive_source_goal(_raw(scope), request_text=REQUEST)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda item: item["provenance"].update(start_offset=1),
        lambda item: item["provenance"].update(end_offset=9999),
        lambda item: item.pop("provenance"),
        lambda item: item.update(kind="RESOURCE"),
    ],
)
def test_finalizer_does_not_rebind_tampered_provenance(tamper: Any) -> None:
    with source_scope_handoff_candidate(user_request=REQUEST, work_unit_ids=UNITS):
        candidate = _normalize(_raw(_scope()))
        scope = next(x for x in candidate["constraints"] if x["field"] == "required_sources")
        tamper(scope)
        with pytest.raises(ValueError, match="Source scope"):
            _finalize(candidate)


def test_confirmation_source_binding_is_exact_and_current_run_only() -> None:
    confirmation = "메일은 제외해 주세요."
    scope = _scope("forbidden_sources", "EMAIL", "메일은 제외", source="CONFIRMATION_RESPONSE")
    with source_scope_handoff_candidate(
        user_request=REQUEST,
        confirmation_response_text=confirmation,
        work_unit_ids=UNITS,
    ):
        candidate = _normalize(_raw(scope), confirmation=confirmation)
        intent = _finalize(candidate, confirmation=confirmation)
        normalized = next(x for x in intent["constraints"] if x["field"] == "forbidden_sources")
        assert normalized["provenance"] == {
            "source": "CONFIRMATION_RESPONSE",
            "source_text": "메일은 제외",
            "start_offset": 0,
            "end_offset": 6,
        }
        with pytest.raises(ValueError, match="authority differs"):
            _finalize(candidate, confirmation="다른 확인 응답")


@pytest.mark.parametrize(
    "user_text,resource",
    [
        ("선택한 메일을 읽고 다른 메일은 검색하지 마.", "GMAIL_THREAD"),
        ("선택한 일정의 시간을 알려줘. 다른 캘린더는 검색하지 마.", "CALENDAR_EVENT"),
        ("메일과 작업을 근거로 현황을 알려줘.", "GMAIL_THREAD"),
    ],
)
def test_selected_identity_or_source_mention_does_not_invent_category_scope(
    user_text: str,
    resource: str,
) -> None:
    raw = _raw()
    selected = {"resource_type": resource, "resource_id": "exact-selected-id"}
    raw["selected_resource_refs"] = [selected]
    with source_scope_handoff_candidate(user_request=user_text, work_unit_ids=UNITS):
        projected = projection_ops.project_extractive_source_goal(raw, request_text=user_text)
        assert projected["constraints"]["additional_constraints"] == []
        assert projected["selected_resource_refs"] == [selected]
        raw.pop("selected_resource_refs")
        intent = _finalize(_normalize(raw, request=user_text), request=user_text)
        read = ("google_workspace", resource, "RESOURCE_SELECTED")
        assert (
            ScopeExpansionResolver().out_of_scope_reads(
                request_intent=intent,
                required_reads=[read],
                category_of=coarse_resource_category,
                required_work_unit_bindings={read: ("work-1",)},
            )
            == ()
        )


def test_wrong_model_category_is_not_semantically_corrected_by_validator() -> None:
    # Exact provenance proves origin, not that the model chose the right category.
    raw = _raw(_scope(value="EMAIL"))
    with source_scope_handoff_candidate(user_request=REQUEST, work_unit_ids=UNITS):
        projected = projection_ops.project_extractive_source_goal(raw, request_text=REQUEST)
        intent = _finalize(_normalize(raw))
        assert projected["constraints"]["additional_constraints"][0]["value"] == "EMAIL"
        assert (
            next(x for x in intent["constraints"] if x["field"] == "required_sources")["value"]
            == "EMAIL"
        )


def test_non_scope_provenance_and_status_guards_are_not_weakened() -> None:
    with source_scope_handoff_candidate(user_request=REQUEST, work_unit_ids=UNITS):
        schema = goal_schema.identify_goal_output_schema(UNITS)
        invalid = _scope()
        invalid.update(field="title", value="title")
        assert validate_output_schema(_raw(invalid), schema.json_schema)
        with pytest.raises(ValueError):
            intent_ops._validate_provenance_binding(
                cast(Any, {"kind": "SCOPE", "field": "status", "value": "COMPLETED"}),
                "$.constraints[0]",
                provenance_sources={"USER_REQUEST": REQUEST},
                effects=["READ"],
                resource_hints=["TASK"],
            )


def test_context_restores_schema_and_all_production_function_references_on_error() -> None:
    schema = deepcopy(goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema)
    projection = goal_ops.project_extractive_source_goal
    normalizer = goal_schema.validate_request_goal_candidate
    provenance_check = intent_ops._validate_provenance_binding
    with (
        pytest.raises(RuntimeError),
        source_scope_handoff_candidate(
            user_request=REQUEST,
            work_unit_ids=UNITS,
        ),
    ):
        raise RuntimeError("bounded candidate failure")
    assert goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema == schema
    assert goal_ops.project_extractive_source_goal is projection
    assert goal_schema.validate_request_goal_candidate is normalizer
    assert intent_ops._validate_provenance_binding is provenance_check


@pytest.mark.parametrize("scope_produced", [True, False])
@pytest.mark.parametrize("repair", [False, True])
def test_candidate_actual_wire_preserves_v16_goal_and_source_runtime_contract(
    monkeypatch: pytest.MonkeyPatch,
    scope_produced: bool,
    repair: bool,
) -> None:
    class Delegate:
        def infer(self, *args: Any) -> Any:
            raise AssertionError("no additional owner call")

    registry = load_development_tool_registry()
    constructor = {
        "delegate": Delegate(),
        "tool_catalog": registry,
        "model_id": "test",
        "sampling_seed": 180,
    }
    baseline = ScopeAuthorityCandidate(**constructor)
    candidate = SourceScopeHandoffCandidate(**constructor)
    assert candidate._goal_output_instruction == baseline._goal_output_instruction
    assert (
        candidate.binding["goal_output_prompt_sha256"]
        == baseline.binding["goal_output_prompt_sha256"]
    )
    assert candidate.binding["candidate_id"] == "ru-source-scope-handoff-v24"
    raw = _raw(*([_scope()] if scope_produced else []))
    goal_raw = {**raw, "requested_result_mode": "ANSWER_ONLY", "requested_outputs": []}
    candidates = source_ops.build_source_dependency_candidates(registry)
    valid_source = {
        "source_dependencies": [
            {"resource_type": item["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
            for item in candidates
        ]
    }
    invalid_source = {**deepcopy(valid_source), "requested_outputs": []}
    responses = [goal_raw, *([invalid_source] if repair else []), valid_source]
    calls = []

    def dispatch(**kwargs: Any) -> Any:
        payload = deepcopy(kwargs["payload"])
        calls.append(payload)
        return {
            "response": json.dumps(responses[len(calls) - 1]),
            "model": "test",
            "prompt_eval_count": 3,
            "eval_count": 5,
            "total_duration": 1000000,
        }

    monkeypatch.setattr(transport, "_post_json", dispatch)
    prompt_registry = PromptRegistry()
    context = {"user_request": REQUEST, "selected_resource_refs": [], "requested_work": _work()}
    with source_scope_handoff_candidate(user_request=REQUEST) as session:
        goal_result = candidate.infer(
            "LOCAL_GPU",
            prompt_registry.lookup_for_evaluation("request_understanding.identify_goal"),
            context,
            goal_schema.identify_goal_output_schema(UNITS),
        )
        assert session.work_unit_ids == UNITS
        assert goal_result.structured_output == raw
        projected = projection_ops.project_extractive_source_goal(raw, request_text=REQUEST)
        source_input = {
            **context,
            "goal_candidate": projected,
            "source_candidates": list(candidates),
        }
        result = candidate.infer(
            "LOCAL_GPU",
            prompt_registry.lookup_for_evaluation(
                "request_understanding.identify_source_dependencies"
            ),
            source_input,
            source_ops.build_source_dependency_output_schema(
                candidates,
                work_unit_ids=UNITS,
            ),
        )
        assert result.structured_output == valid_source
        assert candidate.events[-1]["input"] == source_input
        assert len(projected["constraints"]["additional_constraints"]) == int(scope_produced)
    assert len(calls) == 2 + int(repair)
    assert calls[0]["system"] == baseline._goal_output_instruction
    assert (
        calls[0]["options"]["temperature"] == 0.0
    )  # Same v16 helper policy, not Product Goal 0.1.
    source_first = calls[1]
    assert source_first["system"].endswith(SOURCE_SCOPE_CONTRACT)
    assert (
        hashlib.sha256(source_first["system"].encode()).hexdigest()
        == candidate.events[-1]["instruction_sha256"]
    )
    assert json.loads(source_first["prompt"])["input"] == source_input
    assert (
        source_first["format"]
        == source_ops.build_source_dependency_output_schema(
            candidates,
            work_unit_ids=UNITS,
        ).json_schema
    )
    for call in calls[1:]:
        assert call["options"]["temperature"] == 0.05
        assert call["options"]["seed"] == 180
    if repair:
        assert json.loads(calls[2]["prompt"])["input"]["base_projection"] == source_input
    assert result.input_tokens == 3 * (1 + int(repair))
    assert result.output_tokens == 5 * (1 + int(repair))


def test_source_class_rejects_scope_tampering_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = SourceScopeHandoffCandidate(
        delegate=object(),
        tool_catalog=load_development_tool_registry(),
        model_id="test",
        sampling_seed=180,
    )
    monkeypatch.setattr(
        transport,
        "_post_json",
        lambda **kwargs: pytest.fail("must reject before model I/O"),
    )
    with source_scope_handoff_candidate(user_request=REQUEST, work_unit_ids=UNITS):
        projected = projection_ops.project_extractive_source_goal(
            _raw(_scope()), request_text=REQUEST
        )
        projected["constraints"]["additional_constraints"][0]["value"] = "EMAIL"
        with pytest.raises(ValueError, match="validated Goal projection"):
            candidate.infer(
                "LOCAL_GPU",
                PromptRegistry().lookup_for_evaluation(
                    "request_understanding.identify_source_dependencies"
                ),
                {"user_request": REQUEST, "requested_work": _work(), "goal_candidate": projected},
                None,
            )
