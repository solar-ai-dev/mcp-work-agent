from __future__ import annotations

import pytest

from google_work_agent.application.agents.planning.project_retrieval_collections import (
    project_retrieval_collections,
)


def test_project_retrieval_collections__with_resource_items__keeps_bounded_metadata() -> None:
    result = project_retrieval_collections(
        {
            "collection_results": [
                {
                    "route_id": "route-1",
                    "resource_type": "GMAIL_THREAD",
                    "continuation_status": "HAS_MORE",
                    "items": [
                        {
                            "resource_ref": "gmail-thread:1",
                            "resource_type": "GMAIL_THREAD",
                            "title": "First",
                        },
                        {
                            "resource_ref": "gmail-thread:2",
                            "resource_type": "GMAIL_THREAD",
                            "title": None,
                        },
                    ],
                }
            ]
        }
    )

    assert result == [
        {
            "resource_type": "GMAIL_THREAD",
            "continuation_status": "HAS_MORE",
            "items": [
                {"item_number": 1, "title": "First"},
                {"item_number": 2, "title": None},
            ],
        }
    ]


def test_project_retrieval_collections__with_invalid_item_shape__rejects_projection() -> None:
    with pytest.raises(ValueError, match="collection item"):
        project_retrieval_collections(
            {
                "collection_results": [
                    {
                        "resource_type": "GMAIL_THREAD",
                        "continuation_status": "EXHAUSTED",
                        "items": ["not-an-object"],
                    }
                ]
            }
        )
