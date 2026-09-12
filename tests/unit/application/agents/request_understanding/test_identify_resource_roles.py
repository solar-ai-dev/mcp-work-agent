from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import cast

import pytest

from google_work_agent.application.agents.request_understanding.identify_resource_roles import (
    build_resource_role_candidates,
    build_resource_role_decision_output_schema,
    normalize_resource_role_decisions,
    validate_resource_role_decision_candidate,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

_CANDIDATES = build_resource_role_candidates(load_signed_tool_registry())


def _decisions(
    *,
    sources: dict[str, list[str]] | None = None,
    outputs: dict[str, str] | None = None,
) -> dict[str, object]:
    sources = sources or {}
    outputs = outputs or {}
    items: list[dict[str, object]] = []
    for candidate in _CANDIDATES:
        resource_type = candidate["resource_type"]
        information = sources.get(resource_type)
        effect = outputs.get(resource_type)
        if information is not None and effect is not None:
            items.append(
                {
                    "resource_type": resource_type,
                    "role": "SOURCE_AND_OUTPUT",
                    "required_information": information,
                    "effect": effect,
                }
            )
        elif information is not None:
            items.append(
                {
                    "resource_type": resource_type,
                    "role": "SOURCE",
                    "required_information": information,
                }
            )
        elif effect is not None:
            items.append(
                {"resource_type": resource_type, "role": "OUTPUT", "effect": effect}
            )
        else:
            items.append({"resource_type": resource_type, "role": "NONE"})
    return {"resource_decisions": items}


def test_registry_candidates__preserve_catalog_order_and_capability_intersection() -> None:
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
    assert by_resource["GMAIL_DRAFT"] == {
        "resource_type": "GMAIL_DRAFT",
        "allowed_roles": ["NONE", "SOURCE", "OUTPUT", "SOURCE_AND_OUTPUT"],
        "allowed_output_effects": ["CREATE", "UPDATE"],
    }
    assert by_resource["GMAIL_THREAD"] == {
        "resource_type": "GMAIL_THREAD",
        "allowed_roles": ["NONE", "SOURCE"],
        "allowed_output_effects": [],
    }


def test_cross_source_draft__normalizes_role_decisions_to_existing_contract() -> None:
    candidate = validate_resource_role_decision_candidate(
        _decisions(
            sources={"TASK": ["준비 상황"], "CALENDAR_EVENT": ["인쇄소 일정"]},
            outputs={"GMAIL_DRAFT": "CREATE"},
        ),
        resource_candidates=_CANDIDATES,
    )

    assert normalize_resource_role_decisions(
        candidate,
        resource_candidates=_CANDIDATES,
    ) == {
        "source_reads": [
            {"resource_type": "TASK", "required_information": ["준비 상황"]},
            {
                "resource_type": "CALENDAR_EVENT",
                "required_information": ["인쇄소 일정"],
            },
        ],
        "outputs": [{"resource_type": "GMAIL_DRAFT", "effect": "CREATE"}],
    }


def test_role_decision_schema__rejects_output_only_existing_resource_update() -> None:
    candidate = _decisions(outputs={"GITHUB_ISSUE": "UPDATE"})

    errors = validate_output_schema(
        candidate,
        build_resource_role_decision_output_schema(_CANDIDATES).json_schema,
    )

    assert errors


def test_role_decision_schema__allows_output_only_resource_create() -> None:
    candidate = _decisions(outputs={"GITHUB_ISSUE": "CREATE"})

    errors = validate_output_schema(
        candidate,
        build_resource_role_decision_output_schema(_CANDIDATES).json_schema,
    )

    assert errors == []


@pytest.mark.parametrize(
    ("sources", "outputs", "expected_source", "expected_output"),
    [
        (
            {"GMAIL_DRAFT": ["기존 본문과 identity"]},
            {"GMAIL_DRAFT": "UPDATE"},
            ["GMAIL_DRAFT"],
            [("GMAIL_DRAFT", "UPDATE")],
        ),
        ({"GMAIL_THREAD": ["최종 일정"]}, {}, ["GMAIL_THREAD"], []),
        ({}, {"TASK": "CREATE"}, [], [("TASK", "CREATE")]),
        (
            {"TASK": ["기존 identity"]},
            {"TASK": "UPDATE"},
            ["TASK"],
            [("TASK", "UPDATE")],
        ),
    ],
)
def test_role_combinations__preserve_source_output_and_unrelated_none(
    sources: dict[str, list[str]],
    outputs: dict[str, str],
    expected_source: list[str],
    expected_output: list[tuple[str, str]],
) -> None:
    raw = _decisions(sources=sources, outputs=outputs)
    candidate = validate_resource_role_decision_candidate(
        raw,
        resource_candidates=_CANDIDATES,
    )
    normalized = normalize_resource_role_decisions(
        candidate,
        resource_candidates=_CANDIDATES,
    )

    assert [source["resource_type"] for source in normalized["source_reads"]] == (
        expected_source
    )
    assert [
        (output["resource_type"], output["effect"]) for output in normalized["outputs"]
    ] == expected_output
    relevant = set(expected_source) | {resource_type for resource_type, _ in expected_output}
    assert all(
        decision["role"] == "NONE"
        for decision in candidate["resource_decisions"]
        if decision["resource_type"] not in relevant
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda items: items.pop(),
        lambda items: items.append({"resource_type": "UNREGISTERED", "role": "NONE"}),
        lambda items: items.__setitem__(1, deepcopy(items[0])),
        lambda items: items[0].update({"effect": "CREATE"}),
        lambda items: items[2].update(
            {"role": "SOURCE", "required_information": [], "effect": "UPDATE"}
        ),
        lambda items: items[1].update({"role": "OUTPUT", "effect": "CREATE"}),
    ],
)
def test_role_decision_schema__rejects_missing_extra_duplicate_and_invalid_combinations(
    mutate: Callable[[list[dict[str, object]]], object],
) -> None:
    candidate = _decisions()
    items = cast(list[dict[str, object]], candidate["resource_decisions"])
    mutate(items)

    errors = validate_output_schema(
        candidate,
        build_resource_role_decision_output_schema(_CANDIDATES).json_schema,
    )

    assert errors
