"""085 input/order/safety gates; synthetic fixtures and fake transport only."""

import json
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_answer_choice_adjacent as runner


@pytest.fixture
def adjacent_inputs() -> list[dict[str, Any]]:
    values = []
    for case in runner.handoff.fixtures():
        if case["case_id"] not in runner.CASE_IDS:
            continue
        projection: dict[str, Any] = {}

        def capture(
            prompt_id: str,
            prompt_input: Mapping[str, object],
            *,
            _projection: dict[str, Any] = projection,
        ) -> Mapping[str, object]:
            assert prompt_id == "planning.compose_answer" and not _projection
            _projection.update(runner.handoff._wire_projection(dict(prompt_input)))
            raise runner.handoff._CapturedFirst

        with pytest.raises(runner.handoff._CapturedFirst):
            runner.handoff._pipeline(case, capture, {})
        values.append({**case, "first": projection})
    return values


@pytest.mark.parametrize("group", runner.CASE_IDS)
def test_build_payload__adjacent_input__preserves_product_input_runtime_and_role(
    adjacent_inputs: list[dict[str, Any]],
    group: str,
) -> None:
    case = next(item for item in adjacent_inputs if item["case_id"] == group)
    projection, original = case["first"]["input"], case["first"]["wire_payload"]
    snapshots = case["pipeline_input"]["source_snapshots"]
    before = deepcopy((original, projection, snapshots))
    unordered = runner.choice.choice_wire(original, projection, snapshots)
    payload = runner.build_payload(original, projection, snapshots)
    assert (original, projection, snapshots) == before
    assert payload == unordered  # JSON Schema accepted values are unchanged.
    assert payload["system"] == unordered["system"]
    assert payload["prompt"] == unordered["prompt"]
    assert json.loads(payload["prompt"])["input"] == projection
    assert "source_snapshots" not in json.loads(payload["prompt"])["input"]
    for key in ("model", "think", "stream", "options"):
        assert payload[key] == original[key]
    assert all(order[0] == "mode" for order in runner.property_orders(payload))
    assert runner.ordered.transport_hash(payload) != runner.ordered.transport_hash(unordered)
    if group == "SYNTHETIC_TASK_NOTES":
        assert payload == runner.ordered.mode_first_wire(unordered)
        branches = payload["format"]["oneOf"]
        assert [branch["properties"]["mode"]["const"] for branch in branches] == [
            "FACT_REFERENCES",
            "PROSE",
        ]
        pairs = branches[0]["properties"]["items"]["items"]["enum"]
        assert {item["field"] for item in pairs} == {"title", "notes"}
        assert "status" not in {item["field"] for item in pairs}
        assert "due" not in {item["field"] for item in pairs}
    else:
        assert "oneOf" not in payload["format"]
        assert payload["format"]["properties"]["mode"] == {"const": "PROSE"}


def test_admission__task_notes_only__preserves_literal_without_inventing_status_or_due(
    adjacent_inputs: list[dict[str, Any]],
) -> None:
    case = next(item for item in adjacent_inputs if item["case_id"] == runner.CASE_IDS[0])
    projection = case["first"]["input"]
    snapshots = case["pipeline_input"]["source_snapshots"]
    value = {"mode": "FACT_REFERENCES", "items": [{"evidence_ref": "e-task", "field": "notes"}]}
    draft = runner.choice.candidate.materialize_answer_rendering_choice(
        value,
        prompt_input=projection,
        source_snapshots=snapshots,
    )
    assert draft is not None
    assert draft["answer"].startswith("메모(원문):\n> 장비 수령 항목을 확인할 것")
    assert "상태" not in draft["answer"] and "예정일" not in draft["answer"]
    assert draft["evidence_refs"] == ["e-task"]
    for field in ("status", "due"):
        with pytest.raises(ValueError, match="invalid answer rendering choice"):
            runner.choice.candidate.materialize_answer_rendering_choice(
                {"mode": "FACT_REFERENCES", "items": [{"evidence_ref": "e-task", "field": field}]},
                prompt_input=projection,
                source_snapshots=snapshots,
            )


def test_admission__no_task_catalog__preserves_prose_without_enabling_fact_references(
    adjacent_inputs: list[dict[str, Any]],
) -> None:
    case = next(item for item in adjacent_inputs if item["case_id"] == runner.CASE_IDS[1])
    projection, snapshots = case["first"]["input"], case["pipeline_input"]["source_snapshots"]
    value = {
        "mode": "PROSE",
        "schema_version": 2,
        "answer": "일정의 시간과 장소입니다.",
        "evidence_refs": projection["answer_outline"]["evidence_refs"],
    }
    draft = runner.choice.candidate.materialize_answer_rendering_choice(
        value,
        prompt_input=projection,
        source_snapshots=snapshots,
    )
    assert draft == {key: item for key, item in value.items() if key != "mode"}
    with pytest.raises(ValueError, match="invalid answer rendering choice"):
        runner.choice.candidate.materialize_answer_rendering_choice(
            {"mode": "FACT_REFERENCES", "items": []},
            prompt_input=projection,
            source_snapshots=snapshots,
        )


@pytest.fixture
def sealed_history(adjacent_inputs: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> Any:
    model = {"model_id": "qwen3.5:9b", "model_digest": "synthetic-digest"}
    prior: dict[str, Any] = {"model": model, "cases": deepcopy(adjacent_inputs)}
    raw: dict[str, Any] = {
        "state": "FINISHED",
        "source_binding_unchanged": True,
        "plan_sha256": runner.PRIOR_PLAN_HASH,
        "cases": [],
    }
    for case in prior["cases"]:
        digest = runner.object_hash(case["pipeline_input"])
        case["pipeline_input_sha256"] = digest
        raw["cases"].append(
            {
                "case_id": case["case_id"],
                "state": "RETURNED",
                "pipeline_input_sha256": digest,
                "pipeline_input_unchanged": True,
                "calls": [
                    {
                        **deepcopy(case["first"]),
                        "state": "RETURNED",
                        "structural_validation": "VALID",
                        "provider_response": {
                            "model": model["model_id"],
                            "done": True,
                            "response": "historical response",
                            "prompt_eval_count": 4,
                            "eval_count": 2,
                            "total_duration": 1_000_000,
                        },
                    }
                ],
            }
        )
    monkeypatch.setattr(
        runner.existing,
        "file_hash",
        lambda path: runner.PRIOR_HASH if path == runner.PRIOR else runner.PRIOR_PLAN_HASH,
    )
    monkeypatch.setattr(
        runner.choice.history,
        "read_json",
        lambda path: deepcopy(raw if path == runner.PRIOR else prior),
    )
    monkeypatch.setattr(runner.handoff, "_bound_files", lambda: {})
    monkeypatch.setattr(runner, "head", lambda: "synthetic-head")
    return model, prior, raw


def test_make_plan__unchanged_history__seals_four_new_calls_and_two_baselines(
    sealed_history: Any,
) -> None:
    model, _, _ = sealed_history
    plan = runner.make_plan(model)
    assert [case["case_id"] for case in plan["cases"]] == [
        f"{group}-MODE_FIRST-T{trial}" for trial in (1, 2) for group in runner.CASE_IDS
    ]
    assert plan["policy"]["new_calls"] == 4
    assert plan["policy"]["historical_calls"] == len(plan["historical_prose"]) == 2
    assert all(item["new_call"] is False for item in plan["historical_prose"])
    assert plan["semantic_verdict"] == "NOT_REVIEWED"
    runner.verify_wire_seals(plan)


@pytest.mark.parametrize("drift", ["model", "input", "wire", "snapshot", "response", "row_count"])
def test_make_plan__historical_drift__rejects_before_generation(
    sealed_history: Any,
    drift: str,
) -> None:
    model, prior, raw = sealed_history
    if drift == "model":
        model = {**model, "model_digest": "another"}
    elif drift == "input":
        prior["cases"][0]["first"]["input"]["user_request"] = "changed"
    elif drift == "wire":
        raw["cases"][0]["calls"][0]["wire_payload"]["options"]["seed"] += 1
    elif drift == "snapshot":
        prior["cases"][0]["pipeline_input"]["source_snapshots"] = {}
    elif drift == "response":
        raw["cases"][0]["calls"][0]["provider_response"]["done"] = False
    else:
        raw["cases"].append(deepcopy(raw["cases"][0]))
    with pytest.raises(ValueError):
        runner.make_plan(model)


def test_verify_wire_seals__order_only_change__rejects_dict_equal_payload(
    sealed_history: Any,
) -> None:
    plan = runner.make_plan(sealed_history[0])
    before = deepcopy(plan)
    branch = plan["cases"][0]["candidate_payload"]["format"]["oneOf"][0]
    branch["properties"] = dict(reversed(list(branch["properties"].items())))
    assert plan == before
    with pytest.raises(ValueError, match="order drift"):
        runner.verify_wire_seals(plan)


def test_execute_plan__fake_transport__records_once_without_hidden_reasoning_or_retry(
    sealed_history: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = runner.make_plan(sealed_history[0])
    recorder = runner.choice.recorder
    monkeypatch.setattr(recorder, "RESULTS", tmp_path)
    monkeypatch.setattr(runner.existing, "inspect_diagnostic_model", lambda _: sealed_history[0])
    calls = []

    def post(**kwargs: Any) -> dict[str, Any]:
        payload = deepcopy(kwargs["payload"])
        calls.append(payload)
        body = json.loads(payload["prompt"])
        value = {
            "mode": "PROSE",
            "schema_version": 2,
            "answer": "주어진 자료를 확인했습니다.",
            "evidence_refs": body["input"]["answer_outline"]["evidence_refs"],
        }
        return {
            "model": plan["model"]["model_id"],
            "done": True,
            "response": json.dumps(value),
            "prompt_eval_count": 5,
            "eval_count": 3,
            "thinking": "HIDDEN_NOT_FOR_STORAGE",
        }

    monkeypatch.setattr(recorder.existing.transport, "_post_json", post)
    raw = runner.execute_plan(plan, tmp_path / "trial", plan_sha256=runner.object_hash(plan))
    assert raw["actual_http_calls"] == len(calls) == 4
    assert raw["completed"] and raw["binding_unchanged"]
    assert raw["provider_calls"] == raw["graph_calls"] == 0
    assert "HIDDEN_NOT_FOR_STORAGE" not in json.dumps(raw)
    assert all(
        row["answer_admission"]["validation"]["structural_result"] == "VALID"
        for row in raw["calls"]
    )
    assert all(
        row["answer_admission"]["semantic_verdict"] == "NOT_REVIEWED" for row in raw["calls"]
    )
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan, tmp_path / "repeat", plan_sha256=runner.object_hash(plan))
    assert len(calls) == 4
