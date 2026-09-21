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
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    WriteEffectValue,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)

_CATALOG = load_signed_tool_registry()
_SOURCE_CANDIDATES = source_dependencies.build_source_dependency_candidates(_CATALOG)
_OUTPUT_CANDIDATES = output_responsibilities.build_output_responsibility_candidates(_CATALOG)


def _source(
    *, values: dict[str, tuple[list[str], str]] | None = None
) -> source_dependency_decision.SourceDependencyDecisionCandidateV1:
    values = values or {}
    return {
        "source_dependencies": [
            (
                {
                    "resource_type": candidate["resource_type"],
                    "dependency": "SOURCE_REQUIRED",
                    "required_information": values[candidate["resource_type"]][0],
                    "target_scope": values[candidate["resource_type"]][1],
                    "work_unit_ids": ["work-1"],
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
    *, values: dict[str, WriteEffectValue] | None = None
) -> output_responsibility_decision.OutputResponsibilityDecisionCandidateV2:
    values = values or {}
    return {
        "output_responsibilities": [
            {
                "resource_type": candidate["resource_type"],
                "effect": values[candidate["resource_type"]],
                "work_unit_ids": ["work-1"],
            }
            for candidate in _OUTPUT_CANDIDATES
            if candidate["resource_type"] in values
        ]
    }


@pytest.mark.parametrize(
    ("sources", "outputs", "expected_sources", "expected_outputs"),
    [
        (
            {
                "TASK": (["준비 상황"], "CRITERIA"),
                "CALENDAR_EVENT": (["인쇄소 일정"], "CRITERIA"),
            },
            {"GMAIL_DRAFT": "CREATE"},
            ["TASK", "CALENDAR_EVENT"],
            [("GMAIL_DRAFT", "CREATE")],
        ),
        (
            {"GMAIL_DRAFT": (["기존 본문"], "SINGULAR")},
            {"GMAIL_DRAFT": "UPDATE"},
            ["GMAIL_DRAFT"],
            [("GMAIL_DRAFT", "UPDATE")],
        ),
        ({"GMAIL_THREAD": (["최종 일정"], "CRITERIA")}, {}, ["GMAIL_THREAD"], []),
        ({}, {"TASK": "CREATE"}, [], [("TASK", "CREATE")]),
        (
            {"TASK": (["기존 상태"], "SINGULAR")},
            {"TASK": "UPDATE"},
            ["TASK"],
            [("TASK", "UPDATE")],
        ),
    ],
)
def test_atomic_decisions__after_validation__merge_to_canonical_contract(
    sources: dict[str, tuple[list[str], str]],
    outputs: dict[str, WriteEffectValue],
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


def test_merge_resource_responsibilities__with_explicit_item_sources__restores_child_sources(
) -> None:
    merged = responsibility_merge.merge_resource_responsibilities(
        source_decisions=_source(
            values={
                "GMAIL_DRAFT": (["body"], "SINGULAR"),
                "TASK_LIST": (["task_list_title"], "CRITERIA"),
                "TASK": (["completion_status"], "CRITERIA"),
                "CALENDAR": (["calendar_metadata"], "CRITERIA"),
                "CALENDAR_EVENT": (["start", "end"], "CRITERIA"),
            }
        ),
        output_decisions=_output(values={"GMAIL_DRAFT": "CREATE"}),
        source_candidates=_SOURCE_CANDIDATES,
        output_candidates=_OUTPUT_CANDIDATES,
        request_text=(
            "Orion 할 일과 인쇄소 일정 보고 담당자에게 준비 상황을 알릴 메일을 "
            "Gmail 임시보관함에 저장해줘."
        ),
    )

    assert [item["resource_type"] for item in merged["source_reads"]] == [
        "TASK",
        "CALENDAR_EVENT",
    ]
    assert merged["outputs"] == [
        {
            "resource_type": "GMAIL_DRAFT",
            "effect": "CREATE",
            "work_unit_ids": ["work-1"],
        }
    ]


def test_merge_resource_responsibilities__with_typed_mail_fact_source__preserves_source(
) -> None:
    merged = responsibility_merge.merge_resource_responsibilities(
        source_decisions=_source(
            values={
                "GMAIL_THREAD": (
                    ["subject", "participants", "message_history", "timestamps"],
                    "CRITERIA",
                )
            }
        ),
        output_decisions=_output(),
        source_candidates=_SOURCE_CANDIDATES,
        output_candidates=_OUTPUT_CANDIDATES,
        request_text="메일에 나온 Orion 출고 기준과 담당을 확인해줘.",
    )

    assert merged["source_reads"] == [
        {
            "resource_type": "GMAIL_THREAD",
            "required_information": [
                "subject",
                "participants",
                "message_history",
                "timestamps",
            ],
            "target_scope": "CRITERIA",
            "work_unit_ids": ["work-1"],
        }
    ]


def test_merge_resource_responsibilities__with_singular_source__preserves_scope_and_facts() -> (
    None
):
    merged = responsibility_merge.merge_resource_responsibilities(
        source_decisions=_source(
            values={"CALENDAR_EVENT": (["start", "end"], "SINGULAR")}
        ),
        output_decisions=_output(),
        source_candidates=_SOURCE_CANDIDATES,
        output_candidates=_OUTPUT_CANDIDATES,
    )

    assert merged["source_reads"] == [
        {
            "resource_type": "CALENDAR_EVENT",
            "required_information": ["start", "end"],
            "target_scope": "SINGULAR",
            "work_unit_ids": ["work-1"],
        }
    ]
