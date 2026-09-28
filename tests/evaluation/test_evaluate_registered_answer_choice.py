"""088 runner guard/observation tests; no hardware probe or model/Provider I/O."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import evaluate_registered_answer_choice as runner


def test_validate_plan__stored_http_property_order_changes__rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload: dict[str, Any] = {"format": {"properties": {"mode": {}, "answer": {}}}}
    original: dict[str, Any] = {
        "model": {},
        "cases": [
            {
                "expected_first": {
                    "payload": payload,
                    "transport_sha256": runner.transport_hash(payload),
                }
            }
        ],
    }
    monkeypatch.setattr(runner, "make_plan", lambda _model: deepcopy(original))
    changed = deepcopy(original)
    changed["cases"][0]["expected_first"]["payload"]["format"]["properties"] = {
        "answer": {},
        "mode": {},
    }
    assert changed == original  # Python mapping equality cannot protect wire ordering.
    with pytest.raises(ValueError, match="byte/order"):
        runner.validate_plan(changed)


def test_boundary_observations__failed_read_and_denied_write__preserves_attempts() -> None:
    boundary = SimpleNamespace(
        events=[
            {"boundary": "local_hardware_probe"},
            {"boundary": "snapshot_read"},
            {"boundary": "provider_write_dispatch", "decision": "DENY"},
        ],
        read_results=[{"tool_id": "tasks_get_task", "error_type": "TimeoutError"}],
    )
    result = runner._boundary_observations(boundary)
    assert result["counts"] == {
        "snapshot_read_attempts": 1,
        "snapshot_read_returned": 0,
        "provider_write_attempts_denied": 1,
        "all_boundary_denials": 1,
    }
    boundary.events.clear()
    assert len(result["events"]) == 3
    assert result["read_results"][0]["error_type"] == "TimeoutError"


def test_boundary_observations__runtime_never_exposed_boundary__does_not_claim_zero() -> None:
    result = runner._boundary_observations(None)
    assert result["observed"] is False
    assert result["counts"] is None


def test_observation_guard__four_attempts_recorded__rejects_fifth_before_leaf() -> None:
    owner = runner._Observation({}, started=runner.time.monotonic(), save=lambda: None, fake=True)
    owner.calls = [{} for _ in range(4)]
    with pytest.raises(RuntimeError, match="DISPATCH_CAP"):
        owner._guard()


def test_wire_observer__transport_raises__preserves_started_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"model": runner.MODEL_ID, "prompt": "unused fake diagnostic payload"}
    case = {"expected_first": {"transport_sha256": runner.transport_hash(payload)}}
    writes: list[dict[str, Any] | None] = []
    owner: runner._Observation = runner._Observation(
        case,
        started=runner.time.monotonic(),
        save=lambda: writes.append(deepcopy(owner.active)),
        fake=False,
    )
    event: dict[str, Any] = {"phase": "FIRST", "wire_request_count": 0}
    owner.active = event

    def fail(**_kwargs: Any) -> Any:
        raise TimeoutError("synthetic transport failure")

    monkeypatch.setattr(runner.transport, "_post_json", fail)
    with owner.wire(), pytest.raises(TimeoutError, match="synthetic"):
        runner.transport._post_json(
            endpoint="http://127.0.0.1:11434",
            path="/api/generate",
            payload=payload,
            timeout_seconds=180,
        )
    assert len(writes) == 1
    assert event["wire_request_count"] == 1
    assert event["payload"] == payload
    assert "provider_response_metadata" not in event


def test_fake_wire__prose_shape__keeps_version_and_reports_no_usage() -> None:
    payload = {"model": runner.MODEL_ID, "prompt": "unused fake diagnostic payload"}
    owner = runner._Observation(
        {
            "expected_first": {"transport_sha256": runner.transport_hash(payload)},
            "prompt_input": {"answer_outline": {"evidence_refs": ["evidence-1"]}},
        },
        started=runner.time.monotonic(),
        save=lambda: None,
        fake=True,
    )
    owner.active = {
        "phase": "FIRST",
        "wire_request_count": 0,
        "prompt_ref": {"prompt_id": runner.EVALUATION_SLOT},
    }
    with owner.wire():
        response = runner.transport._post_json(
            endpoint="http://127.0.0.1:11434",
            path="/api/generate",
            payload=payload,
            timeout_seconds=180,
        )
    assert runner.json.loads(str(response["response"])) == {
        "mode": "PROSE",
        "schema_version": 2,
        "answer": "모델 없는 연결 검증용 응답입니다.",
        "evidence_refs": ["evidence-1"],
    }
    assert "prompt_eval_count" not in response
    assert owner.active["provider_response_metadata"]["done_reason"] == "stop"
