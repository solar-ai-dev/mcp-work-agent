from pathlib import Path
from typing import cast

import pytest
from scripts.evaluate_retrieval_connected_segment import (
    _replay_clock_ms,
    _select_replay_inputs,
    _source_route_diagnostics,
    _state_diagnostics,
    _summarize_llm_output,
    evaluate,
)

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)


def test_current_upstream_override_replaces_both_saved_inputs() -> None:
    saved: dict[str, object] = {
        "request_intent": {"saved": "intent"},
        "tool_route_plan": {"saved": "route"},
    }
    current_intent = cast(RequestIntentV2, {"current": "intent"})
    current_route = cast(ToolRoutePlanV2, {"current": "route"})

    assert _select_replay_inputs(saved, None) == (
        saved["request_intent"],
        saved["tool_route_plan"],
    )
    assert _select_replay_inputs(saved, (current_intent, current_route)) == (
        current_intent,
        current_route,
    )


def test_state_diagnostics_excludes_evidence_text() -> None:
    state: dict[str, object] = {
        "sufficiency": {
            "status": "NEEDS_MORE_DATA",
            "issues": [{"slot": "calendar_time", "description": "private text"}],
        },
        "evidence_selection": {"selected_segment_ids": ["one"]},
        "read_result_handles": ["handle"],
        "finalize_intent": {"intent": "BLOCKED", "reason_code": "CONTEXT_BLOCKED"},
    }

    summary = _state_diagnostics(state)

    assert summary["sufficiency_status"] == "NEEDS_MORE_DATA"
    assert summary["sufficiency_issue_slots"] == ["calendar_time"]
    assert summary["selected_segment_count"] == 1
    assert summary["finalize_reason_code"] == "CONTEXT_BLOCKED"
    assert "private text" not in str(summary)


def test_replay_clock_keeps_original_run_time() -> None:
    original = 1_786_060_800_000

    assert _replay_clock_ms(original, 2_500) == original + 2_500
    assert _replay_clock_ms(original, -100) == original


def test_current_upstream_override_must_cover_every_case(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cover exactly"):
        evaluate(
            checkpoint_root=tmp_path,
            result_path=tmp_path / "result.json",
            case_ids=("CASE-CORE-014",),
            model_id="qwen3.5:9b",
            sampling_temperature=0.0,
            sampling_seed=1729,
            input_overrides={},
        )


def test_llm_summary_keeps_issue_binding_without_private_description() -> None:
    candidate = {
        "status": "BLOCKED",
        "issues": [
            {
                "slot": "task_status",
                "issue_type": "MISSING",
                "resolution_source": "GOOGLE",
                "description": "private source text",
            }
        ],
    }

    summary = _summarize_llm_output("retrieval.assess_sufficiency", candidate)

    assert summary["status"] == "BLOCKED"
    assert summary["issue_bindings"] == [
        {
            "slot": "task_status",
            "issue_type": "MISSING",
            "resolution_source": "GOOGLE",
        }
    ]
    assert "private source text" not in str(summary)


def test_llm_summary_records_query_operations_and_selection_count() -> None:
    assert _summarize_llm_output(
        "retrieval.plan_query",
        {"route_queries": [{"operation": "SEARCH"}, {"operation": "FREEBUSY"}]},
    )["operation_kinds"] == ["SEARCH", "FREEBUSY"]
    assert _summarize_llm_output(
        "retrieval.select_evidence", {"segment_assessments": [{"private": "text"}]}
    )["segment_assessments_count"] == 1


def test_source_route_diagnostics_separate_guard_policy_and_access_routes() -> None:
    plan = {
        "input_plan": {
            "input_routes": [
                {
                    "route_id": "calendar",
                    "resource_type": "CALENDAR",
                    "required": True,
                    "reason_codes": ["REQUESTED_INPUT"],
                },
                {
                    "route_id": "task_list",
                    "resource_type": "TASK_LIST",
                    "required": True,
                    "reason_codes": ["RETRIEVAL_TASK_LIST_DISCOVERY"],
                },
                {
                    "route_id": "event",
                    "resource_type": "CALENDAR_EVENT",
                    "required": True,
                    "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
                },
            ]
        }
    }
    acquisition = {
        "source_summaries": [
            {
                "route_id": "task_list",
                "status": "COMPLETE",
                "resource_count": 1,
            }
        ]
    }

    summary = _source_route_diagnostics(plan, acquisition)

    assert summary[0]["guard_required"] is True
    assert summary[0]["policy_required"] is False
    assert summary[0]["attempted"] is False
    assert summary[1]["guard_required"] is False
    assert summary[1]["attempted"] is True
    assert summary[2]["guard_required"] is True
    assert summary[2]["policy_required"] is True
    assert summary[2]["attempted"] is False
