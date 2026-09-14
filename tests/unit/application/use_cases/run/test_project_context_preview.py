from __future__ import annotations

from json import dumps
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.project_context_preview import (
    ProjectContextPreviewHandler,
    ProjectContextPreviewQueryV1,
)
from google_work_agent.ports.system.contracts.retrieval_head import RetrievalHeadV1


class _Checkpoint:
    def load_retrieval_head(self, run_id: str) -> RetrievalHeadV1 | None:
        if run_id != "run-1":
            return None
        return RetrievalHeadV1(1, run_id, "thread-1", 7, "retrieval-current", "cp-1", 1)


@pytest.mark.parametrize(
    "connector,resource_type,category",
    [
        ("google_workspace", "gmail_draft", "mail"),
        ("google_workspace", "task", "task"),
        ("google_workspace", "calendar_event", "calendar"),
        ("github", "github_issue", "github"),
    ],
)
def test_context_preview__contains_only_current__selected_retrieval_evidence(
    tmp_path: Path,
    connector: str,
    resource_type: str,
    category: str,
) -> None:
    database_path = tmp_path / "context-preview.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('account-1', 'u@example.com', 1)"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Inbox', 1, 1)"
        )
        connection.execute(
            """INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'WAITING_APPROVAL',
                      'thread-1', 'AUTO', '{}', 4, 1)"""
        )
        connection.execute(
            """INSERT INTO plans (
                id, run_id, revision_no, status, summary_text, created_at_ms,
                review_status, review_version, review_disposition
            ) VALUES ('plan-1', 'run-1', 1, 'WAITING_APPROVAL', 'Plan', 2,
                      'PASSED', 1, 'PASS')"""
        )
        connection.execute(
            """INSERT INTO actions (
                id, plan_id, connector_id, position, tool_name, effect_type,
                approval_requirement, verification_policy, recovery_policy, status,
                arguments_json, arguments_hash, expected_json, created_at_ms, updated_at_ms
            ) VALUES ('action-1', 'plan-1', 'google_workspace', 1, 'tasks_create_task',
                      'CREATE', 'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH', 'PROPOSED',
                      '{}', ?, '{}', 3, 3)""",
            ("a" * 64,),
        )
        for ref_id, resource_id, title in (
            ("ref-current", "provider-id-1", "Shared title"),
            ("ref-same-title", "provider-id-2", "Shared title"),
            ("ref-fallback", "provider-secret-id", None),
            ("ref-stale", "provider-id-stale", "Stale title"),
        ):
            connection.execute(
                """INSERT INTO resource_refs (
                    id, run_id, connector_id, resource_type, resource_id,
                    title, metadata_json, captured_at_ms
                ) VALUES (?, 'run-1', ?, ?, ?, ?, '{}', 3)""",
                (ref_id, connector, resource_type, resource_id, title),
            )
        first_excerpt, second_excerpt, visible_parts = _context_excerpts(category)
        for evidence_id, ref_id, artifact, segment, role, excerpt in (
            (
                "e-01",
                "ref-current",
                "retrieval-current",
                "segment-1",
                "SUPPORTS",
                first_excerpt,
            ),
            (
                "e-02",
                "ref-current",
                "retrieval-current",
                "segment-2",
                "CONTEXT",
                second_excerpt,
            ),
            (
                "e-03",
                "ref-same-title",
                "retrieval-current",
                "segment-3",
                "SUPPORTS",
                first_excerpt,
            ),
            (
                "e-04",
                "ref-fallback",
                "retrieval-current",
                "segment-4",
                "SUPPORTS",
                first_excerpt,
            ),
            (
                "e-05",
                "ref-stale",
                "retrieval-old",
                "segment-old",
                "CONTEXT",
                "stale content",
            ),
        ):
            connection.execute(
                """INSERT INTO evidence (
                    id, run_id, origin_type, resource_ref_id, kind, excerpt,
                    locator_json, created_at_ms
                ) VALUES (?, 'run-1', 'CONNECTOR_RESOURCE', ?, 'excerpt', ?, ?, 3)""",
                (
                    evidence_id,
                    ref_id,
                    excerpt,
                    dumps(
                        {
                            "retrieval_artifact_id": artifact,
                            "segment_id": segment,
                            "role": role,
                        }
                    ),
                ),
            )
    handler = ProjectContextPreviewHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        checkpoint=_Checkpoint(),  # type: ignore[arg-type]
    )

    result = handler(ProjectContextPreviewQueryV1("run-1"))

    assert result.retrieval_revision == 7
    assert [(item.resource_identity, item.segment_ids) for item in result.items] == [
        ("ref-current", ("segment-1", "segment-2")),
        ("ref-same-title", ("segment-3",)),
        ("ref-fallback", ("segment-4",)),
    ]
    assert [item.title for item in result.items] == ["Shared title", "Shared title", "Shared title"]
    assert all(part in result.items[0].content for part in visible_parts)
    assert result.items[0].preview == result.items[0].content[:240]
    if category == "task":
        assert "마감: 2026년 9월 10일" in result.items[0].content
    if category == "calendar":
        assert "시작: 2026년 9월 10일 오전 10:00" in result.items[0].content
    assert not any(
        hidden in result.items[0].content
        for hidden in (
            "draft_id",
            "thread_id",
            "message_id",
            "resource_id",
            "calendar_id",
            "event_id",
            "in_reply_to",
            "references",
            "null",
            "[]",
        )
    )
    assert all(item.category == category for item in result.items)
    counts = {
        "mail": result.gmail_count,
        "task": result.tasks_count,
        "calendar": result.calendar_count,
        "github": result.github_count,
    }
    assert counts[category] == 3
    assert sum(counts.values()) == 3
    assert result.adjustment_allowed is True
    assert result.allowed_adjustments == ("EXCLUDE_EVIDENCE", "RETRIEVE_MORE")


def _context_excerpts(category: str) -> tuple[str, str, tuple[str, str]]:
    return {
        "mail": (
            "draft_id: hidden\nthread_id: hidden\nsubject: Shared title\nbody:\n첫 메일 본문",
            "in_reply_to: null\nreferences: []\nbody:\n둘째 메일 본문",
            ("첫 메일 본문", "둘째 메일 본문"),
        ),
        "task": (
            "task_list_id: hidden\ntitle: Shared title\ndue: 2026-09-10\nnotes:\n첫 태스크 내용",
            "task_list_id: hidden\nnotes:\n둘째 태스크 내용",
            ("첫 태스크 내용", "둘째 태스크 내용"),
        ),
        "calendar": (
            "calendar_id: hidden\nevent_id: hidden\ntitle: Shared title\n"
            "start: 2026-09-10T10:00:00+09:00\nend: 2026-09-10T11:00:00+09:00\n"
            "description: 첫 일정 내용\nattendees: []",
            "calendar_id: hidden\nevent_id: hidden\ndescription: 둘째 일정 내용",
            ("첫 일정 내용", "둘째 일정 내용"),
        ),
        "github": (
            "repository: solar-ai-dev/google-work-agent\nissue_number: 208\n"
            "title: Shared title\nstate: OPEN\nurl: https://example.invalid\n"
            "description:\n첫 GitHub 내용",
            "description:\n둘째 GitHub 내용",
            ("첫 GitHub 내용", "둘째 GitHub 내용"),
        ),
    }[category]
