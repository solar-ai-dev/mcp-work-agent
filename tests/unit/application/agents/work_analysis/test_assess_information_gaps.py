from typing import cast

import pytest

from google_work_agent.application.agents.work_analysis.assess_information_gaps import (
    assess_information_gaps,
    combine_information_gap_assessment,
    require_resolution_for_undetermined_action,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    InformationGapAssessmentV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from tests.support.work_analysis import (
    WorkAnalysisRuntimeFake,
    fact,
    intent,
    output_json_schema,
    prompt_ref,
)


def test_assess_information_gaps__uses_exact_prompt__and_bounded_retrieval_need() -> None:
    output = {
        "disposition": "NEEDS_MORE_DATA",
        "ambiguities": [],
        "retrieval_needs": [
            {"required_information": "current due date", "reason_codes": ["DUE_DATE_MISSING"]}
        ],
        "evidence_refs": ["ev-1"],
        "reason_codes": ["DUE_DATE_MISSING"],
    }
    runtime = WorkAnalysisRuntimeFake(output)

    result = assess_information_gaps(
        request_intent=intent(),
        work_facts=[fact("f1")],
        evidence=[],
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.assess_information_gaps", "assess_information_gaps"),
        allowed_evidence_refs={"ev-1"},
        requested_mode="AUTO",
    )

    assert result == output
    assert (
        cast(PromptReference, runtime.calls[0]["prompt_ref"]).prompt_id
        == "work_analysis.assess_information_gaps"
    )


def test_assess_information__gaps_rejects__unbounded_evidence() -> None:
    runtime = WorkAnalysisRuntimeFake(
        {
            "disposition": "COMPLETE",
            "ambiguities": [],
            "retrieval_needs": [],
            "evidence_refs": ["stale"],
        }
    )
    with pytest.raises(ValueError, match="invalid information-gap schema"):
        assess_information_gaps(
            request_intent=intent(),
            work_facts=[fact("f1")],
            evidence=[],
            llm_runtime=runtime,
            prompt_ref=prompt_ref(
                "work_analysis.assess_information_gaps", "assess_information_gaps"
            ),
            allowed_evidence_refs={"ev-1"},
            requested_mode="AUTO",
        )


def test_assess_information__gaps_exposes_disposition_invariants__to_repair() -> None:
    runtime = WorkAnalysisRuntimeFake(
        {
            "disposition": "COMPLETE",
            "ambiguities": [],
            "retrieval_needs": [],
            "evidence_refs": ["ev-1"],
        }
    )

    assess_information_gaps(
        request_intent=intent(),
        work_facts=[fact("f1")],
        evidence=[],
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.assess_information_gaps", "assess_information_gaps"),
        allowed_evidence_refs={"ev-1"},
        requested_mode="LOCAL_GPU",
    )

    schema = output_json_schema(runtime)
    branches = {branch["properties"]["disposition"]["const"]: branch for branch in schema["oneOf"]}
    assert branches["COMPLETE"]["properties"]["evidence_refs"]["items"]["enum"] == ["ev-1"]
    assert set(branches["COMPLETE"]["required"]) == {
        "disposition",
        "ambiguities",
        "retrieval_needs",
        "evidence_refs",
    }
    assert branches["COMPLETE"]["properties"]["retrieval_needs"]["maxItems"] == 0
    assert branches["NEEDS_MORE_DATA"]["properties"]["retrieval_needs"]["minItems"] == 1
    assert "question" in branches["NEEDS_CONFIRMATION"]["required"]


def test_read_only_gap__genuine_new_choice__preserves_confirmation() -> None:
    result = combine_information_gap_assessment(
        assessment={
            "disposition": "NEEDS_CONFIRMATION",
            "ambiguities": [
                {
                    "code": "MISSING_APPROVED_BUDGET",
                    "description": "The evidence does not include an approved budget.",
                    "requires_confirmation": True,
                    "evidence_refs": ["ev-1"],
                }
            ],
            "retrieval_needs": [],
            "evidence_refs": ["ev-1"],
            "question": "Please provide the approved budget.",
            "options": [],
            "reason_codes": ["MISSING_APPROVED_BUDGET"],
        },
        relation_ambiguities=[],
    )

    assert result["disposition"] == "NEEDS_CONFIRMATION"
    assert result["ambiguities"][0]["requires_confirmation"] is True
    assert result["question"] == "Please provide the approved budget."


def test_write_gap__user_owned_choice__preserves_confirmation() -> None:
    assessment: InformationGapAssessmentV1 = {
        "disposition": "NEEDS_CONFIRMATION",
        "ambiguities": [],
        "retrieval_needs": [],
        "evidence_refs": ["ev-1"],
        "question": "Which calendar should receive the event?",
        "options": ["primary", "team"],
        "reason_codes": ["MISSING_CALENDAR_CHOICE"],
    }

    assert (
        combine_information_gap_assessment(
            assessment=assessment,
            relation_ambiguities=[],
        )
        == assessment
    )


def test_undetermined_duplicate_review__returns_to_retrieval__without_user_confirmation() -> None:
    assessment: InformationGapAssessmentV1 = {
        "disposition": "COMPLETE",
        "ambiguities": [],
        "retrieval_needs": [],
        "evidence_refs": [],
    }

    result = require_resolution_for_undetermined_action(
        assessment=assessment,
        route_action_necessities=[
            {
                "route_id": "task-create",
                "status": "UNDETERMINED",
                "reason": "observed tasks were not represented",
                "evidence_refs": [],
                "candidate_refs": [],
            }
        ],
    )

    assert result["disposition"] == "NEEDS_MORE_DATA"
    assert result["retrieval_needs"] == [
        {
            "required_information": (
                "current observations needed to determine requested action applicability"
            ),
            "reason_codes": ["ACTION_NECESSITY_UNDETERMINED"],
        }
    ]
    assert "question" not in result
