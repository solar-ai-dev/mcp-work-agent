from __future__ import annotations

from json import dumps

from google_work_agent.application.use_cases.run.project_action_target_display import (
    project_action_target_display,
)
from google_work_agent.domain.evidence.model import Evidence, EvidenceOriginType
from google_work_agent.domain.resource_ref.model import ResourceRef


def test_calendar_target_display__projects_schedule__without_provider_identity() -> None:
    resource_ref = _resource_ref(resource_type="calendar_event", title=None)
    evidence = _evidence(
        resource_ref.id,
        "\n".join(
            (
                "calendar_id: opaque-calendar-id",
                "event_id: opaque-event-id",
                "title: 주간 프로젝트 회의",
                "start: 2026-09-14T15:00:00+09:00",
                "end: 2026-09-14T15:30:00+09:00",
                "timezone: Asia/Seoul",
                "description: 표시 범위 밖 본문",
            )
        ),
    )

    result = project_action_target_display(resource_ref=resource_ref, evidence=(evidence,))

    assert result == {
        "title": "주간 프로젝트 회의",
        "start": "2026-09-14T15:00:00+09:00",
        "end": "2026-09-14T15:30:00+09:00",
        "timezone": "Asia/Seoul",
    }
    assert "opaque" not in str(result)
    assert "description" not in result


def test_task_and_issue_target_display__projects_business_facts__without_opaque_identity() -> None:
    task_ref = _resource_ref(
        resource_type="task",
        title="회의 후속자료",
        metadata={"due": "2026-09-15", "status": "needsAction", "task_id": "opaque"},
    )
    issue_ref = _resource_ref(
        resource_type="github_issue",
        title="배포 체크리스트",
        metadata={"state": "open", "node_id": "opaque"},
    )

    assert project_action_target_display(resource_ref=task_ref, evidence=()) == {
        "title": "회의 후속자료",
        "due": "2026-09-15",
        "status": "needsAction",
    }
    assert project_action_target_display(resource_ref=issue_ref, evidence=()) == {
        "title": "배포 체크리스트",
        "state": "open",
    }


def _resource_ref(
    *,
    resource_type: str,
    title: str | None,
    metadata: dict[str, object] | None = None,
) -> ResourceRef:
    return ResourceRef(
        id=f"ref-{resource_type}",
        run_id="run-1",
        connector_id="github" if resource_type == "github_issue" else "google_workspace",
        resource_type=resource_type,
        resource_id=f"opaque-{resource_type}-id",
        parent_resource_id="opaque-parent-id",
        canonical_url=None,
        title=title,
        event_time_ms=None,
        version_token="v1",
        metadata_json=dumps(metadata or {}),
        captured_at_ms=1,
    )


def _evidence(resource_ref_id: str, excerpt: str) -> Evidence:
    return Evidence(
        id="evidence-1",
        run_id="run-1",
        origin_type=EvidenceOriginType.GOOGLE_RESOURCE,
        resource_ref_id=resource_ref_id,
        message_id=None,
        kind="excerpt",
        excerpt=excerpt,
        locator_json=None,
        created_at_ms=1,
    )
