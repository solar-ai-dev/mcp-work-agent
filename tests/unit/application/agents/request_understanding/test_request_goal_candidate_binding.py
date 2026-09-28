from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.planning.project_request_intent_for_work_units import (
    project_request_intent_for_work_units,
)
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_responsibilities,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_dependencies,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)
from google_work_agent.application.agents.request_understanding.identify_goal import (
    identify_goal_with_budget,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def _candidate(source_reads: list[dict[str, Any]]) -> dict[str, Any]:
    requests = ("메일의 기한으로 초안을 만들어줘.", "작업 상태로 별도 초안을 만들어줘.")
    request_text = " ".join(requests)
    unit_ids = ("work-1", "work-2")
    constraints: dict[str, Any] = {
        field: []
        for field in (
            "search_terms",
            "business_concepts",
            "person",
            "sender",
            "recipient",
            "subject",
            "period",
            "additional_constraints",
        )
    }
    constraints["coverage_requirement"] = {
        "value": "NOT_COLLECTION",
        "work_unit_ids": list(unit_ids),
    }
    requested_work = {
        "work_units": [
            {
                "unit_id": unit_id,
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": request_text.index(text),
                        "end_offset": request_text.index(text) + len(text),
                        "source_text": text,
                    }
                ],
            }
            for unit_id, text in zip(unit_ids, requests, strict=True)
        ],
        "work_relations": [],
    }
    candidate = goal_schema.validate_request_goal_candidate(
        {
            "goal": request_text,
            "completion_conditions": list(requests),
            "constraints": constraints,
            "analysis_requirement": "NONE",
        },
        resource_responsibilities={
            "source_reads": source_reads,
            "outputs": [
                {"resource_type": "GMAIL_DRAFT", "effect": "CREATE", "work_unit_ids": [unit_id]}
                for unit_id in unit_ids
            ],
        },
        effect_prohibitions={"effect_prohibitions": []},
        requested_work=requested_work,
        work_unit_ids=unit_ids,
        schema=goal_schema.identify_goal_output_schema(unit_ids),
    )
    return finalize_intent(
        candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-bound-source-information",
        user_request=request_text,
    )


def _source(resource_type: str, facts: list[str], work_unit_ids: list[str]) -> dict[str, Any]:
    return {
        "resource_type": resource_type,
        "required_information": facts,
        "target_scope": "CRITERIA",
        "work_unit_ids": work_unit_ids,
    }


def _information(intent: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in intent["constraints"] if item["field"] == "required_information"]


def _prompt_ref(node_name: str) -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test", prompt_id=f"request_understanding.{node_name}",
        prompt_version="1", content_hash="test", agent_role="request_understanding",
        subgraph_name="request_understanding", node_name=node_name, node_state="INITIAL",
        purpose=node_name, input_schema_version="v1", output_schema_version="v1",
    )


def test_source_information__disjoint_work_bindings__survive_planning_projection() -> None:
    sources = [
        _source("GMAIL_THREAD", ["contract deadline"], ["work-1"]),
        _source("TASK", ["current status"], ["work-2"]),
    ]
    original = deepcopy(sources)
    intent = _candidate(sources)

    assert sources == original
    assert _information(intent) == [
        {
            "kind": "USER_REQUIREMENT",
            "field": "required_information",
            "value": ["contract deadline"],
            "work_unit_ids": ["work-1"],
        },
        {
            "kind": "USER_REQUIREMENT",
            "field": "required_information",
            "value": ["current status"],
            "work_unit_ids": ["work-2"],
        },
    ]
    for unit_id, expected in (("work-1", "contract deadline"), ("work-2", "current status")):
        projected = project_request_intent_for_work_units(intent, work_unit_ids=[unit_id])
        assert [item["value"] for item in _information(projected)] == [[expected]]
        assert projected["resource_responsibilities"]["outputs"] == [
            {
                "resource_type": "GMAIL_DRAFT",
                "effect": "CREATE",
                "work_unit_ids": [unit_id],
            }
        ]


@pytest.mark.parametrize("unit_id,own_fact", [("work-1", "due"), ("work-2", "start")])
def test_source_information__shared_and_local_bindings__remain_distinct(
    unit_id: str,
    own_fact: str,
) -> None:
    intent = _candidate(
        [
            _source("GMAIL_THREAD", ["common context"], ["work-1", "work-2"]),
            _source("TASK", ["due"], ["work-1"]),
            _source("CALENDAR_EVENT", ["start"], ["work-2"]),
        ]
    )
    projected = project_request_intent_for_work_units(intent, work_unit_ids=[unit_id])

    assert [item["value"] for item in _information(projected)] == [["common context"], [own_fact]]
    assert all("provenance" not in item for item in _information(intent))
    assert _information(intent)[0]["work_unit_ids"] == ["work-1", "work-2"]


def test_source_information__same_binding__deduplicates_without_extra_constraints() -> None:
    intent = _candidate(
        [
            _source("GMAIL_THREAD", ["due", "owner"], ["work-1"]),
            _source("TASK", ["owner", "status"], ["work-1"]),
        ]
    )

    assert [item["value"] for item in _information(intent)] == [["due", "owner", "status"]]
    assert not _information(project_request_intent_for_work_units(intent, work_unit_ids=["work-2"]))


def test_source_information__no_sources__does_not_invent_requirement() -> None:
    assert not _information(_candidate([]))


@pytest.mark.parametrize(
    "sources",
    [
        [
            _source("GMAIL_THREAD", ["contract deadline"], ["work-1"]),
            _source("TASK", ["current status"], ["work-2"]),
        ],
        [
            _source("GMAIL_THREAD", ["context"], ["work-1", "work-2"]),
            _source("TASK", ["owner", "status"], ["work-1"]),
        ],
        [
            _source("GMAIL_THREAD", ["due", "owner"], ["work-1"]),
            _source("TASK", ["owner", "status"], ["work-1"]),
        ],
    ],
    ids=["disjoint", "shared-and-local", "same-binding"],
)
def test_target_confirmation__new_source_information__keeps_owner_work_binding(
    sources: list[dict[str, Any]],
) -> None:
    initial = _candidate([])
    prior = {
        key: value
        for key, value in initial.items()
        if key not in {"schema_version", "meta", "ambiguity"}
    }
    prior["effect_prohibitions"] = [{"effect": "SEND", "work_unit_ids": ["work-2"]}]
    original = deepcopy(prior)
    registry = load_signed_tool_registry()
    source_candidates = source_dependencies.build_source_dependency_candidates(registry)
    by_resource = {source["resource_type"]: source for source in sources}
    raw = {
        "source_dependencies": [
            {**by_resource[item["resource_type"]], "dependency": "SOURCE_REQUIRED"}
            if item["resource_type"] in by_resource
            else {
                "resource_type": item["resource_type"],
                "dependency": "SOURCE_NOT_REQUIRED",
            }
            for item in source_candidates
        ]
    }
    runtime = FakeStructuredInferencePort(outputs=[raw])
    request = WorkflowStartRequest(
        run_id="run", conversation_id="conversation", workflow_key="workflow",
        entry_mode="AGENT_SEARCH", requested_mode="LOCAL_GPU",
        request_text=prior["goal"], selected_resource_ids=(), selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request", "command", "v1"),
    )
    result, _ = identify_goal_with_budget(
        llm_runtime=runtime,
        prompt_ref=_prompt_ref("identify_goal"),
        requested_work_prompt_ref=_prompt_ref("identify_requested_work"),
        work_relation_prompt_ref=_prompt_ref("identify_work_relations"),
        source_dependency_prompt_ref=_prompt_ref("identify_source_dependencies"),
        output_responsibility_prompt_ref=_prompt_ref("identify_output_responsibilities"),
        effect_prohibition_prompt_ref=_prompt_ref("identify_effect_prohibitions"),
        source_status_prompt_ref=_prompt_ref("identify_source_status"),
        request=request,
        retry_budget=build_default_run_budget(),
        source_dependency_candidates=source_candidates,
        output_responsibility_candidates=(
            output_responsibilities.build_output_responsibility_candidates(registry)
        ),
        prior_goal_candidate=prior,
        prior_ambiguity_candidate={
            "requires_confirmation": True,
            "reason_codes": ["MISSING_TARGET_RESOURCE"],
            "missing_fields": ["target_resource"],
        },
        confirmation_response={
            "schema_version": 1,
            "response_kind": "FREE_TEXT",
            "free_text": "관련 납품 자료",
            "selected_option": None,
        },
    )
    finalized = finalize_intent(
        result,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="confirmed-intent", user_request=request.request_text,
        confirmation_response_text="관련 납품 자료",
    )
    normal = _candidate(finalized["resource_responsibilities"]["source_reads"])

    assert prior == original
    assert _information(finalized) == _information(normal)
    assert finalized["goal"] == prior["goal"]
    assert finalized["completion_conditions"] == prior["completion_conditions"]
    assert finalized["effect_prohibitions"] == prior["effect_prohibitions"]
    assert finalized["resource_responsibilities"]["outputs"] == (
        prior["resource_responsibilities"]["outputs"]
    )
    for unit_id in ("work-1", "work-2"):
        assert _information(project_request_intent_for_work_units(
            finalized, work_unit_ids=[unit_id],
        )) == _information(project_request_intent_for_work_units(
            normal, work_unit_ids=[unit_id],
        ))
    assert [call["prompt_ref"].prompt_id for call in runtime.calls] == [
        "request_understanding.identify_source_dependencies"
    ]
