from tests.support.context_retrieval import acquisition_result

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
)
from google_work_agent.application.agents.retrieval.project_detail_candidate_refs import (
    project_detail_candidate_refs,
)


def test_project_detail_candidate_refs__selection_empty__retains_acquired_candidate() -> None:
    assert project_detail_candidate_refs(
        evidence_drafts=[], acquisition_result=acquisition_result()
    ) == ["gmail_thread:thread-kim"]


def test_project_detail_candidate_refs__selected_first__deduplicates_acquisition() -> None:
    selected: list[EvidenceDraftV1] = [
        {
            "schema_version": 1,
            "evidence_id": "evidence-selected",
            "resource_handle": "gmail_thread:selected",
            "segment_id": "segment-selected",
            "kind": "excerpt",
            "excerpt": "selected",
            "locator": {},
            "reason_codes": ["SUPPORTS"],
        }
    ]
    acquisition = acquisition_result()
    acquisition["resource_handles"] = [
        "gmail_thread:other",
        "gmail_thread:selected",
    ]

    assert project_detail_candidate_refs(
        evidence_drafts=selected, acquisition_result=acquisition
    ) == ["gmail_thread:selected", "gmail_thread:other"]
