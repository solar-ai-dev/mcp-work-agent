from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort
from tests.unit.application.agents.request_understanding.test_identify_goal import _request
from tests.unit.application.agents.request_understanding.test_identify_requested_work import _prompt

from google_work_agent.application.agents.request_understanding import identify_goal as goal_owner
from google_work_agent.application.agents.request_understanding.bind_work_request_span import (
    bind_work_request_span,
)
from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
)
from google_work_agent.application.agents.request_understanding.identify_requested_work import (
    identify_requested_work,
    validate_requested_work_candidate,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget


def _raw(selector: str) -> dict[str, Any]:
    return {"schema_version": 1, "work_units": [{"request_spans": [selector]}]}


def _owner_prompts() -> dict[str, Any]:
    return {
        field: _prompt(f"request_understanding.{operation}", operation)
        for field, operation in (
            ("prompt_ref", "identify_goal"),
            ("requested_work_prompt_ref", "identify_requested_work"),
            ("work_relation_prompt_ref", "identify_work_relations"),
            ("effect_prohibition_prompt_ref", "identify_effect_prohibitions"),
            ("source_dependency_prompt_ref", "identify_source_dependencies"),
            ("output_responsibility_prompt_ref", "identify_output_responsibilities"),
            ("source_status_prompt_ref", "identify_source_status"),
        )
    }


@pytest.mark.parametrize(
    ("original", "selector"),
    [
        ("8월 12일", "8 월 12 일"),
        ("a@example.test에", "a@example.test 에"),
        ("  a\t b\n c  ", "a b c"),
        ("😀 가나", "😀 가 나"),
        ("단어내부분", "어 내 부"),
    ],
)
def test_fresh_codec_preserves_exact_typed_slice_without_changing_wire(
    original: str, selector: str
) -> None:
    prompt = _prompt("request_understanding.identify_requested_work", "identify_goal")
    strict = FakeStructuredInferencePort(outputs=[_raw(selector)], validate_schema=True)
    fresh = FakeStructuredInferencePort(outputs=[_raw(selector)], validate_schema=True)
    kwargs = {"requested_mode": "LOCAL_GPU", "prompt_ref": prompt, "user_request": original}
    with pytest.raises(ValueError, match="exactly once"):
        identify_requested_work(llm_runtime=strict, **kwargs)
    work = identify_requested_work(llm_runtime=fresh, allow_whitespace_selector=True, **kwargs)
    assert strict.calls == fresh.calls and len(fresh.calls) == 1
    span = work["work_units"][0]["request_provenance"][0]
    assert span["source_text"] == original[span["start_offset"] : span["end_offset"]]
    assert validate_requested_work_definition(work, user_request=original) == work
    changed = deepcopy(work)
    changed["work_units"][0]["request_provenance"][0]["source_text"] = selector
    with pytest.raises(ValueError, match="source-bound"):
        validate_requested_work_definition(changed, user_request=original)


@pytest.mark.parametrize(
    ("original", "selector"),
    [
        ("same same", "same"),
        ("ab a b", "a  b"),
        ("aaa", "a a"),
        ("Ab", "a b"),
        ("a-b", "a b"),
        ("ＡＢ", "A B"),
        ("é", "e\u0301"),
        ("ab", "a\u200bb"),
        ("a\u001cb", "a b"),
        ("ab", "a\ufeffb"),
        ("12분", "1 3분"),
        ("alpha", " \t\n"),
    ],
)
def test_codec_rejects_ambiguity_and_all_non_whitespace_mutation(
    original: str, selector: str
) -> None:
    with pytest.raises(ValueError):
        bind_work_request_span(selector, user_request=original, allow_whitespace_selector=True)


def test_exact_priority_and_whitespace_only_admission_are_explicit() -> None:
    assert bind_work_request_span(
        "ab", user_request="a b / ab", allow_whitespace_selector=True
    ) == (6, 8)
    for codepoint in (
        9,
        10,
        11,
        12,
        13,
        32,
        133,
        160,
        5760,
        *range(8192, 8203),
        8232,
        8233,
        8239,
        8287,
        12288,
    ):
        assert bind_work_request_span(
            "a b", user_request=f"a{chr(codepoint)}b", allow_whitespace_selector=True
        ) == (0, 3)


def test_default_exact_only_preserves_legacy_whitespace_only_selector() -> None:
    raw = _raw(" ")
    expected = {
        "work_units": [
            {
                "unit_id": "work-1",
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": 1,
                        "end_offset": 2,
                        "source_text": " ",
                    }
                ],
            }
        ],
        "work_relations": [],
    }
    assert validate_requested_work_candidate(raw, user_request="a b") == expected
    assert bind_work_request_span(" ", user_request="a b") == (1, 2)
    with pytest.raises(ValueError, match="only whitespace"):
        bind_work_request_span(" ", user_request="a b", allow_whitespace_selector=True)


def test_exact_state_and_work_count_relations_are_not_reinterpreted() -> None:
    original = "내용을 요약해. 발송하지 마."
    raw = {
        "schema_version": 1,
        "work_units": [
            {"request_spans": ["발송하지 마."]},
            {"request_spans": ["내용을 요약해."]},
        ],
    }
    runtime = FakeStructuredInferencePort(outputs=[raw], validate_schema=True)
    work = identify_requested_work(
        llm_runtime=runtime,
        requested_mode="LOCAL_GPU",
        prompt_ref=_prompt("request_understanding.identify_requested_work", "identify_goal"),
        user_request=original,
        allow_whitespace_selector=True,
    )
    assert work == validate_requested_work_candidate(raw, user_request=original)
    assert len(work["work_units"]) == 2 and work["work_relations"] == []
    # A structurally valid extra Work is not silently merged into another Work.


def test_codec_cannot_overwrite_overlapping_original_ranges() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "schema_version": 1,
                "work_units": [{"request_spans": ["al pha beta", "beta"]}],
            }
        ]
    )
    with pytest.raises(ValueError, match="overlap"):
        identify_requested_work(
            llm_runtime=runtime,
            requested_mode="LOCAL_GPU",
            prompt_ref=_prompt("request_understanding.identify_requested_work", "identify_goal"),
            user_request="alpha beta",
            allow_whitespace_selector=True,
        )


@pytest.mark.parametrize("mode", ["default", "fresh", "confirmation", "reconsideration", "prior"])
def test_budgeted_owner_defensively_limits_codec_to_fresh_initial_work(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    observed = []

    class StopAfterWorkOptions(Exception):
        pass

    def capture(**kwargs: Any) -> Any:
        observed.append(kwargs["allow_whitespace_selector"])
        raise StopAfterWorkOptions

    monkeypatch.setattr(goal_owner, "identify_requested_work", capture)
    extra: dict[str, Any] = {}
    if mode != "default":
        extra["allow_whitespace_work_selector"] = True
    if mode == "confirmation":
        extra["confirmation_response"] = {}
    if mode == "reconsideration":
        extra["request_reconsideration"] = {}
    if mode == "prior":
        extra["prior_goal_candidate"] = {}
    with pytest.raises(StopAfterWorkOptions):
        goal_owner.identify_goal_with_budget(
            llm_runtime=FakeStructuredInferencePort(outputs=[]),
            request=_request("a b"),
            retry_budget=build_default_run_budget(),
            source_dependency_candidates=(),
            output_responsibility_candidates=(),
            **_owner_prompts(),
            **extra,
        )
    assert observed == [mode == "fresh"]


def test_confirmation_reuses_exact_existing_work_without_invoking_work_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = validate_requested_work_candidate(_raw("a b"), user_request="a b")
    prior = {"requested_work": work}
    before = deepcopy(prior)

    def forbidden(**_kwargs: Any) -> Any:
        raise AssertionError("confirmation must not regenerate Work")

    def resolve(**kwargs: Any) -> Any:
        assert kwargs["prior_goal_candidate"] is prior
        assert kwargs["prompt_input"]["requested_work"] == work
        return prior, kwargs["retry_budget"]

    monkeypatch.setattr(goal_owner, "identify_requested_work", forbidden)
    monkeypatch.setattr(goal_owner, "_resolve_confirmed_goal", resolve)
    result, _ = goal_owner.identify_goal_with_budget(
        llm_runtime=FakeStructuredInferencePort(outputs=[]),
        request=_request("a b"),
        retry_budget=build_default_run_budget(),
        source_dependency_candidates=(),
        output_responsibility_candidates=(),
        confirmation_response={},
        prior_goal_candidate=prior,
        allow_whitespace_work_selector=True,
        **_owner_prompts(),
    )
    assert result is prior and prior == before


def test_budgetless_and_candidate_revision_keep_strict_admission() -> None:
    runtime = FakeStructuredInferencePort(outputs=[_raw("a  b")])
    with pytest.raises(ValueError, match="exactly once"):
        goal_owner.identify_goal(
            llm_runtime=runtime,
            request=_request("a b"),
            source_dependency_candidates=(),
            output_responsibility_candidates=(),
            **_owner_prompts(),
        )
    runtime = FakeStructuredInferencePort(outputs=[_raw("a  b")])
    with pytest.raises(ValueError, match="exactly once"):
        identify_requested_work(
            llm_runtime=runtime,
            requested_mode="LOCAL_GPU",
            prompt_ref=_prompt("request_understanding.identify_requested_work", "identify_goal"),
            user_request="a b",
            candidate_output={},
            failure_record={},
            allow_whitespace_selector=True,
        )
