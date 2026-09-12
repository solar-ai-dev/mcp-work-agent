from __future__ import annotations

import pytest

from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_responsibilities,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_dependencies,
)
from google_work_agent.application.agents.request_understanding import (
    merge_resource_responsibilities as responsibility_merge,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    output_responsibility_decision,
    source_dependency_decision,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)

_CATALOG = load_signed_tool_registry()
_SOURCE_CANDIDATES = source_dependencies.build_source_dependency_candidates(_CATALOG)
_OUTPUT_CANDIDATES = output_responsibilities.build_output_responsibility_candidates(_CATALOG)


def _source(
    *, values: dict[str, list[str]] | None = None
) -> source_dependency_decision.SourceDependencyDecisionCandidateV1:
    values = values or {}
    return {
        "source_dependencies": [
            (
                {
                    "resource_type": candidate["resource_type"],
                    "dependency": "SOURCE_REQUIRED",
                    "required_information": values[candidate["resource_type"]],
                }
                if candidate["resource_type"] in values
                else {
                    "resource_type": candidate["resource_type"],
                    "dependency": "SOURCE_NOT_REQUIRED",
                }
            )
            for candidate in _SOURCE_CANDIDATES
        ]
    }


def _output(
    *, values: dict[str, str] | None = None
) -> output_responsibility_decision.OutputResponsibilityDecisionCandidateV1:
    values = values or {}
    return {
        "output_responsibilities": [
            {
                "resource_type": candidate["resource_type"],
                "effect": values.get(candidate["resource_type"], "NONE"),
            }
            for candidate in _OUTPUT_CANDIDATES
        ]
    }


@pytest.mark.parametrize(
    ("sources", "outputs", "expected_sources", "expected_outputs"),
    [
        (
            {"TASK": ["준비 상황"], "CALENDAR_EVENT": ["인쇄소 일정"]},
            {"GMAIL_DRAFT": "CREATE"},
            ["TASK", "CALENDAR_EVENT"],
            [("GMAIL_DRAFT", "CREATE")],
        ),
        (
            {"GMAIL_DRAFT": ["기존 identity와 본문"]},
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
def test_atomic_decisions__after_validation__merge_to_canonical_contract(
    sources: dict[str, list[str]],
    outputs: dict[str, str],
    expected_sources: list[str],
    expected_outputs: list[tuple[str, str]],
) -> None:
    merged = responsibility_merge.merge_resource_responsibilities(
        source_decisions=_source(values=sources),
        output_decisions=_output(values=outputs),
        source_candidates=_SOURCE_CANDIDATES,
        output_candidates=_OUTPUT_CANDIDATES,
    )

    assert [item["resource_type"] for item in merged["source_reads"]] == expected_sources
    assert [
        (item["resource_type"], item["effect"]) for item in merged["outputs"]
    ] == expected_outputs
