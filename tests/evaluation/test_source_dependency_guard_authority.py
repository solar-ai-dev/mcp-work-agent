"""Historical guard/caller versus current Product, with fake owners and no I/O.

Only three AST-exact definitions from 21ebde2c are frozen. Historical caller
execution uses current helper globals, schemas, projections, and fake owners; it
is a bounded admission comparison, not a replay of that whole historical build.
The current arm runs the real current Product without an identity monkeypatch.
Admitting the external-missing control remains a risk, not business success.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort
from tests.unit.application.agents.request_understanding import test_identify_goal as support

from google_work_agent.application.agents.request_understanding import (
    identify_goal as goal_operation,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef

_SOURCE = "request_understanding.identify_source_dependencies"
_GOAL_REF = support._prompt_ref("request_understanding.identify_goal", "identify_goal")
_MEMO = (
    "아래 메모에서 Project Cedar의 승인 요청만 찾아 정리해줘. "
    "메모: Project Cedar의 승인 요청은 보류이고 추가 자료를 기다린다."
)
_EXTERNAL = "내 메일에서 Project Cedar의 승인 요청을 찾아 정리해줘."
_HISTORICAL_COMMIT = "21ebde2c99cfcfeee67df297ec4900ab199de392"
_HISTORICAL_FIXTURE = Path(__file__).with_name("fixtures") / "source_guard_caller_21ebde2c.py.txt"
_HISTORICAL_DEFINITION_HASHES = {
    "SourceDependencyContradictionError": (
        "8af73b63116353706039d34459ee413fdfd901cf2cb3f9cab9e065f95ca8eb69"
    ),
    "validate_source_dependency_semantics": (
        "72810194a28f50dc62efc477d289f98f6eb5faa81bc35a218e812b844c7eddcc"
    ),
    "identify_goal_with_budget": (
        "4cbf664664edbb6cfd975f80704f535ae696f21b96111a1b855ff1497f010906"
    ),
}


@pytest.fixture
def historical_owner() -> dict[str, Any]:
    source = _HISTORICAL_FIXTURE.read_text(encoding="utf-8")
    assert f"# Source commit: {_HISTORICAL_COMMIT}\n" in source
    tree = ast.parse(source)
    definitions = {
        node.name: ast.get_source_segment(source, node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    assert len(tree.body) == len(definitions) == 3
    assert {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in definitions.items()
        if text is not None
    } == _HISTORICAL_DEFINITION_HASHES
    namespace = dict(vars(goal_operation))
    # The historical exception came from the Source module, whose import globals
    # included deepcopy; the Goal caller itself does not import that helper.
    namespace["deepcopy"] = deepcopy
    # Execute only the hash-pinned, checked-in fixture. CI requires no Git history.
    exec(
        compile("from __future__ import annotations\n" + source, str(_HISTORICAL_FIXTURE), "exec"),
        namespace,
    )
    return namespace


def _goal(text: str, *, named: bool) -> dict[str, object]:
    return {
        "goal": text,
        "completion_conditions": ["사용자가 요청한 결과를 제공한다"],
        "constraints": support._goal_constraints(
            search_terms=["Project Cedar"] if named else [],
            business_concepts=["승인 요청"] if named else [],
        ),
        "analysis_requirement": "NONE",
    }


def _runtime(
    text: str,
    *,
    named: bool = False,
    sources: dict[str, tuple[list[str], str]] | None = None,
    outputs: dict[str, str] | None = None,
    revision: bool = False,
) -> FakeStructuredInferencePort:
    source = support._source_dependency_decisions(source_types=sources)
    queue: list[object] = [
        _goal(text, named=named),
        source,
        support._output_responsibility_decisions(output_types=outputs),
    ]
    if revision:
        queue.append(deepcopy(source))
    # The existing fake supplies one full-request WorkUnit, no prohibitions and
    # empty status. This does not evaluate decomposition or those semantic owners.
    return FakeStructuredInferencePort(outputs=queue, validate_schema=True)


def _invoke(runtime: FakeStructuredInferencePort, text: str, **kwargs: Any) -> Any:
    return support.identify_goal_with_budget(
        llm_runtime=runtime,
        request=kwargs.pop("request", support._request(text)),
        prompt_ref=_GOAL_REF,
        retry_budget=build_default_run_budget(),
        **kwargs,
    )


def _invoke_arm(
    runtime: FakeStructuredInferencePort,
    text: str,
    *,
    monkeypatch: pytest.MonkeyPatch,
    historical_owner: dict[str, Any],
    historical: bool,
    **kwargs: Any,
) -> Any:
    if not historical:
        assert support._identify_goal_with_budget is goal_operation.identify_goal_with_budget
        return _invoke(runtime, text, **kwargs)
    with monkeypatch.context() as scoped:
        scoped.setattr(
            support, "_identify_goal_with_budget", historical_owner["identify_goal_with_budget"]
        )
        return _invoke(runtime, text, **kwargs)


def _source_calls(runtime: FakeStructuredInferencePort) -> list[Any]:
    return [call for call in runtime.calls if call["prompt_ref"].prompt_id == _SOURCE]


def _assert_original_source_input(runtime: FakeStructuredInferencePort, text: str) -> None:
    first = _source_calls(runtime)[0]
    assert first["prompt_input"]["user_request"] == text
    assert first["prompt_input"]["goal_candidate"] == {
        **_goal(text, named=True),
        "completion_conditions": [],
    }
    units = first["prompt_input"]["requested_work"]["work_units"]
    assert units == [
        {
            "unit_id": "work-1",
            "request_provenance": [
                {
                    "source": "USER_REQUEST",
                    "source_text": text,
                    "start_offset": 0,
                    "end_offset": len(text),
                }
            ],
        }
    ]


@pytest.mark.parametrize(
    "text, interpretation",
    [
        (_MEMO, "valid_input_only_answer_rejected_by_baseline"),
        (_EXTERNAL, "missing_external_source_admitted_by_current_is_not_business_success"),
    ],
    ids=["provided-memo-false-positive", "external-omission-risk"],
)
def test_guard_admission_distinguishes_neither_available_facts_nor_external_need(
    monkeypatch: pytest.MonkeyPatch,
    historical_owner: dict[str, Any],
    text: str,
    interpretation: str,
) -> None:
    baseline = _runtime(text, named=True, revision=True)
    with pytest.raises(historical_owner["SourceDependencyContradictionError"]) as failure:
        _invoke_arm(
            baseline,
            text,
            monkeypatch=monkeypatch,
            historical_owner=historical_owner,
            historical=True,
        )
    assert failure.value.reason_code == "INTENT_SOURCE_DEPENDENCY_CONTRADICTION"
    assert failure.value.candidate_output == support._source_dependency_decisions()
    baseline_calls = _source_calls(baseline)
    assert len(baseline_calls) == 2
    assert len(baseline.calls) == 6
    assert not baseline.outputs
    revision_input = baseline_calls[1]["prompt_input"]
    assert revision_input["base_projection"] == baseline_calls[0]["prompt_input"]
    assert revision_input["candidate_output"] == failure.value.candidate_output
    assert revision_input["failure_record"]["failure_reason_code"] == failure.value.reason_code
    _assert_original_source_input(baseline, text)

    candidate = _runtime(text, named=True)
    result, budget = _invoke_arm(
        candidate,
        text,
        monkeypatch=monkeypatch,
        historical_owner=historical_owner,
        historical=False,
    )
    assert len(_source_calls(candidate)) == 1
    assert len(candidate.calls) == 5
    assert not candidate.outputs
    assert candidate.calls == baseline.calls[:5]
    assert budget["semantic_revisions_used_by_failure"] == {}
    assert result["resource_responsibilities"] == {"source_reads": [], "outputs": []}
    assert result["requested_effect_hints"] == []
    assert result["requested_resource_hints"] == []
    for field, value in (("search_terms", "Project Cedar"), ("business_concepts", "승인 요청")):
        assert {
            "kind": "USER_REQUIREMENT",
            "field": field,
            "value": [value],
            "work_unit_ids": ["work-1"],
        } in result["constraints"]
    # Both inputs have the same guard-visible slots. Only the first is a valid
    # source-free task: success of this assertion is NOT a semantic PASS for both.
    assert (interpretation.startswith("valid_input_only")) == (text == _MEMO)


@pytest.mark.parametrize(
    "text,named,sources,outputs",
    [
        ("간단한 인사말을 알려줘.", False, None, None),
        (_EXTERNAL, True, {"GMAIL_THREAD": (["승인 요청 내용"], "CRITERIA")}, None),
        (
            "Project Cedar 승인 요청 제목으로 새 메일 초안을 만들어줘.",
            True,
            None,
            {"GMAIL_DRAFT": "CREATE"},
        ),
    ],
    ids=["general-source-free", "external-source-present", "standalone-write"],
)
def test_controls_keep_identical_candidate_calls_and_revision_budget(
    monkeypatch: pytest.MonkeyPatch,
    historical_owner: dict[str, Any],
    text: str,
    named: bool,
    sources: dict[str, tuple[list[str], str]] | None,
    outputs: dict[str, str] | None,
) -> None:
    baseline = _runtime(text, named=named, sources=sources, outputs=outputs)
    expected, expected_budget = _invoke_arm(
        baseline,
        text,
        monkeypatch=monkeypatch,
        historical_owner=historical_owner,
        historical=True,
    )
    candidate = _runtime(text, named=named, sources=sources, outputs=outputs)
    actual, actual_budget = _invoke_arm(
        candidate,
        text,
        monkeypatch=monkeypatch,
        historical_owner=historical_owner,
        historical=False,
    )
    assert actual == expected
    assert candidate.calls == baseline.calls
    assert len(_source_calls(candidate)) == 1
    assert not candidate.outputs and not baseline.outputs
    assert actual_budget == expected_budget
    assert actual_budget["semantic_revisions_used_by_failure"] == {}
    assert actual["resource_responsibilities"]["source_reads"] == [
        {
            "resource_type": resource,
            "required_information": facts,
            "target_scope": scope,
            "work_unit_ids": ["work-1"],
        }
        for resource, (facts, scope) in (sources or {}).items()
    ]


@pytest.mark.parametrize("historical", [True, False], ids=["historical-21ebde2c", "current"])
def test_selected_identity_read_requirement_is_not_the_ablation_guard(
    monkeypatch: pytest.MonkeyPatch,
    historical_owner: dict[str, Any],
    historical: bool,
) -> None:
    text = "선택한 메일을 읽고 요약해줘."
    selected = SelectedResourceRef("ref-mail-1", "google_workspace", "gmail_thread", "mail-1")
    request = replace(
        support._request(text),
        entry_mode="RESOURCE_SELECTED",
        selected_resource_ids=(selected.resource_id,),
        selected_resources=(selected,),
    )
    runtime = _runtime(text)
    result, budget = _invoke_arm(
        runtime,
        text,
        monkeypatch=monkeypatch,
        historical_owner=historical_owner,
        historical=historical,
        request=request,
    )
    assert result["requested_effect_hints"] == ["READ"]
    assert result["requested_resource_hints"] == ["GMAIL_THREAD"]
    assert result["resource_responsibilities"]["source_reads"] == [
        {
            "resource_type": "GMAIL_THREAD",
            "required_information": [],
            "target_scope": "SINGULAR",
            "work_unit_ids": ["work-1"],
        }
    ]
    assert {
        "kind": "RESOURCE",
        "field": "selected_resource_id",
        "value": ["mail-1"],
        "work_unit_ids": ["work-1"],
    } in result["constraints"]
    assert _source_calls(runtime)[0]["prompt_input"]["selected_resource_refs"]
    assert len(_source_calls(runtime)) == 1
    assert budget["semantic_revisions_used_by_failure"] == {}


@pytest.mark.parametrize("historical", [True, False], ids=["historical-21ebde2c", "current"])
@pytest.mark.parametrize("source_present", [False, True], ids=["source-missing", "source-present"])
def test_confirmed_target_schema_still_requires_source_under_both_arms(
    monkeypatch: pytest.MonkeyPatch,
    historical_owner: dict[str, Any],
    historical: bool,
    source_present: bool,
) -> None:
    text = "그 일정의 시작과 끝을 알려줘."
    # Prepare an already validated, source-unresolved state through the same real
    # caller; then exercise its same-Run target confirmation branch.
    prior, _ = _invoke_arm(
        _runtime(text),
        text,
        monkeypatch=monkeypatch,
        historical_owner=historical_owner,
        historical=historical,
    )
    sources = {"CALENDAR_EVENT": (["start", "end"], "SINGULAR")} if source_present else None
    decision = support._source_dependency_decisions(source_types=sources)
    runtime = FakeStructuredInferencePort(outputs=[decision])
    kwargs: dict[str, Any] = {
        "prior_goal_candidate": prior,
        "prior_ambiguity_candidate": {
            "requires_confirmation": True,
            "reason_codes": ["MISSING_TARGET_RESOURCE"],
            "missing_fields": ["target_resource"],
        },
        "confirmation_response": {
            "schema_version": 1,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "제품 검토 모임",
        },
    }
    if source_present:
        result, budget = _invoke_arm(
            runtime,
            text,
            monkeypatch=monkeypatch,
            historical_owner=historical_owner,
            historical=historical,
            **kwargs,
        )
        assert result["requested_effect_hints"] == ["READ"]
        assert (
            result["resource_responsibilities"]["source_reads"][0]["resource_type"]
            == "CALENDAR_EVENT"
        )
        assert result["requested_work"] == prior["requested_work"]
        assert result["goal"] == prior["goal"]
        assert budget["semantic_revisions_used_by_failure"] == {}
    else:
        # Fake does not validate this deliberately invalid response; the actual
        # Product source candidate validator must reject it before merge.
        with pytest.raises(ValueError, match="source dependency candidate is invalid"):
            _invoke_arm(
                runtime,
                text,
                monkeypatch=monkeypatch,
                historical_owner=historical_owner,
                historical=historical,
                **kwargs,
            )
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["prompt_ref"].prompt_id == _SOURCE
    schema = runtime.calls[0]["output_schema"].json_schema
    assert validate_output_schema(support._source_dependency_decisions(), schema)
    assert not validate_output_schema(
        support._source_dependency_decisions(
            source_types={"CALENDAR_EVENT": (["start", "end"], "SINGULAR")}
        ),
        schema,
    )
    source_goal = runtime.calls[0]["prompt_input"]["goal_candidate"]
    assert isinstance(source_goal, Mapping)
    assert any(
        item["field"] == "search_terms"
        and item["value"] == "제품 검토 모임"
        and item["provenance"]["source"] == "CONFIRMATION_RESPONSE"
        for item in source_goal["constraints"]
    )
