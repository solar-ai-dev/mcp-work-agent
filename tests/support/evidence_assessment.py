"""Explicit inference fixture for an expected durable evidence selection."""

from collections.abc import Mapping
from typing import Any


def evidence_assessment_output(selection: Mapping[str, Any]) -> dict[str, Any]:
    drafts = selection["evidence_drafts"]
    assert len({item["segment_id"] for item in drafts}) == len(drafts)
    assert {item["segment_id"] for item in drafts} == set(selection["selected_segment_ids"])
    assert not set(selection["selected_segment_ids"]) & set(selection["excluded_segment_ids"])
    return {
        "schema_version": 3,
        "segment_assessments": {
            **{
                item["segment_id"]: {
                    "role": item["role"],
                    "relevance_reason": item["relevance_reason"],
                }
                for item in drafts
            },
            **{
                segment_id: {"role": "EXCLUDED", "relevance_reason": "요청과 무관한 자료"}
                for segment_id in selection["excluded_segment_ids"]
            },
        },
    }
