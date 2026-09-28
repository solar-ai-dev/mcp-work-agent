"""Rendering-choice recorder gates; only existing fixtures and fake transport."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_answer_rendering_choice as runner


@pytest.fixture
def lookup() -> tuple[dict[str, Any], dict[str, Any]]:
    # This existing fixture uses tests.support.task_calendar_evidence and the
    # actual Planning projection. It does not create a Canonical example.
    return runner.history.synthetic_completed()


def test_summary_control__existing_projection__rebinds_only_request_meaning(
    lookup: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    projection, snapshots = lookup
    projection["collection_results"] = [{"previous_lookup": "not this request"}]
    projection["request_intent"]["constraints"].append(
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": ["previous lookup only"],
            "work_unit_ids": ["work-1"],
        }
    )
    before = deepcopy((projection, snapshots))
    result = runner.summary_control(projection)
    intent = result["request_intent"]
    selected = [
        item
        for item in projection["request_intent"]["constraints"]
        if item["field"] == "selected_resource_id"
    ]
    assert (projection, snapshots) == before
    assert result["evidence"] == projection["evidence"]
    assert (
        result["answer_outline"]["evidence_refs"] == projection["answer_outline"]["evidence_refs"]
    )
    assert result["user_request"] == intent["goal"] == runner.CONTROL_REQUEST
    assert result["answer_outline"]["sections"] == [runner.CONTROL_REQUEST]
    assert "collection_results" not in result
    assert intent["meta"] == {
        "artifact_id": "083-summary-control-intent",
        "revision": 1,
        "based_on": [],
    }
    assert intent["constraints"] == selected + [
        {
            "kind": "USER_REQUIREMENT",
            "field": "required_information",
            "value": ["notes"],
            "work_unit_ids": ["work-1"],
        }
    ]
    assert intent["resource_responsibilities"] == {
        "source_reads": [
            {
                "resource_type": "TASK",
                "required_information": ["notes"],
                "target_scope": "SINGULAR",
                "work_unit_ids": ["work-1"],
            }
        ],
        "outputs": [],
    }
    assert intent["requested_work"] == {
        "work_units": [
            {
                "unit_id": "work-1",
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "start_offset": 0,
                        "end_offset": len(runner.CONTROL_REQUEST),
                        "source_text": runner.CONTROL_REQUEST,
                    }
                ],
            }
        ],
        "work_relations": [],
    }
    assert (
        runner.history.handoff.validate_intent(
            intent,
            require_meta=True,
            provenance_sources={"USER_REQUEST": runner.CONTROL_REQUEST},
        )
        == intent
    )
    # Both branches remain available even for this non-lookup request. The
    # schema/validator must not make the semantic choice on the model's behalf.
    schema: Any = runner.candidate.bind_answer_rendering_choice_schema(
        result, source_snapshots=snapshots
    )
    assert {branch["properties"]["mode"]["const"] for branch in schema["oneOf"]} == {
        "FACT_REFERENCES",
        "PROSE",
    }


def test_choice_wire__same_input_and_runtime__changes_only_inactive_output_contract(
    lookup: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    projection, snapshots = lookup
    original = runner.history.handoff._wire_projection(projection)["wire_payload"]
    before = deepcopy((original, projection, snapshots))
    payload = runner.choice_wire(original, projection, snapshots)
    body, baseline = json.loads(payload["prompt"]), json.loads(original["prompt"])
    assert (original, projection, snapshots) == before
    assert body["input"] == baseline["input"] == projection
    assert "source_snapshots" not in body["input"]
    assert "evaluation_gold" not in body["input"]
    assert body["output_schema"] == payload["format"]
    assert body["prompt_ref"]["prompt_id"] == "evaluation.planning.choose_answer_rendering"
    assert baseline["prompt_ref"]["prompt_id"] == "planning.compose_answer"
    assert "mode" not in baseline["output_schema"]["properties"]
    assert baseline["output_schema"] == original["format"]
    for key, value in original.items():
        if key not in {"system", "prompt", "format"}:
            assert payload[key] == value
    for branch in body["output_schema"]["oneOf"]:
        assert branch["additionalProperties"] is False
    prose = next(
        branch
        for branch in body["output_schema"]["oneOf"]
        if branch["properties"]["mode"]["const"] == "PROSE"
    )
    prose_without_mode = deepcopy(prose)
    prose_without_mode["properties"].pop("mode")
    prose_without_mode["required"].remove("mode")
    assert prose_without_mode == baseline["output_schema"]


def test_choice_wire__changed_request__rejects_before_dispatch(
    lookup: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    projection, snapshots = lookup
    original = runner.history.handoff._wire_projection(projection)["wire_payload"]
    changed = deepcopy(projection)
    changed["user_request"] = "different request"
    with pytest.raises(ValueError, match="input differs"):
        runner.choice_wire(original, changed, snapshots)


@pytest.mark.parametrize("mode", ["FACT_REFERENCES", "PROSE"])
def test_admission__valid_choice__retains_mode_without_awarding_semantic_success(
    lookup: tuple[dict[str, Any], dict[str, Any]],
    mode: str,
) -> None:
    projection, snapshots = lookup
    control = runner.summary_control(projection)
    ref = control["answer_outline"]["evidence_refs"][0]
    value = (
        {"mode": mode, "items": [{"evidence_ref": ref, "field": "notes"}]}
        if mode == "FACT_REFERENCES"
        else {
            "mode": mode,
            "schema_version": 2,
            "answer": "- 장비 수령 여부 확인",
            "evidence_refs": [ref],
        }
    )
    row: dict[str, Any] = {"content": json.dumps(value, ensure_ascii=False)}
    original = deepcopy(row)
    runner.record_admission(
        row,
        {
            "arm": "CHOICE",
            "prompt_input": control,
            "snapshots": snapshots,
        },
    )
    assert row["content"] == original["content"]
    admission = row["answer_admission"]
    assert admission["mode"] == mode
    assert admission["validation"]["structural_result"] == "VALID"
    assert admission["semantic_verdict"] == "NOT_REVIEWED"
    assert admission["validation"]["semantic_verdict"] == "UNREVIEWED"
    if mode == "FACT_REFERENCES":
        # Literal quotation conflicts with this control's wording. That is a
        # semantic failure to review, not a reason to fabricate a prose answer.
        assert "메모(원문):" in admission["draft"]["answer"]
        assert "> " in admission["draft"]["answer"]
    else:
        assert admission["draft"]["answer"] == value["answer"]


@pytest.fixture
def sealed(
    lookup: tuple[dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    projection, snapshots = lookup
    wire = runner.history.handoff._wire_projection(projection)["wire_payload"]
    base_case = {
        "prompt_input": deepcopy(projection),
        "snapshots": deepcopy(snapshots),
        "original_wire_sha256": runner.object_hash(wire),
    }
    cases = [deepcopy(base_case) for _ in range(4)]
    model = {"model_id": runner.history.handoff.MODEL_ID, "model_digest": "test-digest"}
    prior = {
        "completed": True,
        "binding_unchanged": True,
        "binding": {"model": model, "cases": deepcopy(cases)},
        "calls": [],
    }
    base = {
        "cases": cases,
        "source_hashes": {},
        "historical_references": [],
        "historical_case_binding": {"fixture": "synthetic test only"},
    }
    monkeypatch.setattr(runner.existing, "file_hash", lambda _: runner.PRIOR_HASH)
    monkeypatch.setattr(runner.history, "read_json", lambda _: deepcopy(prior))
    monkeypatch.setattr(runner.selection, "make_plan", lambda _: deepcopy(base))
    monkeypatch.setattr(runner, "head", lambda: "test-head")
    return runner.make_plan(model)


def test_plan__fixed_eight_firsts__preserves_control_pair_and_original_baseline(
    sealed: dict[str, Any],
) -> None:
    assert [case["case_id"] for case in sealed["cases"]] == [
        f"{group}-{arm}-T{trial}"
        for trial in (1, 2)
        for group, arm in (
            ("CORE005_LOOKUP", "CHOICE"),
            ("SYNTHETIC_COMPLETED", "CHOICE"),
            ("SYNTHETIC_REFORMULATION", "BASELINE"),
            ("SYNTHETIC_REFORMULATION", "CHOICE"),
        )
    ]
    assert sealed["policy"]["new_calls"] == 8
    assert sealed["policy"]["repair"] == sealed["policy"]["retry"] == 0
    assert sealed["semantic_verdict"] == "NOT_REVIEWED"
    assert sealed["business_success"] == "NOT_EVALUATED"
    for offset in (0, 4):
        baseline, choice = sealed["cases"][offset + 2 : offset + 4]
        assert baseline["prompt_input"] == choice["prompt_input"]
        assert baseline["snapshots"] == choice["snapshots"]
        assert baseline["candidate_input_sha256"] == choice["candidate_input_sha256"]
        original = runner.history.handoff._wire_projection(baseline["prompt_input"])
        assert baseline["candidate_payload"] == original["wire_payload"]
        for key in ("options", "think", "model", "stream"):
            assert baseline["candidate_payload"][key] == choice["candidate_payload"][key]
    for case in sealed["cases"]:
        assert runner.object_hash(case["candidate_payload"]) == case["candidate_wire_sha256"]
        assert runner.object_hash(case["prompt_input"]) == case["candidate_input_sha256"]


@pytest.mark.parametrize("kind", ["empty", "foreign_reference", "free_value"])
def test_recording__invalid_or_empty_selection__does_not_fallback_or_repeat(
    sealed: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    observed: list[dict[str, Any]] = []
    monkeypatch.setattr(runner.recorder, "RESULTS", tmp_path)

    def post(**kwargs: Any) -> dict[str, Any]:
        payload = kwargs["payload"]
        observed.append(deepcopy(payload))
        body = json.loads(payload["prompt"])
        assert kwargs["path"] == "/api/generate"
        assert kwargs["timeout_seconds"] == 180
        if body["prompt_ref"]["prompt_id"] == "planning.compose_answer":
            value = {
                "schema_version": 2,
                "answer": "확인할 항목을 안내합니다.",
                "evidence_refs": body["input"]["answer_outline"]["evidence_refs"],
            }
        else:
            selection: list[dict[str, str]] = []
            if kind != "empty":
                selection = [{"evidence_ref": "foreign", "field": "notes"}]
                if kind == "free_value":
                    selection[0].update(
                        evidence_ref=body["input"]["answer_outline"]["evidence_refs"][0],
                        value="invented text",
                    )
            value = {"mode": "FACT_REFERENCES", "items": selection}
        return {
            "model": sealed["model"]["model_id"],
            "response": json.dumps(value, ensure_ascii=False),
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 5,
            "eval_count": 3,
            "total_duration": 1_000_000,
            "thinking": "DO_NOT_STORE_HIDDEN_CONTENT",
        }

    monkeypatch.setattr(runner.recorder.existing.transport, "_post_json", post)
    digest = runner.object_hash(sealed)
    kwargs: dict[str, Any] = {
        "plan_sha256": digest,
        "reconstruct_plan": lambda: deepcopy(sealed),
        "claim_directory": ".rendering-choice-test-trials",
        "reference_results": [],
        "reference_metric": "historical",
        "stop_after_response": runner.record_admission,
    }
    raw = runner.recorder.execute_registered_plan(sealed, tmp_path / "first", **kwargs)
    assert raw["actual_http_calls"] == len(observed) == 8
    assert observed == [case["candidate_payload"] for case in sealed["cases"]]
    assert raw["completed"] is raw["binding_unchanged"] is True
    assert raw["provider_calls"] == raw["graph_calls"] == 0
    assert raw["semantic_verdict"] == "NOT_REVIEWED"
    assert "DO_NOT_STORE_HIDDEN_CONTENT" not in json.dumps(raw)
    for row, case in zip(raw["calls"], sealed["cases"], strict=True):
        assert row["stage"] == "FIRST" and row["wire_request_count"] == 1
        assert row["answer_admission"]["semantic_verdict"] == "NOT_REVIEWED"
        if case["arm"] == "BASELINE":
            assert row["answer_admission"]["mode"] == "BASELINE_PROSE"
            assert row["answer_admission"]["validation"]["structural_result"] == "VALID"
        else:
            assert row["answer_admission"]["structural_result"] == (
                "NO_DRAFT" if kind == "empty" else "INVALID"
            )
            assert "draft" not in row["answer_admission"]
            assert json.loads(row["content"])["mode"] == "FACT_REFERENCES"
    with pytest.raises(FileExistsError):
        runner.recorder.execute_registered_plan(sealed, tmp_path / "repeat", **kwargs)
    assert len(observed) == 8
