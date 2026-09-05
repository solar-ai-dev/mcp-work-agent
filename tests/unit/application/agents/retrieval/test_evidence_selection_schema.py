import pytest

from google_work_agent.application.agents.retrieval.contracts.evidence_selection_schema import (
    bind_evidence_selection_schema,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


@pytest.mark.parametrize("selected, draft_id, valid", [
    (["mail", "task"], "mail", True),
    (["mail"], "mail", False),
    (["task"], "task", False),
    (["mail", "task", "invented"], "mail", False),
    (["mail", "task"], "invented", False),
    (["mail", "task", "task"], "mail", False),
])
def test_current_evidence_schema__binds_ids_and__required_resource_coverage(
    selected: list[str], draft_id: str, valid: bool,
) -> None:
    schema = bind_evidence_selection_schema(
        candidate_resource_refs={"mail": "gmail_thread:1", "task": "task:2"},
        requested_resource_hints=["GMAIL_THREAD", "TASK"], max_evidence=12,
    )
    output = {
        "schema_version": 2, "selected_segment_ids": selected, "excluded_segment_ids": [],
        "evidence_drafts": [{"segment_id": item, "role": "CONTEXT",
                             "relevance_reason": "요청에 필요한 자료"}
                            for item in dict.fromkeys([draft_id, *selected])],
    }
    assert (not validate_output_schema(output, schema.json_schema)) is valid


def test_current_evidence_schema__does_not_require__absent_resource_evidence() -> None:
    schema = bind_evidence_selection_schema(
        candidate_resource_refs={}, requested_resource_hints=["TASK"], max_evidence=12,
    )
    assert validate_output_schema({
        "schema_version": 2, "selected_segment_ids": [], "excluded_segment_ids": [],
        "evidence_drafts": [],
    }, schema.json_schema) == []


def test_search_candidates_may_all_be_excluded_but_not_silently_ignored() -> None:
    schema = bind_evidence_selection_schema(
        candidate_resource_refs={"old": "gmail_thread:1", "unrelated": "gmail_thread:2"},
        requested_resource_hints=["GMAIL_THREAD"], max_evidence=12,
    )
    output = {"schema_version": 2, "selected_segment_ids": [], "evidence_drafts": [],
              "excluded_segment_ids": ["old", "unrelated"]}
    assert validate_output_schema(output, schema.json_schema) == []
    output["excluded_segment_ids"] = ["old"]
    assert validate_output_schema(output, schema.json_schema)
    output["excluded_segment_ids"] = ["old", "old", "unrelated"]
    assert validate_output_schema(output, schema.json_schema)


@pytest.mark.parametrize("draft_ids", [[], ["mail", "mail"], ["other"]])
def test_selected_segment_requires_exactly_one_matching_draft(draft_ids: list[str]) -> None:
    schema = bind_evidence_selection_schema(
        candidate_resource_refs={"mail": "gmail_thread:1", "other": "gmail_thread:2"},
        requested_resource_hints=["GMAIL_THREAD"], max_evidence=12,
    )
    output = {
        "schema_version": 2, "selected_segment_ids": ["mail"],
        "excluded_segment_ids": ["other"],
        "evidence_drafts": [{"segment_id": item, "role": "CONTEXT",
                             "relevance_reason": "관련 후보"} for item in draft_ids],
    }
    assert validate_output_schema(output, schema.json_schema)
    output["evidence_drafts"] = [
        {"segment_id": "mail", "role": "CONTEXT", "relevance_reason": "관련 후보"},
    ]
    assert validate_output_schema(output, schema.json_schema) == []
