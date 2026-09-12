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


def _decisions(*, sources: dict[str, list[str]] | None = None) -> dict[str, object]:
    sources = sources or {}
    return {
        "source_dependencies": [
            (
                {
                    "resource_type": candidate["resource_type"],
                    "dependency": "SOURCE_REQUIRED",
                    "required_information": sources[candidate["resource_type"]],
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


def test_registry_candidates__are_exact_read_capabilities() -> None:
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
def test_source_schema__rejects_non_exact_and_invalid_decisions(
    mutate: Callable[[list[dict[str, object]]], object],
) -> None:
    candidate = _decisions()
    items = cast(list[dict[str, object]], candidate["source_dependencies"])
    mutate(items)

    assert validate_output_schema(
        candidate,
        source_dependencies.build_source_dependency_output_schema(_CANDIDATES).json_schema,
    )


def test_source_validation__preserves_cross_resource_dependencies() -> None:
    candidate = _decisions(sources={"TASK": ["준비 상황"], "CALENDAR_EVENT": ["인쇄소 일정"]})

    assert (
        source_dependencies.validate_source_dependency_candidate(
            candidate,
            source_candidates=_CANDIDATES,
        )
        == candidate
    )
