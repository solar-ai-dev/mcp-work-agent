from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from scripts.evaluate_retrieval_connected_segment import (
    _compact_fact_evidence,
    _evaluate_work_analysis,
    _RecordingInferencePort,
    _replay_clock_ms,
    _select_replay_inputs,
    _source_route_diagnostics,
    _state_diagnostics,
    _summarize_llm_output,
    _work_analysis_input_fingerprint,
    evaluate,
)

from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)


def test_current_upstream_override_replaces_both_saved_inputs() -> None:
    saved: dict[str, object] = {
        "request_intent": {"saved": "intent"},
        "tool_route_plan": {"saved": "route"},
    }
    current_intent = cast(RequestIntentV3, {"current": "intent"})
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


def test_derived_request_override_must_cover_every_case(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="request text overrides must cover exactly"):
        evaluate(
            checkpoint_root=tmp_path,
            result_path=tmp_path / "result.json",
            case_ids=("CASE-CORE-014",),
            model_id="qwen3.5:9b",
            sampling_temperature=0.0,
            sampling_seed=1729,
            request_text_overrides={},
        )


def test_derived_request_override_cannot_be_empty(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nonempty strings"):
        evaluate(
            checkpoint_root=tmp_path,
            result_path=tmp_path / "result.json",
            case_ids=("CASE-CORE-014",),
            model_id="qwen3.5:9b",
            sampling_temperature=0.0,
            sampling_seed=1729,
            request_text_overrides={"CASE-CORE-014": " "},
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
    assert _source_route_diagnostics(plan, None)[1]["attempted"] is None


def test_work_analysis_harness_records_typed_failure_without_private_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Failure(Exception):
        code = type("Code", (), {"value": "PROVIDER_UNAVAILABLE"})()
        provider_dispatch_occurred = True

    def _fail(**_: object) -> None:
        raise _Failure("private prompt and source text")

    monkeypatch.setattr(
        "scripts.evaluate_retrieval_connected_segment.WorkAnalysisSubgraph", _fail
    )
    result = _evaluate_work_analysis(
        state=cast(GraphState, {}),
        llm_runtime=_RecordingInferencePort(object(), []),
        evidence_store=RunScopedEvidenceStore(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        replay_id="test",
        dispatch_count=lambda: 1,
    )

    assert result["outcome"] == "FAILED"
    assert result["error_code"] == "PROVIDER_UNAVAILABLE"
    assert result["provider_dispatch_occurred"] is True
    assert "private prompt" not in str(result)


def test_inference_attempt_records_failure_size_without_prompt_content() -> None:
    class _FailingDelegate:
        def infer(self, *_: object) -> None:
            raise RuntimeError("private source text")

    recorder = _RecordingInferencePort(_FailingDelegate(), [])

    with pytest.raises(RuntimeError):
        recorder.infer(
            "LOCAL_GPU",
            SimpleNamespace(prompt_id="work_analysis.extract_work_facts"),
            {"user_request": "private request"},
            {},
        )

    assert recorder.calls == []
    assert recorder.attempts[0]["outcome"] == "FAILED"
    assert cast(int, recorder.attempts[0]["input_chars"]) > 0
    assert "private" not in str(recorder.attempts)


def test_work_analysis_input_fingerprint_includes_evidence_without_revealing_it() -> None:
    class _EvidenceStore:
        evidence = [{"text": "private evidence"}]

        def resolve(self, *, run_id: str, evidence_refs: list[str]) -> list[dict[str, str]]:
            assert run_id == "test"
            assert evidence_refs == ["e1"]
            return self.evidence

    store = _EvidenceStore()
    state = cast(GraphState, {"retrieval_result": {"evidence_refs": ["e1"]}})
    first = _work_analysis_input_fingerprint(
        state, evidence_store=cast(RunScopedEvidenceStore, store), replay_id="test"
    )
    assert len(first) == 64
    assert "private" not in first
    store.evidence = [{"text": "different private evidence"}]
    second = _work_analysis_input_fingerprint(
        state, evidence_store=cast(RunScopedEvidenceStore, store), replay_id="test"
    )
    assert first != second


def test_inference_detail_is_opt_in() -> None:
    class _Delegate:
        def infer(self, *_: object) -> SimpleNamespace:
            return SimpleNamespace(
                input_tokens=10,
                output_tokens=2,
                latency_ms=3,
                structured_output={"private": "source text"},
            )

    recorder = _RecordingInferencePort(_Delegate(), [])
    recorder.infer("LOCAL_GPU", SimpleNamespace(prompt_id="test"), {})
    assert "structured_output" not in recorder.calls[0]
    recorder.capture_structured_output = True
    recorder.infer("LOCAL_GPU", SimpleNamespace(prompt_id="test"), {})
    assert recorder.calls[1]["structured_output"] == {"private": "source text"}
    assert recorder.calls[1]["prompt_input"] == {}


def test_compact_fact_projection_retains_content_and_citation_not_wrapper() -> None:
    evidence = [
        {
            "evidence_id": "e1",
            "resource_handle": "gmail_thread:t1",
            "excerpt": "Subject: delay",
            "locator": {"is_metadata_only": True, "position": 8},
            "segment_id": "seg1",
            "reason_codes": ["SUPPORTS"],
        }
    ]

    assert _compact_fact_evidence(evidence) == [
        {
            "evidence_id": "e1",
            "resource_handle": "gmail_thread:t1",
            "excerpt": "Subject: delay",
            "is_metadata_only": True,
        }
    ]
