"""Actual Planning component inputs, fake semantics: metadata carry only, no model/Provider."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

import pytest
from scripts.planning_work_relation_context_candidate import (
    project_work_relation_context,
    with_work_relation_context,
)

from google_work_agent.application.agents.planning.compose_arguments_per_output_route import (
    compose_arguments_per_output_route,
)
from google_work_agent.application.agents.planning.draft_action_objective_per_output_route import (
    draft_action_objective_per_output_route,
)
from google_work_agent.application.agents.planning.project_request_intent_for_work_units import (
    project_request_intent_for_work_units,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    BoundSelectedToolSchemaV1,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
    RequestIntentV3,
)
from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)

_SPANS = (
    "Prepare a report draft to first@example.test.",
    "Prepare a notice draft using that planned report for second@example.test.",
    "Prepare an independent draft to third@example.test.",
)
_REQUEST = " ".join(_SPANS)


def _intent(*, related: bool = True, internal_product: bool = False) -> RequestIntentV3:
    spans = (
        (
            "Summarize these supplied notes: progress verified.",
            "Prepare a notice draft from that summary for second@example.test.",
            _SPANS[2],
        )
        if internal_product
        else _SPANS
    )
    request_text = " ".join(spans)
    units = [
        {
            "unit_id": f"work-{index + 1}",
            "request_provenance": [
                {
                    "source": "USER_REQUEST",
                    "start_offset": request_text.index(span),
                    "end_offset": request_text.index(span) + len(span),
                    "source_text": span,
                }
            ],
        }
        for index, span in enumerate(spans)
    ]
    return finalize_intent(
        cast(
            RequestGoalCandidateV1,
            {
                "goal": request_text,
                "completion_conditions": [
                    "Provide the summary and prepare two drafts without sending."
                    if internal_product
                    else "Prepare three draft specifications without sending."
                ],
                "constraints": [
                    {
                        "kind": "EMAIL",
                        "field": "recipient",
                        "value": address,
                        "work_unit_ids": [f"work-{index + 1}"],
                    }
                    for index, address in enumerate(
                        ("first@example.test", "second@example.test", "third@example.test")
                    )
                    if not internal_product or index != 0
                ],
                "requested_effect_hints": ["CREATE"],
                "requested_resource_hints": ["GMAIL_DRAFT"],
                "analysis_requirement": "NONE",
                "effect_prohibitions": [
                    {"effect": "SEND", "work_unit_ids": [unit["unit_id"] for unit in units]}
                ],
                "requested_work": {
                    "work_units": units,
                    "work_relations": [
                        {
                            "source_work_unit_id": "work-1",
                            "target_work_unit_id": "work-2",
                            "kind": (
                                "CONSUMES_WORK_PRODUCT"
                                if internal_product
                                else "CONSUMES_PLANNED_SPECIFICATION"
                            ),
                        }
                    ]
                    if related
                    else [],
                },
                "resource_responsibilities": {
                    "source_reads": [],
                    "outputs": [
                        {
                            "resource_type": "GMAIL_DRAFT",
                            "effect": "CREATE",
                            "work_unit_ids": [unit["unit_id"]],
                        }
                        for unit in units
                        if not internal_product or unit["unit_id"] != "work-1"
                    ],
                },
            },
        ),
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="request-intent-context-test",
        user_request=request_text,
    )


def _routes() -> list[dict[str, Any]]:
    return [
        {
            "route_id": f"draft-{index}",
            "resource_type": "GMAIL_DRAFT",
            "connector_id": "google_workspace",
            "effect": "CREATE",
            "selected_tool_id": "gmail_create_draft",
            "reason_codes": [],
            "work_unit_ids": [f"work-{index}"],
        }
        for index in range(1, 4)
    ]


def _run_components(
    intent: RequestIntentV3, *, candidate: bool
) -> tuple[list[dict[str, Any]], object, object]:
    captured: list[dict[str, Any]] = []

    def fake(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        copied = deepcopy(dict(prompt_input))
        captured.append({"prompt_id": prompt_id, "input": copied})
        route = cast(dict[str, Any], copied["output_route"])
        if prompt_id == "planning.draft_action_objective_per_output_route":
            return {
                "schema_version": 1,
                "objective": f"Prepare {route['route_id']}.",
                "scope_constraints": ["Draft only; approval required."],
                "evidence_refs": [],
            }
        assert prompt_id == "planning.compose_arguments_per_output_route"
        return {
            "schema_version": 1,
            "route_id": route["route_id"],
            "arguments": {"payload": {"body": f"Synthetic draft {route['route_id']}."}},
            "evidence_refs": [],
        }

    invoke = (
        with_work_relation_context(request_intent=intent, user_request=_REQUEST, invoke=fake)
        if candidate
        else fake
    )
    routes = _routes()
    objectives = draft_action_objective_per_output_route(
        routes,
        user_request=_REQUEST,
        request_intent=intent,
        work_analysis=None,
        evidence=[],
        invoke=invoke,
    )
    bound = [
        cast(
            BoundSelectedToolSchemaV1,
            {
                **route,
                "schema_version": 1,
                "immutable_arguments": {},
                "argument_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["payload"],
                    "properties": {
                        "payload": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["body"],
                            "properties": {"body": {"type": "string"}},
                        }
                    },
                },
            },
        )
        for route in routes
    ]
    arguments = compose_arguments_per_output_route(
        routes,
        objectives=objectives,
        bound_tool_schemas=bound,
        request_intent=intent,
        invoke=invoke,
    )
    return captured, objectives, arguments


def test_incoming_relation_reaches_both_components_without_reviving_other_work_semantics() -> None:
    intent = _intent()
    before = deepcopy(intent)
    baseline, baseline_objectives, baseline_arguments = _run_components(intent, candidate=False)
    candidate, candidate_objectives, candidate_arguments = _run_components(intent, candidate=True)
    assert len(candidate) == len(baseline) == 6
    assert candidate_objectives == baseline_objectives
    assert candidate_arguments == baseline_arguments
    assert intent == before
    related_calls = 0
    for previous, current in zip(baseline, candidate, strict=True):
        actual = deepcopy(current)
        context = actual["input"].pop("work_relation_context", None)
        assert actual == previous
        local = current["input"]["request_intent"]
        route = current["input"]["output_route"]
        unit_id = route["work_unit_ids"][0]
        assert [item["unit_id"] for item in local["requested_work"]["work_units"]] == [unit_id]
        assert local["requested_work"]["work_relations"] == []
        assert len(local["resource_responsibilities"]["outputs"]) == 1
        assert all(item["work_unit_ids"] == [unit_id] for item in local["constraints"])
        assert local["effect_prohibitions"] == [{"effect": "SEND", "work_unit_ids": [unit_id]}]
        if unit_id != "work-2":
            assert context is None
            continue
        related_calls += 1
        assert context["authority"] == "REQUEST_DEFINITION_ONLY"
        assert context["based_on_request_intent"] == {
            "artifact_id": intent["meta"]["artifact_id"],
            "revision": intent["meta"]["revision"],
        }
        assert context["applicable_work_unit_ids"] == ["work-2"]
        assert (
            context["requested_work"]["work_relations"]
            == intent["requested_work"]["work_relations"]
        )
        assert [unit["unit_id"] for unit in context["requested_work"]["work_units"]] == [
            "work-1",
            "work-2",
        ]
        assert set(context) == {
            "schema_version",
            "authority",
            "based_on_request_intent",
            "applicable_work_unit_ids",
            "requested_work",
        }
        assert (
            validate_requested_work_definition(context["requested_work"], user_request=_REQUEST)
            == context["requested_work"]
        )
    assert related_calls == 2


def test_relation_free_calls_remain_identical() -> None:
    intent = _intent(related=False)
    assert _run_components(intent, candidate=False) == _run_components(intent, candidate=True)


@pytest.mark.parametrize("kind", ["CONSUMES_WORK_PRODUCT", "CONSUMES_PLANNED_SPECIFICATION"])
def test_existing_relation_kind_is_copied_without_becoming_a_result(kind: str) -> None:
    intent = _intent(internal_product=kind == "CONSUMES_WORK_PRODUCT")
    context = project_work_relation_context(
        intent, user_request=intent["goal"], work_unit_ids=["work-2"]
    )
    assert context is not None
    assert context["requested_work"]["work_relations"][0]["kind"] == kind
    assert context["authority"] == "REQUEST_DEFINITION_ONLY"


@pytest.mark.parametrize("source,target", [("work-2", "work-2"), ("unknown", "work-2")])
def test_invalid_relation_endpoints_are_rejected(source: str, target: str) -> None:
    intent = cast(dict[str, Any], _intent())
    intent["requested_work"]["work_relations"][0].update(
        {
            "source_work_unit_id": source,
            "target_work_unit_id": target,
        }
    )
    with pytest.raises(ValueError):
        project_work_relation_context(intent, user_request=_REQUEST, work_unit_ids=["work-2"])


def test_unknown_local_work_or_unfinalized_intent_is_rejected() -> None:
    intent = cast(dict[str, Any], _intent())
    with pytest.raises(ValueError, match="unknown WorkUnit"):
        project_work_relation_context(intent, user_request=_REQUEST, work_unit_ids=["unknown"])
    del intent["meta"]
    with pytest.raises(ValueError, match="finalized RequestIntent"):
        project_work_relation_context(intent, user_request=_REQUEST, work_unit_ids=["work-2"])


def test_invoker_uses_snapshot_and_does_not_intercept_unrelated_prompt() -> None:
    intent = _intent()
    seen: list[Mapping[str, object]] = []

    def fake(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        seen.append(deepcopy(dict(prompt_input)))
        return {"unchanged": prompt_id}

    invoke = with_work_relation_context(request_intent=intent, user_request=_REQUEST, invoke=fake)
    local_intent = project_request_intent_for_work_units(intent, work_unit_ids=["work-2"])
    intent["meta"]["revision"] += 1
    intent["requested_work"]["work_relations"].clear()
    invoke(
        "planning.draft_action_objective_per_output_route",
        {
            "output_route": _routes()[1],
            "request_intent": local_intent,
        },
    )
    context = cast(dict[str, Any], seen[0]["work_relation_context"])
    assert context["based_on_request_intent"]["revision"] == 1
    assert len(context["requested_work"]["work_relations"]) == 1
    untouched = {"source": "unrelated"}
    assert invoke("unrelated", untouched) == {"unchanged": "unrelated"}
    assert seen[-1] == untouched


def test_single_work_and_unrelated_local_binding_do_not_gain_context() -> None:
    intent = project_request_intent_for_work_units(_intent(related=False), work_unit_ids=["work-1"])
    intent["goal"] = _SPANS[0]
    intent["completion_conditions"] = ["Prepare one draft specification without sending."]
    assert (
        project_work_relation_context(intent, user_request=_SPANS[0], work_unit_ids=["work-1"])
        is None
    )
    context = project_work_relation_context(
        _intent(), user_request=_REQUEST, work_unit_ids=["work-2", "work-3"]
    )
    assert context is not None
    assert context["applicable_work_unit_ids"] == ["work-2"]
    assert {unit["unit_id"] for unit in context["requested_work"]["work_units"]} == {
        "work-1",
        "work-2",
    }


def test_stale_relation_authority_is_rejected_before_semantic_call() -> None:
    intent = _intent()
    calls: list[str] = []

    def fake(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        return {}

    invoke = with_work_relation_context(request_intent=intent, user_request=_REQUEST, invoke=fake)
    local_intent = project_request_intent_for_work_units(intent, work_unit_ids=["work-2"])
    local_intent["meta"]["revision"] += 1
    with pytest.raises(ValueError, match="same revision"):
        invoke(
            "planning.compose_arguments_per_output_route",
            {
                "output_route": _routes()[1],
                "request_intent": local_intent,
            },
        )
    assert calls == []
