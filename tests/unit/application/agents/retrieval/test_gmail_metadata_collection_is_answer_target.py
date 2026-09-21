from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.retrieval import (
    gmail_metadata_collection_is_answer_target as metadata_collection,
)


def test_gmail_metadata_collection_is_answer_target__with_exhaustive_subject_read__returns_true(
) -> None:
    intent = cast(
        RequestIntentV3,
        {
            "constraints": [
                {
                    "kind": "SCOPE",
                    "field": "coverage_requirement",
                    "value": "EXHAUSTIVE",
                }
            ],
            "analysis_requirement": "NONE",
            "resource_responsibilities": {
                "source_reads": [
                    {
                        "resource_type": "GMAIL_THREAD",
                        "required_information": ["thread_identity", "subject"],
                    }
                ],
                "outputs": [],
            },
        },
    )

    assert metadata_collection.gmail_metadata_collection_is_answer_target(intent) is True
