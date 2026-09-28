from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tests.evaluation import test_production_goal_output_candidate as connected

from google_work_agent.adapters.langgraph.confirmation_llm_runtime import (
    ConfirmationAwareLLMRuntime,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes import (
    identify_goal_node as node,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget


@pytest.mark.parametrize(
    "mode",
    ["fresh", "goal", "intent", "confirmation", "reconsideration", "pending", "other_pending"],
)
def test_physical_node_codec_gate_excludes_existing_state_and_nested_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    projection: dict[str, Any] = {"request": SimpleNamespace(run_id="run-1")}
    state: dict[str, Any] = {"retry_budget": build_default_run_budget()}
    if mode in {"goal", "intent"}:
        state["goal_candidate" if mode == "goal" else "request_intent"] = {}
    if mode in {"confirmation", "reconsideration"}:
        projection[
            "confirmation_response" if mode == "confirmation" else "request_reconsideration"
        ] = {}
    runtime = ConfirmationAwareLLMRuntime(SimpleNamespace())
    if mode in {"pending", "other_pending"}:
        runtime.register(
            run_id="run-1" if mode == "pending" else "other",
            origin_target="request.detect_ambiguity",
            response={"free_text": "yes"},
        )
    observed = []

    def owner(**kwargs: Any) -> Any:
        observed.append(kwargs["allow_whitespace_work_selector"])
        return {}, kwargs["retry_budget"]

    monkeypatch.setattr(node, "project_identify_goal_input", lambda _: projection)
    monkeypatch.setattr(node, "ensure_llm_call_budget", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(node, "identify_goal_with_budget", owner)
    node.identify_goal_node(
        state,
        llm_runtime=runtime,
        source_dependency_candidates=(),
        output_responsibility_candidates=(),
        **{
            field: None
            for field in (
                "prompt_ref",
                "effect_prohibition_prompt_ref",
                "source_dependency_prompt_ref",
                "output_responsibility_prompt_ref",
                "source_status_prompt_ref",
                "requested_work_prompt_ref",
                "work_relation_prompt_ref",
            )
        },
    )
    assert observed == [mode in {"fresh", "other_pending"}]
    assert runtime.has_pending_confirmation(run_id="run-1") == (mode == "pending")
    runtime.clear(run_id="run-1")
    assert not runtime.has_pending_confirmation(run_id="run-1")


def test_actual_product_compiled_ru_uses_codec_without_evaluation_validator_patch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_runtime = connected._runtime
    observed = []

    def runtime(path: Path, patcher: pytest.MonkeyPatch, replies: list[Any]) -> Any:
        replies[0] = {
            "schema_version": 1,
            "work_units": [{"request_spans": ["Read  the selected task."]}],
        }
        result = original_runtime(path, patcher, replies)
        observed.append(result)
        return result

    monkeypatch.setattr(connected, "_runtime", runtime)
    connected.test_actual_product_identify_goal_node_consumes_cached_output_in_compiled_graph(
        tmp_path, monkeypatch
    )
    _, observation, calls, _ = observed[0]
    assert len(calls) == 5
    assert observation.calls[0]["input"] == {"user_request": "Read the selected task."}
    assert observation.calls[0]["prompt_id"] == "request_understanding.identify_requested_work"
