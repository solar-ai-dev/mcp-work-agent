"""Empty evidence is not proof of an empty READ; fake composer, no model/Provider."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

import pytest

from google_work_agent.application.agents.planning.compose_answer import compose_answer
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerOutlineV1,
)
from google_work_agent.application.agents.planning.outline_answer import outline_answer
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    RetrievalSourceStatusV1,
)

_UNCERTAIN = "현재 자료로 판단할 수 없습니다."
_EMPTY_TASK = "Google Tasks에서 현재 표시할 할 일을 찾지 못했습니다."


def _task_intent() -> dict[str, object]:
    return {
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "NONE",
        "constraints": [],
        "resource_responsibilities": {
            "source_reads": [
                {
                    "resource_type": "TASK",
                    "required_information": ["title"],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": ["work-1"],
                }
            ],
            "outputs": [],
        },
    }


def _status(**changes: object) -> RetrievalSourceStatusV1:
    return cast(
        RetrievalSourceStatusV1,
        {
            "route_id": "tasks-read",
            "resource_type": "task",
            "status": "COMPLETE",
            "evidence_refs": [],
            "work_unit_ids": ["work-1"],
            "failure_kind": None,
            "checked_read_count": 1,
            "observed_resource_count": 0,
            "known_scope_count": 1,
            "scope_complete": True,
            "continuation_status": "EXHAUSTED",
            **changes,
        },
    )


def _retrieval(
    statuses: list[RetrievalSourceStatusV1],
    *,
    coverage: str = "PARTIAL",
) -> dict[str, object]:
    return {
        "coverage": coverage,
        "source_statuses": statuses,
        "evidence_by_work_unit": [{"work_unit_id": "work-1", "evidence_refs": []}],
        "missing_information": [],
        "unresolved_event_dates": [],
    }


def _run(
    intent: dict[str, object],
    retrieval: dict[str, object] | None,
) -> tuple[dict[str, Any], dict[str, Any], list[tuple[str, dict[str, object]]]]:
    calls: list[tuple[str, dict[str, object]]] = []
    before = deepcopy((intent, retrieval))

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append((prompt_id, deepcopy(dict(prompt_input))))
        return {"schema_version": 2, "answer": _UNCERTAIN, "evidence_refs": []}

    kwargs: dict[str, Any] = {
        "user_request": "현재 할 일을 알려줘.",
        "request_intent": intent,
        "evidence": [],
        "retrieval_result": retrieval,
        "work_analysis": None,
        "invoke": invoke,
    }
    outline = outline_answer(**kwargs)
    answer = compose_answer(**kwargs, answer_outline=cast(AnswerOutlineV1, outline))
    assert (intent, retrieval) == before
    return cast(dict[str, Any], outline), cast(dict[str, Any], answer), calls


@pytest.mark.parametrize(
    "observation",
    [
        "absent",
        "failed",
        "not_attempted",
        "partial",
        "observed_nonempty",
        "no_status",
        "task_list_only",
        "missing_count",
        "continuation_unknown",
    ],
)
def test_empty_task_evidence_without_complete_zero_proof_retains_composer(
    observation: str,
) -> None:
    retrieval: dict[str, object] | None
    if observation == "absent":
        retrieval = None
    elif observation == "no_status":
        retrieval = _retrieval([], coverage="SUFFICIENT")
    elif observation == "failed":
        retrieval = _retrieval(
            [
                _status(
                    status="FAILED",
                    failure_kind="TIMEOUT",
                    scope_complete=False,
                    continuation_status="UNKNOWN",
                )
            ]
        )
    elif observation == "not_attempted":
        retrieval = _retrieval(
            [
                _status(
                    status="NOT_ATTEMPTED",
                    checked_read_count=0,
                    scope_complete=False,
                    continuation_status="UNKNOWN",
                )
            ]
        )
    elif observation == "partial":
        retrieval = _retrieval(
            [
                _status(
                    status="PARTIAL",
                    known_scope_count=2,
                    scope_complete=False,
                    continuation_status="HAS_MORE",
                )
            ]
        )
    elif observation == "task_list_only":
        retrieval = _retrieval([_status(resource_type="task_list")], coverage="SUFFICIENT")
    elif observation == "missing_count":
        status = _status()
        del status["observed_resource_count"]
        retrieval = _retrieval([status], coverage="SUFFICIENT")
    elif observation == "continuation_unknown":
        retrieval = _retrieval([_status(continuation_status="UNKNOWN")], coverage="SUFFICIENT")
    else:
        # READ found resources, but none of their Evidence was selected.
        retrieval = _retrieval([_status(observed_resource_count=2)], coverage="SUFFICIENT")

    outline, answer, calls = _run(_task_intent(), retrieval)

    assert [prompt_id for prompt_id, _ in calls] == ["planning.compose_answer"]
    assert _UNCERTAIN in answer["answer"]
    assert _EMPTY_TASK not in answer["answer"]
    assert outline["sections"] != ["검색 결과 없음"]
    assert answer["evidence_refs"] == []
    prompt_input = calls[0][1]
    if retrieval is None:
        assert "source_statuses" not in prompt_input
    else:
        assert prompt_input["source_statuses"] == retrieval["source_statuses"]
        assert prompt_input["coverage"] == retrieval["coverage"]


@pytest.mark.parametrize("status", ["FAILED", "NOT_ATTEMPTED"])
def test_generic_read_failed_or_unattempted_is_not_a_checked_empty_scope(status: str) -> None:
    # An attempt counter does not override the typed failure/unattempted outcome.
    retrieval = _retrieval(
        [
            _status(
                status=status,
                resource_type="gmail_thread",
                failure_kind="TIMEOUT" if status == "FAILED" else None,
                scope_complete=False,
                continuation_status="UNKNOWN",
            )
        ]
    )
    _, answer, calls = _run({"requested_effect_hints": ["READ"]}, retrieval)

    assert [prompt_id for prompt_id, _ in calls] == ["planning.compose_answer"]
    assert _UNCERTAIN in answer["answer"]
    assert "조회 범위 1개를 확인했고" not in answer["answer"]
    assert "관련 항목을 찾지 못했습니다" not in answer["answer"]
    assert "접근 가능한 전체 범위를 확인했지만" not in answer["answer"]
    assert calls[0][1]["source_statuses"] == retrieval["source_statuses"]
    if status == "FAILED":
        assert "자료를 읽지 못했습니다" in answer["answer"]


def test_complete_zero_task_scope_keeps_existing_zero_call_answer() -> None:
    retrieval = _retrieval([_status()], coverage="SUFFICIENT")

    outline, answer, calls = _run(_task_intent(), retrieval)

    assert calls == []
    assert outline["sections"] == ["검색 결과 없음"]
    assert _EMPTY_TASK in answer["answer"]
    assert answer["evidence_refs"] == []
    assert _UNCERTAIN not in answer["answer"]


@pytest.mark.parametrize("missing_field", ["checked_read_count", "observed_resource_count"])
def test_legacy_missing_scope_counter_is_not_zero_result_evidence(missing_field: str) -> None:
    status = dict(_status())
    del status[missing_field]
    retrieval = _retrieval([cast(RetrievalSourceStatusV1, status)], coverage="SUFFICIENT")

    _, answer, calls = _run({"requested_effect_hints": ["READ"]}, retrieval)

    assert len(calls) == 1
    assert "관련 항목을 찾지 못했습니다" not in answer["answer"]
    assert answer["answer"] == _UNCERTAIN


def test_successful_empty_scope_plus_failed_other_route_counts_only_successful_scope() -> None:
    retrieval = _retrieval(
        [
            _status(),
            _status(
                route_id="mail-read",
                resource_type="gmail_thread",
                status="FAILED",
                failure_kind="TIMEOUT",
                checked_read_count=4,
                known_scope_count=4,
                scope_complete=False,
                continuation_status="UNKNOWN",
            ),
        ]
    )

    _, answer, calls = _run({"requested_effect_hints": ["READ"]}, retrieval)

    assert [prompt_id for prompt_id, _ in calls] == ["planning.compose_answer"]
    assert "조회 범위 1개를 확인했고" in answer["answer"]
    assert "조회 범위 5개" not in answer["answer"]
    assert "전체 검색은 완료되지 않았습니다" in answer["answer"]
    assert "자료를 읽지 못했습니다" in answer["answer"]
    assert "접근 가능한 전체 범위를 확인했지만" not in answer["answer"]
    assert _UNCERTAIN in answer["answer"]
    assert calls[0][1]["source_statuses"] == retrieval["source_statuses"]
