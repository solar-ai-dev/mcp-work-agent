"""Budget/sealing checks with fake HTTP only; no model or Provider execution."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_read_answer_handoff as diagnostic


def _model() -> dict[str, Any]:
    version = {"version": "test-only"}
    return {
        "model_id": diagnostic.MODEL_ID,
        "model_digest": "test-only-digest",
        "ollama_version_response": version,
        "ollama_version_sha256": diagnostic.object_hash(version),
    }


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, dict[str, Any]]:
    monkeypatch.setattr(diagnostic, "RESULTS", tmp_path)
    monkeypatch.setattr(diagnostic, "inspect_diagnostic_model", lambda _: _model())
    monkeypatch.setattr(diagnostic, "head", lambda: "test-sha")
    monkeypatch.setattr(diagnostic, "_bound_files", lambda: {"source.py": "test-hash"})
    plan = diagnostic.make_plan(_model())
    path = tmp_path / "trial" / "plan.json"
    diagnostic.write_json(path, plan, exclusive=True)
    return path, diagnostic.file_hash(path), plan


def test_preparation__seals_only_two_firsts_and_a_zero_call_control(
    sealed: tuple[Path, str, dict[str, Any]],
) -> None:
    _, _, plan = sealed
    assert [case["case_id"] for case in plan["cases"]] == list(diagnostic.CASE_IDS)
    assert [case["dispatch_limit"] for case in plan["cases"]] == [0, 1, 1]
    assert plan["cases"][0]["first"] is None
    assert "오전 10시부터 오전 11시까지" in plan["cases"][0]["prepared"]["compose_result"]["answer"]
    for case in plan["cases"][1:]:
        first = case["first"]
        assert "source_snapshots" not in first["input"]
        assert "evaluation_gold" not in first["input"]
        wire = first["wire_payload"]
        assert wire["think"] is False
        assert wire["options"] == {"num_ctx": 16384, "seed": diagnostic.SEED}
        assert diagnostic.object_hash(wire) == first["wire_sha256"]
        assert case["prepared"]["pipeline_input_unchanged"] is True


@pytest.mark.parametrize(
    "response_kind", ["valid", "invalid_json", "invalid_schema", "timeout", "prose_repair"]
)
def test_execution__preserves_first_and_enforces_fixed_dispatch_count(
    sealed: tuple[Path, str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    response_kind: str,
) -> None:
    path, digest, _ = sealed
    calls: list[dict[str, Any]] = []

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(deepcopy(kwargs))
        assert kwargs["path"] == "/api/generate"
        assert kwargs["endpoint"] == diagnostic.OLLAMA_FIXED_LOOPBACK_ENDPOINT
        raw = json.loads((path.parent / "raw.json").read_text(encoding="utf-8"))
        assert raw["model_calls"] == len(calls)
        assert raw["cases"][-1]["calls"][0]["state"] == "DISPATCHING"
        if response_kind == "timeout":
            raise TimeoutError("test timeout")
        prompt_input = json.loads(kwargs["payload"]["prompt"])["input"]
        content = {
            "schema_version": 2,
            "answer": "확인한 자료를 전달합니다.",
            "evidence_refs": prompt_input["answer_outline"]["evidence_refs"],
        }
        if response_kind == "prose_repair":
            content["answer"] = '{"unexpected": "not user prose"}'
        response = (
            "not-json"
            if response_kind == "invalid_json"
            else "{}"
            if response_kind == "invalid_schema"
            else json.dumps(content, ensure_ascii=False)
        )
        return {
            "response": response,
            "model": diagnostic.MODEL_ID,
            "prompt_eval_count": 12,
            "eval_count": 8,
            "total_duration": 10_000_000,
            "done": True,
        }

    monkeypatch.setattr(diagnostic.transport, "_post_json", post)
    raw = diagnostic.execute_plan(path, digest)
    assert len(calls) == raw["model_calls"] == 2
    assert raw["cases"][0]["state"] == "RETURNED"
    assert raw["cases"][0]["calls"] == []
    for row in raw["cases"][1:]:
        assert len(row["calls"]) == 1
        assert row["state"] == ("RETURNED" if response_kind == "valid" else "FAILED")
        assert row["pipeline_input_unchanged"] is True
        assert row["semantic_review"] == "UNREVIEWED"
        if response_kind != "timeout":
            assert "provider_response" in row["calls"][0]
        if response_kind == "prose_repair":
            assert row["blocked_followup"]["dispatched"] is False
            assert row["failure"]["type"] == "FirstOnlyBoundReached"
    with pytest.raises(FileExistsError):
        diagnostic.execute_plan(path, digest)
    assert len(calls) == 2


@pytest.mark.parametrize("drift", ["hash", "head", "source"])
def test_execute__drift_rejected_before_dispatch(
    sealed: tuple[Path, str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    path, digest, _ = sealed
    if drift == "head":
        monkeypatch.setattr(diagnostic, "head", lambda: "different-sha")
    elif drift == "source":
        monkeypatch.setattr(diagnostic, "_bound_files", lambda: {"source.py": "different-hash"})
    else:
        digest = "wrong-hash"

    def no_dispatch(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("must not generate for a changed plan")

    monkeypatch.setattr(diagnostic.transport, "_post_json", no_dispatch)
    with pytest.raises(ValueError):
        diagnostic.execute_plan(path, digest)
    assert not (path.parent / "raw.json").exists()
