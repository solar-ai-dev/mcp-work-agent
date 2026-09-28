"""v29 fixture/Prompt/wire gates. No model, graph or Provider is invoked."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from evaluation.dataset_v8 import load_cases
from scripts import evaluate_ambiguity_owner as runner
from scripts.ru_ambiguity_owner_candidate import INPUT_MARKER, ambiguity_owner_instruction

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry


@pytest.fixture(scope="module")
def plan() -> dict[str, Any]:
    return runner.make_plan(model_digest=None)


def test_registration_freezes_six_cases_and_identical_input_schema(plan: dict[str, Any]) -> None:
    assert len(plan["case_ids"]) == len(set(plan["case_ids"])) == 6
    assert plan["max_first_calls"] == 12
    assert plan["max_total_calls_with_schema_repair"] == 24
    assert plan["semantic_revision_calls"] == plan["provider_reads"] == plan["provider_writes"] == 0
    assert "scripts/ru_observation.py" in plan["source_hashes"]
    for case in plan["cases"]:
        left, right = case["arms"]["baseline"], case["arms"]["candidate"]
        assert left["input"] == right["input"]
        assert left["schema"] == right["schema"]
        assert left["input_sha256"] == right["input_sha256"]
        assert left["assembled_instruction_sha256"] != right["assembled_instruction_sha256"]
        text = json.dumps(left["input"], ensure_ascii=False)
        assert "expected_owners" not in text
        assert "expectation_basis" not in text
        assert "case_id" not in left["input"]


def test_candidate_deletes_only_count_rules_and_examples(plan: dict[str, Any]) -> None:
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(runner.PROMPT_ID)
    projection = plan["cases"][0]["arms"]["baseline"]["input"]
    before = runner.owner_instruction(projection, ref, registry, "baseline")
    after = runner.owner_instruction(projection, ref, registry, "candidate")
    source, _, input_text = before.partition(INPUT_MARKER)
    candidate, _, after_input = after.partition(INPUT_MARKER)
    assert input_text == after_input
    assert "다음 네 값만으로" not in candidate
    assert "결과는 반드시" not in candidate
    assert "구조 예시:" not in candidate
    assert "connector_owned_source_count=1" not in candidate
    assert "READ라는 이유만으로 판단을 생략하지 않고" in candidate
    assert "goal_candidate.requested_work" in candidate
    assert "Source identity와 새 output identity를 혼동하지 않는다." in candidate
    assert candidate[candidate.index("# 출력") :] == source[source.index("# 출력") :]
    # Every retained nonempty line already existed, apart from list renumbering.
    for line in candidate.splitlines():
        if line.startswith("2. 대상이 선택됐거나"):
            line = "4." + line[2:]
        if line.startswith("3. 사용자 선택과"):
            line = "5." + line[2:]
        assert not line or line in source.splitlines()


@pytest.mark.parametrize("bad", ["no envelope", "new source" + INPUT_MARKER + "{}"])
def test_unreviewed_prompt_shape_is_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        ambiguity_owner_instruction(bad)


def test_original_observed_core_semantics_and_provenance_are_preserved(
    plan: dict[str, Any],
) -> None:
    canonical = load_cases()
    frozen = json.loads(runner.CORE_FIXTURE.read_text(encoding="utf-8"))
    for case, original in zip(plan["cases"][4:], frozen, strict=True):
        assert case["user_request"] == canonical[case["case_id"]].raw["canonical_user_prompt"]
        assert "\ufffd" not in json.dumps(case, ensure_ascii=False)
        assert case["goal_candidate"]["constraints"] == original["goal_candidate"]["constraints"]
        assert (
            case["goal_candidate"]["requested_work"] == original["goal_candidate"]["requested_work"]
        )
        assert case["selected_resource_refs"] == original["selected_resource_refs"]
        assert case["origin"]["old_response_reused"] is False
        assert len(case["origin"]["raw_sha256"]) == 64
        assert len(case["origin"]["binding"]["product_sha"]) == 40
        assert (
            case["origin"]["old_ambiguity_input_sha256"] != case["arms"]["baseline"]["input_sha256"]
        )
    source_types = {
        item["resource_type"]
        for item in plan["cases"][5]["goal_candidate"]["resource_responsibilities"]["source_reads"]
    }
    # Incorrect upstream choices must not be silently repaired by this experiment.
    assert source_types == {"GMAIL_DRAFT", "CALENDAR"}


def test_count_collision_and_collection_are_actual_product_projections(
    plan: dict[str, Any],
) -> None:
    first = plan["cases"][0]["arms"]["baseline"]["input"]
    info = first["resolution_responsibilities"]
    assert info["searchable_target_anchor_count"] == 1
    assert info["connector_owned_source_count"] == 2
    source = first["goal_candidate"]["resource_responsibilities"]["source_reads"]
    assert [item["work_unit_ids"] for item in source] == [["work-1"], ["work-2"]]
    collection = plan["cases"][2]["arms"]["baseline"]["input"]
    assert collection["resolution_responsibilities"]["searchable_target_anchor_count"] == 0
    assert (
        collection["goal_candidate"]["resource_responsibilities"]["source_reads"][0]["target_scope"]
        == "CRITERIA"
    )
    create = plan["cases"][3]["arms"]["baseline"]["input"]
    assert create["goal_candidate"]["resource_responsibilities"]["source_reads"] == []


@pytest.mark.parametrize("index", [0, 1])
def test_product_guard_preserves_multi_work_user_target(plan: dict[str, Any], index: int) -> None:
    ref = PromptRegistry().lookup_for_evaluation(runner.PROMPT_ID)
    raw = {"missing_information_owner": "USER", "missing_fields": ["target_resource"]}
    actual, _, result = runner.owner_result(plan["cases"][index], raw, ref)
    assert actual == plan["cases"][index]["arms"]["baseline"]["input"]
    assert result["requires_confirmation"] is True
    assert result["missing_fields"] == ["target_resource"]


def _fake_transport(monkeypatch: pytest.MonkeyPatch, outputs: list[object]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(deepcopy(kwargs))
        return {
            "response": json.dumps(outputs.pop(0), ensure_ascii=False),
            "model": runner.MODEL_ID,
            "prompt_eval_count": 30,
            "eval_count": 20,
            "total_duration": 1000000,
        }

    monkeypatch.setattr(transport, "_post_json", post)
    return calls


def test_wire_policy_raw_postvalidation_and_no_gold_are_separate(
    monkeypatch: pytest.MonkeyPatch, plan: dict[str, Any]
) -> None:
    raw = {"missing_information_owner": "USER", "missing_fields": ["target_resource"]}
    calls = _fake_transport(monkeypatch, [raw])
    record = runner.run_arm(
        plan["cases"][0], "candidate", transport.OllamaHTTPClient(), PromptRegistry()
    )
    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert payload["options"] == {"num_ctx": 16384, "temperature": 0.0, "seed": runner.SEED}
    assert payload["think"] is False
    assert calls[0]["timeout_seconds"] == 180
    assert "expected_owners" not in payload["system"]
    assert record["attempts"][0]["raw_output"] == raw
    assert record["final"]["structural_result"] == "PASS"
    assert record["final"]["postvalidator_output"]["requires_confirmation"] is True
    assert record["final"]["semantic_review"] == "PENDING_MANUAL_REVIEW"
    assert record["metrics"]["calls"] == 1
    assert record["metrics"]["missing_usage_calls"] == 0


def test_schema_repair_is_bounded_and_preserves_first_failed_output(
    monkeypatch: pytest.MonkeyPatch, plan: dict[str, Any]
) -> None:
    calls = _fake_transport(
        monkeypatch,
        [
            {"missing_information_owner": "USER"},
            {"missing_information_owner": "USER", "missing_fields": ["target_resource"]},
        ],
    )
    record = runner.run_arm(
        plan["cases"][0], "candidate", transport.OllamaHTTPClient(), PromptRegistry()
    )
    assert len(calls) == 2
    assert record["attempts"][0]["schema_errors"]
    assert record["attempts"][1]["attempt"] == "SCHEMA_REPAIR"
    assert record["attempts"][1]["out_of_scope_repair_changes"] == []
    assert record["final"]["structural_result"] == "PASS"
    assert "base_projection" in calls[1]["payload"]["prompt"]
    assert "candidate_output" in calls[1]["payload"]["prompt"]
    assert "다음 네 값만으로" not in calls[1]["payload"]["system"]


def test_schema_repair_cannot_change_unaffected_owner(
    monkeypatch: pytest.MonkeyPatch, plan: dict[str, Any]
) -> None:
    calls = _fake_transport(
        monkeypatch,
        [
            {"missing_information_owner": "USER"},
            {"missing_information_owner": "NONE", "missing_fields": []},
        ],
    )
    record = runner.run_arm(
        plan["cases"][0], "candidate", transport.OllamaHTTPClient(), PromptRegistry()
    )
    assert len(calls) == 2
    assert record["final"]["structural_result"] == "FAIL"
    assert record["attempts"][1]["out_of_scope_repair_changes"]


def test_semantic_validator_error_does_not_start_repair_or_revision(
    monkeypatch: pytest.MonkeyPatch, plan: dict[str, Any]
) -> None:
    calls = _fake_transport(
        monkeypatch, [{"missing_information_owner": "NONE", "missing_fields": ["target_resource"]}]
    )
    record = runner.run_arm(
        plan["cases"][0], "candidate", transport.OllamaHTTPClient(), PromptRegistry()
    )
    assert len(calls) == 1
    assert record["attempts"][0]["schema_errors"] == []
    assert record["final"]["structural_result"] == "FAIL"
    assert record["final"]["error_type"] == "RequestAmbiguityValidationError"


def test_owner_category_alone_is_not_semantic_pass(plan: dict[str, Any]) -> None:
    record = runner.grade_first(
        {"missing_information_owner": "USER", "missing_fields": ["invented_unrelated_choice"]},
        plan["cases"][5],
    )
    assert record["owner_choice"] == "OWNER_CHOICE_PASS"
    assert record["semantic_review"].startswith("REQUIRED")
