"""090 single-factor wire and fixed-budget gates; all transports are fake."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_answer_assembly_ablation as runner
from scripts.evaluate_task_completion_fact import synthetic_completed
from scripts.ru_observation import object_hash


@pytest.fixture(scope="module")
def source() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    projection, snapshots = synthetic_completed()
    first = runner.registered.expected_first(projection, snapshots)
    return projection, snapshots, first


@pytest.fixture
def plan(source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    projection, snapshots, first = source
    cases, rows, old_cases = [], [], []
    for trial in (1, 2):
        for group in runner.GROUPS:
            case_id = f"{group}-REGISTERED-T{trial}"
            cases.append(
                {
                    "case_id": case_id,
                    "group": group,
                    "trial": trial,
                    "prompt_input": deepcopy(projection),
                    "snapshots": deepcopy(snapshots),
                    "expected_first": deepcopy(first),
                    "upstream": "SYNTHETIC_TEST_ONLY",
                }
            )
            rows.append(
                {
                    "case_id": case_id,
                    "phase": "FIRST",
                    "state": "RETURNED",
                    "wire_request_count": 1,
                    "provider_response_metadata": {"done": True},
                    "actual_model": "qwen3.5:9b",
                    "payload": deepcopy(first["payload"]),
                    "transport_sha256": first["transport_sha256"],
                    "input": deepcopy(projection),
                    "input_sha256": object_hash(projection),
                }
            )
            old_cases.append(
                {
                    **deepcopy(cases[-1]),
                    "candidate_payload": runner.build_payload(
                        first["payload"], arm=runner.ARMS[1], prior_version="v1"
                    ),
                }
            )
    prepared, historical = runner._cases(
        {"binding": {"cases": cases, "model": {"model_id": "qwen3.5:9b"}}, "calls": rows},
        {"binding": {"cases": old_cases}},
    )
    return {
        "model": {"model_id": "qwen3.5:9b"},
        "cases": prepared,
        "historical_references": historical,
        "scope": "SYNTHETIC_WIRE_TEST_ONLY",
    }


def test_build_payload__context_arm__removes_exact_block_without_other_changes(
    source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    wire = deepcopy(source[2]["payload"])
    before = deepcopy(wire)
    result = runner.build_payload(wire, arm=runner.ARMS[0], prior_version="v1")
    assert wire == before
    prefix, suffix = wire["system"].split(runner._PRODUCT_CONTEXT_INSTRUCTION)
    assert result["system"] == prefix + suffix
    assert "Allowed current-Run input projection (JSON):" in result["system"]
    assert {k: v for k, v in result.items() if k != "system"} == {
        k: v for k, v in wire.items() if k != "system"
    }
    assert json.loads(result["prompt"])["prompt_ref"]["prompt_version"] == (
        "evaluation-answer-choice-connected-v088"
    )
    assert runner.ordered.property_orders(result) == runner.ordered.property_orders(wire)


def test_build_payload__metadata_arm__changes_only_version_without_mutating_original(
    source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    wire = deepcopy(source[2]["payload"])
    before = deepcopy(wire)
    result = runner.build_payload(wire, arm=runner.ARMS[1], prior_version="v1")
    assert wire == before
    assert result["prompt"] == wire["prompt"].replace(
        '"prompt_version": "evaluation-answer-choice-connected-v088"',
        '"prompt_version": "v1"',
    )
    assert {k: v for k, v in result.items() if k != "prompt"} == {
        k: v for k, v in wire.items() if k != "prompt"
    }


@pytest.mark.parametrize("copies", [0, 2])
def test_build_payload__missing_or_repeated_context__rejects_ambiguous_removal(
    source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    copies: int,
) -> None:
    wire = deepcopy(source[2]["payload"])
    wire["system"] = wire["system"].replace(
        runner._PRODUCT_CONTEXT_INSTRUCTION, runner._PRODUCT_CONTEXT_INSTRUCTION * copies
    )
    with pytest.raises(ValueError, match="exactly one"):
        runner.build_payload(wire, arm=runner.ARMS[0], prior_version="v1")


def test_build_payload__noncanonical_json__rejects_incidental_reserialization(
    source: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    wire = deepcopy(source[2]["payload"])
    wire["prompt"] = json.dumps(json.loads(wire["prompt"]), indent=2)
    with pytest.raises(ValueError, match="serialization"):
        runner.build_payload(wire, arm=runner.ARMS[1], prior_version="v1")


def test_cases__fixed_schedule__has_eight_firsts_and_six_unique_historical_rows(
    plan: dict[str, Any],
) -> None:
    runner.verify_wire_seals(plan)
    assert [c["arm"] for c in plan["cases"]] == [runner.ARMS[0]] * 6 + [runner.ARMS[1]] * 2
    assert len({r["case_id"] for r in plan["historical_references"]}) == 6
    assert plan["cases"][0]["historical_case_id"] == plan["cases"][6]["historical_case_id"]
    assert all(
        c["candidate_payload"]["options"] == {"num_ctx": 16384, "seed": 20260923}
        for c in plan["cases"]
    )


@pytest.mark.parametrize("change", ["order", "options", "schedule", "original"])
def test_verify_wire_seals__undeclared_mutation__rejects_even_equal_schema_values(
    plan: dict[str, Any],
    change: str,
) -> None:
    case = plan["cases"][0]
    if change == "order":
        props = case["candidate_payload"]["format"]["oneOf"][0]["properties"]
        props["mode"] = props.pop("mode")
    elif change == "options":
        case["candidate_payload"]["options"]["temperature"] = 0
        case["candidate_transport_sha256"] = runner.ordered.transport_hash(
            case["candidate_payload"]
        )
    elif change == "schedule":
        plan["cases"].reverse()
    else:
        case["original_payload"]["options"]["temperature"] = 0
    with pytest.raises(ValueError):
        runner.verify_wire_seals(plan)


@pytest.mark.parametrize("failure", [None, "timeout", "wrong_model", "wall"])
def test_execute_plan__fake_transport__preserves_wire_and_stops_without_retry(
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
        assert kwargs["timeout_seconds"] == 180
        if failure == "timeout":
            raise TimeoutError("synthetic timeout")
        return {
            "model": "foreign" if failure == "wrong_model" else "qwen3.5:9b",
            "response": '{"mode":"FACT_REFERENCES","items":[]}',
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 5,
            "eval_count": 3,
            "total_duration": 1_000_000,
            "thinking": "DO_NOT_PERSIST",
        }

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    kwargs: dict[str, Any] = {
        "plan_sha256": object_hash(plan),
        "reconstruct_plan": lambda: deepcopy(plan),
    }
    raw = runner.execute_plan(plan, tmp_path / "trial", **kwargs)
    count = 0 if failure == "wall" else 1 if failure else 8
    assert raw["actual_http_calls"] == len(observed) == count
    assert observed == [c["candidate_transport_sha256"] for c in plan["cases"][:count]]
    assert raw["registered_router_calls"] == raw["graph_calls"] == raw["provider_calls"] == 0
    assert raw["semantic_verdict"] == "NOT_REVIEWED"
    assert raw["binding_unchanged"] is True
    assert raw["completed"] is (failure is None)
    assert "DO_NOT_PERSIST" not in json.dumps(raw)
    if failure is None:
        assert all(r["answer_admission"]["structural_result"] == "NO_DRAFT" for r in raw["calls"])
    elif failure == "wall":
        assert raw["calls"][0]["state"] == "NOT_DISPATCHED"
        assert raw["calls"][0]["wire_request_count"] == 0
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan, tmp_path / "rerun", **kwargs)
    assert len(observed) == count
