"""Diagnostic sealing and single-FIRST bounds; fake HTTP, no model or Provider."""

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_query_ref_postfix as diagnostic
from tests.unit.application.agents.retrieval.test_plan_query_detail_ref_binding import (
    _context,
    _detail,
)

from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition


def _model() -> dict[str, Any]:
    version = {"version": "0.34.0"}
    return {
        "model_id": diagnostic.MODEL_ID,
        "model_digest": "test-digest",
        "ollama_version_response": version,
        "ollama_version_sha256": diagnostic.object_hash(version),
    }


def _authority() -> dict[str, Any]:
    """Synthetic typed test inputs, not substitutes for the historical loader."""
    context = _context(selected=True)
    context.update(
        requested_mode="LOCAL_GPU",
        retry_budget=build_default_run_budget(started_at_ms=0),
        now_ms=0,
        timezone="Asia/Seoul",
    )
    authority = {
        "context": context,
        "lineage": {"test_only": True},
        "source_plan": {"model": {"id": diagnostic.MODEL_ID, "digest": "test-digest"}},
    }
    captured: dict[str, Any] = {}

    class Capture:
        def infer(self, mode: Any, ref: Any, value: Any, schema: Any) -> Any:
            captured.update(input=deepcopy(value), prompt_ref=asdict(ref), schema=schema)
            raise diagnostic._CapturedFirst

    with pytest.raises(diagnostic._CapturedFirst):
        diagnostic._pipeline(Capture(), authority)
    old = deepcopy(captured["schema"].json_schema)
    for branch in old["properties"]["route_queries"]["items"]["oneOf"]:
        if branch["properties"]["operation"].get("const") == "DETAIL_FETCH":
            branch["properties"]["detail_candidate_ref"] = {"type": "string", "minLength": 1}
    call = {
        "prompt_id": diagnostic.PROMPT_ID,
        "prompt_ref": captured["prompt_ref"],
        "input": captured["input"],
        "output_schema": old,
        "model": diagnostic.MODEL_ID,
        "temperature": None,
        "seed": 20260923,
        "wire_options": {"num_ctx": 16384, "seed": 20260923},
        "wire_think": False,
    }
    call["input_sha256"] = diagnostic.object_hash(call["input"])
    call["wire_sha256"] = diagnostic.wire_projection(
        call, call["input"], OutputSchemaDefinition(captured["schema"].schema_version, old)
    )["wire_sha256"]
    authority["call"] = call
    return authority


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, dict[str, Any]]:
    authority = _authority()
    monkeypatch.setattr(diagnostic, "load_authority", lambda: deepcopy(authority))
    monkeypatch.setattr(diagnostic, "inspect_diagnostic_model", lambda _: _model())
    monkeypatch.setattr(diagnostic, "head", lambda: "test-head")
    monkeypatch.setattr(diagnostic, "_bound_files", lambda: {"source.py": "sealed-hash"})
    monkeypatch.setattr(diagnostic, "RESULTS", tmp_path)
    monkeypatch.setattr(diagnostic, "SOURCE_HASHES", {})
    plan = diagnostic.make_plan(_model())
    path = tmp_path / "trial" / "plan.json"
    diagnostic.write_json(path, plan, exclusive=True)
    return path, diagnostic.file_hash(path), plan


def test_preparation__same_original_input_prompt_and_options_schema_fix_only(
    sealed: tuple[Path, str, dict[str, Any]],
) -> None:
    _, _, plan = sealed
    original, current = plan["historical_first"], plan["first"]
    assert current["input"] == original["input"]
    assert current["prompt_ref"] == original["prompt_ref"]
    assert current["wire_payload"]["options"] == original["wire_options"]
    assert plan["policy"]["max_model_calls"] == 1
    assert plan["policy"]["repair"] == plan["policy"]["retry"] == 0
    details = [
        b
        for b in current["schema"]["properties"]["route_queries"]["items"]["oneOf"]
        if b["properties"]["operation"].get("const") == "DETAIL_FETCH"
    ]
    assert details[0]["properties"]["detail_candidate_ref"] == {
        "type": "string",
        "enum": ["task:selected"],
    }


@pytest.mark.parametrize(
    "fault", ["valid", "native_id", "invalid_json", "duplicate_route", "timeout", "wrong_model"]
)
def test_execution__records_first_before_consumption_and_never_dispatches_revision(
    sealed: tuple[Path, str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    path, digest, _ = sealed
    calls: list[dict[str, Any]] = []

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(deepcopy(kwargs))
        assert kwargs["path"] == "/api/generate"
        assert kwargs["timeout_seconds"] == 180
        stored = diagnostic._read(path.parent / "raw.json")
        assert stored["state"] == "DISPATCHING" and stored["model_calls"] == 1
        if fault == "timeout":
            raise TimeoutError("fixed test timeout")
        result = _detail("selected" if fault == "native_id" else "task:selected")
        if fault == "duplicate_route":
            result["route_queries"].append(deepcopy(result["route_queries"][0]))
        return {
            "model": "other" if fault == "wrong_model" else diagnostic.MODEL_ID,
            "response": "not-json" if fault == "invalid_json" else json.dumps(result),
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 5,
            "total_duration": 2_000_000,
            "thinking": "must never be persisted",
        }

    monkeypatch.setattr(diagnostic.transport, "_post_json", post)
    raw = diagnostic.execute_plan(path, digest)
    assert len(calls) == raw["model_calls"] == 1
    assert raw["provider_calls"] == 0 and raw["semantic_review"] == "UNREVIEWED"
    assert "must never be persisted" not in (path.parent / "raw.json").read_text(encoding="utf-8")
    if fault == "valid":
        assert raw["state"] == "RETURNED"
        assert raw["normalized_first"]["schema_version"] == 2
        assert raw["first_output"]["schema_version"] == 3
        assert (
            raw["consumer_result"]["query_plan"]["route_queries"][0]["detail_candidate_ref"]
            == "task:selected"
        )
        assert (
            raw["consumer_result"]["source_fetch_plans"][0]["detail_candidate_ref"]
            == "task:selected"
        )
    elif fault == "duplicate_route":
        assert raw["state"] == "BOUND_REACHED"
        assert raw["blocked_followup"]["dispatched"] is False
        assert "candidate_output" in raw["blocked_followup"]["input"]
        assert raw["blocked_followup"]["input"]["candidate_output"] == raw["first_output"]
        assert raw["normalized_first"]["schema_version"] == 2
        assert raw["structural_validation"] == "VALID"
    else:
        assert raw["state"] == "FAILED"
    if fault == "native_id":
        assert raw["structural_validation"] == "INVALID_SCHEMA"
        assert raw["first_output"]["route_queries"][0]["detail_candidate_ref"] == "selected"
    with pytest.raises(FileExistsError):
        diagnostic.execute_plan(path, digest)
    assert len(calls) == 1


def test_claim__same_plan_cannot_be_copied_to_a_new_directory(
    sealed: tuple[Path, str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, digest, plan = sealed
    claim = diagnostic.RESULTS / ".query-ref-postfix-trials" / f"{digest}.json"
    diagnostic.write_json(claim, {"already_attempted": True}, exclusive=True)
    other = diagnostic.RESULTS / "copied" / "plan.json"
    diagnostic.write_json(other, plan, exclusive=True)
    monkeypatch.setattr(
        diagnostic.transport, "_post_json", lambda **_: pytest.fail("generation forbidden")
    )
    with pytest.raises(FileExistsError):
        diagnostic.execute_plan(other, diagnostic.file_hash(other))
    assert not (other.parent / "raw.json").exists()


@pytest.mark.parametrize("drift", ["hash", "source", "model", "server_version"])
def test_preflight__drift_fails_before_any_attempt(
    sealed: tuple[Path, str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    path, digest, _ = sealed
    if drift == "source":
        monkeypatch.setattr(diagnostic, "_bound_files", lambda: {"source.py": "changed"})
    elif drift == "model":
        model = _model()
        model["model_digest"] = "different"
        monkeypatch.setattr(diagnostic, "inspect_diagnostic_model", lambda _: model)
    elif drift == "server_version":
        model = _model()
        model["ollama_version_response"] = {"version": "different"}
        model["ollama_version_sha256"] = diagnostic.object_hash(model["ollama_version_response"])
        monkeypatch.setattr(diagnostic, "inspect_diagnostic_model", lambda _: model)
    with pytest.raises(ValueError):
        diagnostic.execute_plan(path, "invalid" if drift == "hash" else digest)
    assert not (path.parent / "attempt.json").exists()


def test_schema_guard__rejects_unrelated_drift(sealed: tuple[Path, str, dict[str, Any]]) -> None:
    plan = sealed[2]
    changed = deepcopy(plan["first"]["schema"])
    changed["properties"]["schema_version"]["enum"] = [99]
    with pytest.raises(ValueError, match="beyond"):
        diagnostic.check_schema_only_change(
            plan["historical_first"]["output_schema"], changed, {"tasks": ["task:selected"]}
        )


def test_loader__changed_historical_bytes_rejected_before_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostic, "file_hash", lambda _: "changed")
    monkeypatch.setattr(
        diagnostic.sqlite3,
        "connect",
        lambda *args, **kwargs: pytest.fail("must not open changed DB"),
    )
    with pytest.raises(ValueError, match="bytes changed"):
        diagnostic.load_authority()
