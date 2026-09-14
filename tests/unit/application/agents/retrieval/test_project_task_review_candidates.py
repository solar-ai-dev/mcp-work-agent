from typing import cast

import pytest

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.project_task_review_candidates import (
    project_task_review_candidates,
)


def _result(resources: list[dict[str, object]]) -> AcquisitionResultV1:
    return cast(
        AcquisitionResultV1,
        {
            "source_summaries": [
                {
                    "route_id": "task-read",
                    "resources": resources,
                }
            ]
        },
    )


def _task(*, title: str, notes: str | None = None) -> dict[str, object]:
    return {
        "resource_handle": "task:task-1",
        "resource_type": "task",
        "resource_id": "task-1",
        "parent_id": "task-list-1",
        "version": "v1",
        "payload": {
            "title": title,
            "status": "needsAction",
            "due": "2026-08-10T00:00:00.000Z",
            "notes": notes,
        },
    }


def test_task_candidates__preserve_bounded_observation__and_dedupe_identity() -> None:
    candidates = project_task_review_candidates(_result([_task(title="Ion"), _task(title="Ion")]))

    assert candidates == [
        {
            "candidate_ref": "task:task-1",
            "route_id": "task-read",
            "resource_id": "task-1",
            "task_list_id": "task-list-1",
            "title": "Ion",
            "status": "needsAction",
            "due": "2026-08-10T00:00:00.000Z",
            "notes": None,
            "notes_truncated": False,
            "source_version_ref": "v1",
        }
    ]


def test_task_candidates__reject_conflicting_observations__for_same_identity() -> None:
    with pytest.raises(ValueError, match="conflicting observations"):
        project_task_review_candidates(_result([_task(title="Ion"), _task(title="Different")]))


def test_task_candidates__with_long_notes__carry_bounded_semantic_context() -> None:
    notes = "different work detail " * 100

    candidate = project_task_review_candidates(_result([_task(title="Ion", notes=notes)]))[0]

    assert candidate["notes"] == notes.strip()[:1200]
    assert candidate["notes_truncated"] is True
