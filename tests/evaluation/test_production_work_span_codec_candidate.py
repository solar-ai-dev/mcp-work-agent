"""Codec structure/connected fake-wire gates; not semantic model scores."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import production_work_span_codec_candidate as codec
from tests.evaluation import test_production_goal_output_candidate as goal_tests

from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)


def _raw(*spans: str) -> dict[str, Any]:
    return {"schema_version": 1, "work_units": [{"request_spans": [span]} for span in spans]}


def test_exact_unchanged_and_preferred_over_whitespace_equivalent_other_occurrence() -> None:
    request = "A B 와 AB 확인"
    raw = _raw("AB 확인")
    assert codec.materialize_work_spans(raw, user_request=request) == (
        codec.work_owner.validate_requested_work_candidate(raw, user_request=request)
    )
    assert codec.bind_request_span("AB", user_request=request)["start_offset"] == 6
    assert codec.bind_request_span("AB", user_request=request)["binding_mode"] == "EXACT"


@pytest.mark.parametrize(
    ("original_text", "selector", "expected"),
    [
        ("8월 12일까지 검토해.", "8 월 12 일까지 검토해.", "8월 12일까지 검토해."),
        (
            "name@example.test에 알려줘.",
            "name@example.test 에 알려줘.",
            "name@example.test에 알려줘.",
        ),
        ("  a\t b\n c  ", "\t a b c\n", "a\t b\n c"),
        ("😀 가나 확인", "😀 가 나 확인", "😀 가나 확인"),
        ("ab c", "a b c", "ab c"),
        ("단어내부분", "어 내 부", "어내부"),
    ],
)
def test_unique_whitespace_selector_uses_original_codepoint_offsets(
    original_text: str, selector: str, expected: str
) -> None:
    bound = codec.bind_request_span(selector, user_request=original_text)
    assert bound["binding_mode"] == "WHITESPACE_SELECTOR"
    assert (
        bound["source_text"]
        == expected
        == original_text[bound["start_offset"] : bound["end_offset"]]
    )


def test_explicit_unicode_whitespace_set_excludes_zero_width_and_c0_separators() -> None:
    assert len(codec.SELECTOR_WHITESPACE) == 25
    for separator in codec.SELECTOR_WHITESPACE:
        bound = codec.bind_request_span("a b", user_request=f"a{separator}b")
        assert bound["source_text"] == f"a{separator}b"
    for separator in ("\u001c", "\u001d", "\u001e", "\u001f", "\u200b", "\ufeff"):
        with pytest.raises(ValueError, match="codepoint-identical"):
            codec.bind_request_span("a b", user_request=f"a{separator}b")


@pytest.mark.parametrize(
    ("original_text", "selector"),
    [
        ("same same", "same"),  # repeated exact match
        ("ab a b", "a  b"),  # repeated folded match
        ("aaa", "a a"),  # overlapping folded occurrences
        ("Ab", "a b"),  # case change
        ("a-b", "a b"),  # punctuation removal
        ("ＡＢ", "A B"),  # NFKC would change representation
        ("é", "e\u0301"),  # canonical Unicode normalization
        ("ab", "a\u200bb"),  # zero-width insertion
        ("ab", "a\ufeffb"),  # BOM insertion
        ("삭제하지 마", "삭제해"),  # semantic substitution
        ("12분", "1 3분"),  # numeric substitution
        ("alpha", " \t\n\u3000"),  # whitespace-only selector
        ("alpha", ""),
    ],
)
def test_ambiguous_or_non_whitespace_mutation_is_rejected(
    original_text: str, selector: str
) -> None:
    with pytest.raises(ValueError):
        codec.bind_request_span(selector, user_request=original_text)


def test_overlap_and_duplicate_meaning_cannot_be_disambiguated_by_other_work() -> None:
    for request, raw in [
        ("alpha beta", _raw("al pha beta", "beta")),
        ("same same", _raw("same same", "same")),
        ("abc", {"schema_version": 1, "work_units": [{"request_spans": ["a b", "b c"]}]}),
    ]:
        with pytest.raises(ValueError):
            codec.materialize_work_spans(raw, user_request=request)


def test_work_count_and_reading_order_preserved_without_inventing_relation_or_prohibition() -> None:
    request = "내용을 요약해. 발송하지 마."
    raw = _raw("발송 하지 마.", "내용을 요약해.")
    work = codec.materialize_work_spans(raw, user_request=request)
    assert len(work["work_units"]) == 2  # Structural acceptance is NOT semantic approval.
    assert work["work_units"][0]["request_provenance"][0]["source_text"] == "내용을 요약해."
    assert work["work_units"][1]["request_provenance"][0]["source_text"] == "발송하지 마."
    assert work["work_relations"] == []
    assert all(set(unit) == {"unit_id", "request_provenance"} for unit in work["work_units"])


@pytest.mark.parametrize(
    "prior",
    [
        "goal_candidate",
        "request_intent",
        "confirmation_response",
        "request_reconsideration",
        "pending",
    ],
)
def test_prior_or_resume_is_original_validator_and_scope_restores(
    monkeypatch: pytest.MonkeyPatch, prior: str
) -> None:
    from google_work_agent.adapters.langgraph.confirmation_llm_runtime import (
        ConfirmationAwareLLMRuntime,
    )

    original_validator = codec.work_owner.validate_requested_work_candidate
    projected: dict[str, Any] = {"request": SimpleNamespace(run_id="r1", request_text="a b")}
    state = {prior: {}} if prior in {"goal_candidate", "request_intent"} else {}
    if prior in {"confirmation_response", "request_reconsideration"}:
        projected[prior] = {}
    delegate: Any = SimpleNamespace()
    if prior == "pending":
        delegate = ConfirmationAwareLLMRuntime(delegate)
        delegate.register(
            run_id="r1", origin_target="request.detect_ambiguity", response={"response_text": "yes"}
        )
    monkeypatch.setattr(codec, "project_identify_goal_input", lambda _: projected)

    def original(_state: Any, **_kwargs: Any) -> Any:
        return codec.work_owner.validate_requested_work_candidate(_raw("a  b"), user_request="a b")

    monkeypatch.setattr(codec.ru_graph, "identify_goal_node", original)
    events: list[dict[str, Any]] = []
    with (
        codec.work_span_codec_candidate(observations=events),
        pytest.raises(ValueError, match="exactly once"),
    ):
        codec.ru_graph.identify_goal_node(state, llm_runtime=delegate)
    assert events == []
    assert codec.work_owner.validate_requested_work_candidate is original_validator
    assert codec.ru_graph.identify_goal_node is original
    assert codec._active_owner.get() is None


def test_fresh_scope_rejects_another_request_or_run(monkeypatch: pytest.MonkeyPatch) -> None:
    projected = {"request": SimpleNamespace(run_id="r1", request_text="a b")}
    monkeypatch.setattr(codec, "project_identify_goal_input", lambda _: projected)

    def original(_state: Any, **_kwargs: Any) -> Any:
        return codec.work_owner.validate_requested_work_candidate(_raw("a b"), user_request="a b")

    monkeypatch.setattr(codec.ru_graph, "identify_goal_node", original)
    events: list[dict[str, Any]] = []
    with codec.work_span_codec_candidate(observations=events):
        with (
            provider_dispatch_execution_scope(run_id="other"),
            pytest.raises(ValueError, match="current-Run"),
        ):
            codec.ru_graph.identify_goal_node({}, llm_runtime=SimpleNamespace())
        projected["request"].request_text = "another request"
        with (
            provider_dispatch_execution_scope(run_id="r1"),
            pytest.raises(ValueError, match="current-Run"),
        ):
            codec.ru_graph.identify_goal_node({}, llm_runtime=SimpleNamespace())
    assert len(events) == 2


def test_actual_product_compiled_goal_node_keeps_all_wire_inputs_schema_and_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_runtime = goal_tests._runtime
    recorded: list[Any] = []

    def runtime(path: Path, patcher: pytest.MonkeyPatch, replies: list[Any]) -> Any:
        replies = deepcopy(replies)
        replies[0] = _raw("Read  the selected task.")
        result = original_runtime(path, patcher, replies)
        recorded.append(result)
        return result

    monkeypatch.setattr(goal_tests, "_runtime", runtime)
    events: list[dict[str, Any]] = []
    with codec.work_span_codec_candidate(observations=events):
        goal_tests.test_actual_product_identify_goal_node_consumes_cached_output_in_compiled_graph(
            tmp_path, monkeypatch
        )
    _, observation, calls, _ = recorded[0]
    assert len(calls) == 5
    assert observation.calls[0]["prompt_id"] == "request_understanding.identify_requested_work"
    assert observation.calls[0]["input"] == {"user_request": "Read the selected task."}
    assert (
        calls[0]["payload"]["format"] == codec.work_owner.REQUESTED_WORK_OUTPUT_SCHEMA.json_schema
    )
    assert events[0]["events"][0]["bindings"][0]["binding_mode"] == "WHITESPACE_SELECTOR"
    work = events[0]["events"][0]["materialized_work_definition"]
    assert (
        work["work_units"][0]["request_provenance"][0]["source_text"] == "Read the selected task."
    )
