from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import cast

import pytest

from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_dependencies,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

_CANDIDATES = source_dependencies.build_source_dependency_candidates(load_signed_tool_registry())


def _decisions(
    *,
    sources: dict[str, tuple[list[str], str]] | None = None,
) -> dict[str, object]:
    sources = sources or {}
    return {
        "source_dependencies": [
            (
                {
                    "resource_type": candidate["resource_type"],
                    "dependency": "SOURCE_REQUIRED",
                    "required_information": sources[candidate["resource_type"]][0],
                    "target_scope": sources[candidate["resource_type"]][1],
                }
                if candidate["resource_type"] in sources
                else {
                    "resource_type": candidate["resource_type"],
                    "dependency": "SOURCE_NOT_REQUIRED",
                }
            )
            for candidate in _CANDIDATES
        ]
    }


def test_registry_candidates__from_runtime_registry__match_read_capabilities() -> None:
    assert [candidate["resource_type"] for candidate in _CANDIDATES] == [
        "GMAIL_THREAD",
        "GMAIL_MESSAGE",
        "GMAIL_DRAFT",
        "GMAIL_ATTACHMENT",
        "TASK_LIST",
        "TASK",
        "CALENDAR",
        "CALENDAR_EVENT",
        "CALENDAR_FREEBUSY",
        "GITHUB_ISSUE",
    ]
    by_resource = {candidate["resource_type"]: candidate for candidate in _CANDIDATES}
    assert by_resource["GMAIL_DRAFT"]["read_tool_ids"] == [
        "gmail_get_draft",
        "gmail_search_drafts",
    ]
    assert by_resource["TASK"]["read_tool_ids"] == [
        "tasks_get_task",
        "tasks_list_tasks",
    ]
    assert by_resource["TASK_LIST"]["owned_fact_kinds"] == [
        "task_list_identity",
        "task_list_title",
    ]
    assert "completion_status" in by_resource["TASK"]["owned_fact_kinds"]
    assert "start" in by_resource["CALENDAR_EVENT"]["owned_fact_kinds"]
    assert "start" not in by_resource["CALENDAR"]["owned_fact_kinds"]
    assert source_dependencies.resource_identity_fact_kind("CALENDAR_EVENT") == "event_identity"
    assert source_dependencies.resource_identity_fact_kind("TASK") == "task_identity"
    assert source_dependencies.resource_identity_fact_kind("UNKNOWN") is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda items: items.pop(),
        lambda items: items.append(
            {"resource_type": "UNREGISTERED", "dependency": "SOURCE_NOT_REQUIRED"}
        ),
        lambda items: items.__setitem__(1, deepcopy(items[0])),
        lambda items: items[0].update({"required_information": ["unexpected"]}),
        lambda items: items[0].update({"dependency": "SOURCE_REQUIRED"}),
    ],
)
def test_source_schema__with_non_exact_or_invalid_decisions__rejects_candidate(
    mutate: Callable[[list[dict[str, object]]], object],
) -> None:
    candidate = _decisions()
    items = cast(list[dict[str, object]], candidate["source_dependencies"])
    mutate(items)

    assert validate_output_schema(
        candidate,
        source_dependencies.build_source_dependency_output_schema(_CANDIDATES).json_schema,
    )


def test_source_validation__with_cross_resource_request__preserves_dependencies() -> None:
    candidate = _decisions(
        sources={
            "TASK": (["준비 상황"], "CRITERIA"),
            "CALENDAR_EVENT": (["인쇄소 일정"], "CRITERIA"),
        }
    )

    assert (
        source_dependencies.validate_source_dependency_candidate(
            candidate,
            source_candidates=_CANDIDATES,
        )
        == candidate
    )


def test_source_validation__singular_event__preserves_requested_facts_without_identity() -> None:
    candidate = _decisions(
        sources={"CALENDAR_EVENT": (["start", "end"], "SINGULAR")}
    )

    assert not validate_output_schema(
        candidate,
        source_dependencies.build_source_dependency_output_schema(_CANDIDATES).json_schema,
    )
    validated = source_dependencies.validate_source_dependency_candidate(
        candidate,
        source_candidates=_CANDIDATES,
    )
    by_resource = {
        decision["resource_type"]: decision for decision in validated["source_dependencies"]
    }
    assert by_resource["CALENDAR_EVENT"]["required_information"] == [
        "start",
        "end",
    ]
    assert by_resource["CALENDAR_EVENT"]["target_scope"] == "SINGULAR"
    assert by_resource["CALENDAR"]["dependency"] == "SOURCE_NOT_REQUIRED"


def test_source_validation__criteria_event__allows_fact_without_identity() -> None:
    candidate = _decisions(sources={"CALENDAR_EVENT": (["status"], "CRITERIA")})

    assert not validate_output_schema(
        candidate,
        source_dependencies.build_source_dependency_output_schema(_CANDIDATES).json_schema,
    )
    assert (
        source_dependencies.validate_source_dependency_candidate(
            candidate,
            source_candidates=_CANDIDATES,
        )
        == candidate
    )


def test_source_schema__source_required__requires_non_empty_information() -> None:
    candidate = _decisions(sources={"TASK": ([], "CRITERIA")})

    assert validate_output_schema(
        candidate,
        source_dependencies.build_source_dependency_output_schema(_CANDIDATES).json_schema,
    )


def test_source_schema__general_request__allows_no_existing_source() -> None:
    candidate = _decisions()

    assert not validate_output_schema(
        candidate,
        source_dependencies.build_source_dependency_output_schema(_CANDIDATES).json_schema,
    )


def test_source_semantics__source_free_answer__allows_all_not_required() -> None:
    candidate = source_dependencies.validate_source_dependency_candidate(
        _decisions(),
        source_candidates=_CANDIDATES,
    )

    assert source_dependencies.validate_source_dependency_semantics(
        candidate,
        goal_candidate={"constraints": {"search_terms": [], "business_concepts": []}},
        has_output_responsibilities=False,
    ) == _decisions()


def test_source_semantics__standalone_output__does_not_force_retrieval() -> None:
    candidate = source_dependencies.validate_source_dependency_candidate(
        _decisions(),
        source_candidates=_CANDIDATES,
    )

    assert source_dependencies.validate_source_dependency_semantics(
        candidate,
        goal_candidate={"constraints": {"search_terms": ["Project Anchor"]}},
        has_output_responsibilities=True,
    ) == _decisions()


def test_source_semantics__external_answer_facts__reject_all_not_required() -> None:
    candidate = source_dependencies.validate_source_dependency_candidate(
        _decisions(),
        source_candidates=_CANDIDATES,
    )

    with pytest.raises(
        source_dependencies.SourceDependencyContradictionError
    ) as raised:
        source_dependencies.validate_source_dependency_semantics(
            candidate,
            goal_candidate={
                "constraints": {
                    "search_terms": ["Atlas"],
                    "business_concepts": ["최종 출고일", "담당자"],
                }
            },
            has_output_responsibilities=False,
        )

    assert raised.value.reason_code == "INTENT_SOURCE_DEPENDENCY_CONTRADICTION"
    assert raised.value.candidate_output == _decisions()


def test_source_schema__confirmed_target__requires_a_source_without_choosing_its_type() -> None:
    schema = source_dependencies.build_source_dependency_output_schema(
        _CANDIDATES,
        require_at_least_one_source=True,
    ).json_schema

    assert validate_output_schema(_decisions(), schema)
    assert not validate_output_schema(
        _decisions(sources={"CALENDAR_EVENT": (["start", "end"], "SINGULAR")}), schema
    )
    assert not validate_output_schema(
        _decisions(sources={"TASK": (["completion_status"], "SINGULAR")}), schema
    )


@pytest.mark.parametrize(
    ("required_resource", "excluded_related_resource", "required_information"),
    [
        ("TASK", "TASK_LIST", "현재 상태"),
        ("TASK_LIST", "TASK", "목록 identity"),
        ("CALENDAR_EVENT", "CALENDAR", "시작 시각"),
        ("CALENDAR", "CALENDAR_EVENT", "calendar identity"),
        ("GMAIL_MESSAGE", "GMAIL_THREAD", "개별 본문"),
        ("GMAIL_THREAD", "GMAIL_MESSAGE", "대화 이력"),
    ],
)
def test_source_validation__distinct_resource_fact_owner__is_preserved(
    required_resource: str,
    excluded_related_resource: str,
    required_information: str,
) -> None:
    candidate = _decisions(
        sources={required_resource: ([required_information], "CRITERIA")}
    )

    validated = source_dependencies.validate_source_dependency_candidate(
        candidate,
        source_candidates=_CANDIDATES,
    )
    by_resource = {
        decision["resource_type"]: decision for decision in validated["source_dependencies"]
    }

    assert by_resource[required_resource]["dependency"] == "SOURCE_REQUIRED"
    assert by_resource[excluded_related_resource]["dependency"] == "SOURCE_NOT_REQUIRED"


@pytest.mark.parametrize("target_scope", ["SINGULAR", "CRITERIA"])
def test_source_schema__source_required__accepts_known_target_scope(
    target_scope: str,
) -> None:
    candidate = _decisions(sources={"TASK": (["completion_status"], target_scope)})

    assert not validate_output_schema(
        candidate,
        source_dependencies.build_source_dependency_output_schema(_CANDIDATES).json_schema,
    )


def test_source_schema__source_required__rejects_missing_or_unknown_target_scope() -> None:
    candidate = _decisions(sources={"TASK": (["completion_status"], "SINGULAR")})
    decisions = cast(list[dict[str, object]], candidate["source_dependencies"])
    required = next(item for item in decisions if item["dependency"] == "SOURCE_REQUIRED")
    required.pop("target_scope")
    schema = source_dependencies.build_source_dependency_output_schema(_CANDIDATES).json_schema
    assert validate_output_schema(candidate, schema)

    required["target_scope"] = "UNKNOWN"
    assert validate_output_schema(candidate, schema)


def test_source_schema__source_not_required__rejects_target_scope() -> None:
    candidate = _decisions()
    decisions = cast(list[dict[str, object]], candidate["source_dependencies"])
    decisions[0]["target_scope"] = "CRITERIA"

    assert validate_output_schema(
        candidate,
        source_dependencies.build_source_dependency_output_schema(_CANDIDATES).json_schema,
    )
