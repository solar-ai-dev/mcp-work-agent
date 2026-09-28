"""091 exact alias view and fake transport; no model or Provider operations."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import answer_acquisition_alias_candidate as candidate
from scripts import evaluate_answer_acquisition_alias as runner
from scripts.evaluate_task_completion_fact import synthetic_completed
from scripts.ru_observation import object_hash


@pytest.fixture(scope="module")
def source() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    projection, snapshots = synthetic_completed()
    wire = runner.history.registered.expected_first(projection, snapshots)["payload"]
    return projection, snapshots, wire


@pytest.fixture
def plan(source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    projection, snapshots, original = source
    payload, view, contract = candidate.build_payload(original, source_snapshots=snapshots)
    cases = []
    for trial in (1, 2):
        for group in runner.history.GROUPS:
            cases.append(
                {
                    "case_id": f"{group}-ALIAS_OMITTED-T{trial}",
                    "group": group,
                    "trial": trial,
                    "arm": runner.ARM,
                    "original_payload": deepcopy(original),
                    "snapshots": deepcopy(snapshots),
                    "original_prompt_input": deepcopy(projection),
                    "prompt_input": deepcopy(view),
                    "evaluation_input_contract": deepcopy(contract),
                    "candidate_payload": deepcopy(payload),
                    "candidate_input_sha256": object_hash(view),
                    "candidate_transport_sha256": runner.ordered.transport_hash(payload),
                    "candidate_property_orders": runner.ordered.property_orders(payload),
                }
            )
    return {
        "model": {"model_id": "qwen3.5:9b"},
        "cases": cases,
        "historical_references": [],
        "scope": "SYNTHETIC_WIRE_TEST_ONLY",
    }


def test_project_acquisition_aliases__exact_owner_copy__omits_only_copy_and_preserves_original(
    source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    original = deepcopy(source[0])
    before = deepcopy(original)
    view, omitted = candidate.project_acquisition_aliases(original)
    assert original == before and len(omitted) == 1
    expected = deepcopy(original)
    expected["request_intent"]["constraints"].pop(omitted[0]["index"])
    assert view == expected
    assert (
        view["request_intent"]["resource_responsibilities"]
        == (original["request_intent"]["resource_responsibilities"])
    )
    candidate.validate_projection(view, original_input=original)


@pytest.mark.parametrize("difference", ["value", "provenance", "work_binding"])
def test_project_acquisition_aliases__nonidentical_condition__preserves_its_authority(
    source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    difference: str,
) -> None:
    original = deepcopy(source[0])
    intent = original["request_intent"]
    extra = deepcopy(intent["constraints"][-1])
    if difference == "value":
        extra["value"] = ["notes"]
    elif difference == "provenance":
        intent["resource_responsibilities"]["source_reads"][0]["required_information"].append(
            "상태"
        )
        intent["constraints"][-1]["value"].append("상태")
        extra["value"] = "상태"
        offset = original["user_request"].index("상태")
        extra["provenance"] = {
            "source": "USER_REQUEST",
            "start_offset": offset,
            "end_offset": offset + 2,
        }
    else:
        first_request = original["user_request"]
        second_request = " 별도 메모도 확인해줘."
        original["user_request"] += second_request
        intent["goal"] = original["user_request"]
        intent["requested_work"]["work_units"].append(
            {
                "unit_id": "work-2",
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": len(first_request),
                        "end_offset": len(original["user_request"]),
                        "source_text": second_request,
                    }
                ],
            }
        )
        extra["work_unit_ids"] = ["work-2"]
    intent["constraints"].append(extra)
    view, omitted = candidate.project_acquisition_aliases(original)
    assert len(omitted) == 1
    assert extra in view["request_intent"]["constraints"]
    assert all(item["constraint"] != extra for item in omitted)


def test_project_acquisition_aliases__invalid_original__rejects_before_omission(
    source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    original = deepcopy(source[0])
    original["request_intent"]["constraints"][-1]["work_unit_ids"] = ["foreign"]
    with pytest.raises(ValueError):
        candidate.project_acquisition_aliases(original)


@pytest.mark.parametrize("field", ["user_request", "goal", "source", "outline", "evidence"])
def test_validate_projection__unrelated_change__rejects_without_recreating_meaning(
    source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    field: str,
) -> None:
    original = source[0]
    view, _ = candidate.project_acquisition_aliases(original)
    if field == "user_request":
        view[field] += "변조"
    elif field == "goal":
        view["request_intent"][field] += "변조"
    elif field == "source":
        view["request_intent"]["resource_responsibilities"]["source_reads"] = []
    elif field == "outline":
        view["answer_outline"]["evidence_refs"] = []
    else:
        view["evidence"] = []
    with pytest.raises(ValueError, match="more than exact"):
        candidate.validate_projection(view, original_input=original)


def test_build_payload__both_input_copies__preserves_registered_metadata_role_and_format(
    source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    projection, snapshots, wire = source
    before = deepcopy(wire)
    result, view, contract = candidate.build_payload(wire, source_snapshots=snapshots)
    assert wire == before
    old_body, body = json.loads(wire["prompt"]), json.loads(result["prompt"])
    assert body.pop("input") == view
    old_body.pop("input")
    assert body == old_body
    old_json = json.dumps(projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    new_json = json.dumps(view, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert result["system"] == wire["system"][: -len(old_json + "\n")] + new_json + "\n"
    assert {k: v for k, v in result.items() if k not in {"system", "prompt"}} == {
        k: v for k, v in wire.items() if k not in {"system", "prompt"}
    }
    assert runner.ordered.property_orders(result) == runner.ordered.property_orders(wire)
    assert contract["input_schema_version"] == candidate.INPUT_VERSION
    assert contract["reduced_intent_authority"] == "EVALUATION_VIEW_NOT_PRODUCT_REQUEST_INTENT_V3"


def test_verify_wire_seals__changed_metadata_or_order__rejects(plan: dict[str, Any]) -> None:
    runner.verify_wire_seals(plan)
    props = plan["cases"][0]["candidate_payload"]["format"]["oneOf"][0]["properties"]
    props["mode"] = props.pop("mode")
    with pytest.raises(ValueError):
        runner.verify_wire_seals(plan)


def test_verify_wire_seals__admission_input_changed__rejects(plan: dict[str, Any]) -> None:
    plan["cases"][0]["original_prompt_input"]["user_request"] += "변조"
    with pytest.raises(ValueError, match="admission input"):
        runner.verify_wire_seals(plan)


@pytest.mark.parametrize("failure", [None, "timeout", "wall"])
def test_execute_plan__fake_firsts__preserves_six_calls_and_never_retries(
    plan: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    observed = []
    monkeypatch.setattr(runner.recorder, "RESULTS", tmp_path)
    if failure == "wall":
        monkeypatch.setattr(runner, "WALL_SECONDS", 0)

    def post(**kwargs: Any) -> dict[str, Any]:
        observed.append(runner.ordered.transport_hash(kwargs["payload"]))
        if failure == "timeout":
            raise TimeoutError("synthetic timeout")
        return {
            "model": "qwen3.5:9b",
            "done": True,
            "done_reason": "stop",
            "response": '{"mode":"FACT_REFERENCES","items":[]}',
            "prompt_eval_count": 5,
            "eval_count": 3,
            "total_duration": 1_000_000,
        }

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    kwargs: dict[str, Any] = {
        "plan_sha256": object_hash(plan),
        "reconstruct_plan": lambda: deepcopy(plan),
    }
    raw = runner.execute_plan(plan, tmp_path / "trial", **kwargs)
    count = 0 if failure == "wall" else 1 if failure else 6
    assert raw["actual_http_calls"] == len(observed) == count
    assert observed == [c["candidate_transport_sha256"] for c in plan["cases"][:count]]
    assert raw["completed"] is (failure is None)
    assert raw["semantic_verdict"] == "NOT_REVIEWED"
    assert raw["registered_router_calls"] == raw["graph_calls"] == raw["provider_calls"] == 0
    if failure is None:
        assert all(r["answer_admission"]["structural_result"] == "NO_DRAFT" for r in raw["calls"])
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan, tmp_path / "again", **kwargs)
    assert len(observed) == count
