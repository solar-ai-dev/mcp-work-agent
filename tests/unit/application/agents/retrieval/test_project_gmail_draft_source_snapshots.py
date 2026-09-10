from typing import cast

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.project_gmail_draft_source_snapshots import (
    project_gmail_draft_source_snapshots,
)


def test_snapshot_projection__preserves_empty_and_null__without_filling_omissions() -> None:
    result = cast(
        AcquisitionResultV1,
        {
            "source_summaries": [
                {
                    "route_id": "draft-read",
                    "resources": [
                        {
                            "resource_handle": "gmail_draft:draft-1",
                            "resource_type": "gmail_draft",
                            "payload": {
                                "to": [],
                                "cc": [],
                                "bcc": [],
                                "subject": "",
                                "body": "",
                                "thread_id": None,
                                "in_reply_to": None,
                                "references": "",
                            },
                        }
                    ],
                }
            ]
        },
    )

    observation = project_gmail_draft_source_snapshots(result)[0]
    snapshot = observation["snapshot"]

    assert observation["resource_handle"] == "gmail_draft:draft-1"
    assert observation["source_version_ref"].startswith("sha256:")
    assert snapshot["to"] == []
    assert snapshot["thread_id"] is None
    assert snapshot["references"] == ""
    assert "attachments" not in snapshot
