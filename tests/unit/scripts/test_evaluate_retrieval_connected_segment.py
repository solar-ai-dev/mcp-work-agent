from pathlib import Path
from typing import cast

import pytest
from scripts.evaluate_retrieval_connected_segment import (
    _replay_clock_ms,
    _select_replay_inputs,
    _state_diagnostics,
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
