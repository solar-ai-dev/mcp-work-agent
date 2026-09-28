"""095 synthetic direct gates; no historical files, model or Provider execution."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from scripts import evaluate_task_status_presentation as runner
from scripts.ru_observation import object_hash
from scripts.task_field_scope_diagnostic import build_cases

from google_work_agent.application.agents.retrieval.project_task_calendar_source_snapshots import (
    task_calendar_source_snapshot,
)


@pytest.fixture(scope="module")
def sources() -> list[dict[str, Any]]:
    return build_cases()


def _rebind(source: dict[str, Any], fields: dict[str, Any]) -> None:
    item = source["prompt_input"]["evidence"][0]
    ref = runner.registered._ref(item)
    previous = source["snapshots"][ref]
    observed = task_calendar_source_snapshot(
        {
            "resource_type": "task",
            "resource_handle": item["resource_handle"],
            "parent_id": previous["parent_id"],
            "version": previous["provider_version"],
            "payload": fields,
        },
        max_snapshot_chars=4000,
    )
    assert observed is not None
    source["snapshots"][ref] = observed["snapshot"]
    item["locator"]["source_version_ref"] = observed["source_version_ref"]
    item["excerpt"] = "\n".join(f"{key}: {value}" for key, value in fields.items())


def _wire(source: dict[str, Any]) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        runner.registered.expected_first(
            source["prompt_input"],
            source["snapshots"],
            planning_mode=runner.registered.PRODUCT_TASK_FIELD_SCOPE,
        )["payload"],
    )


@pytest.fixture
def plan(sources: list[dict[str, Any]]) -> dict[str, Any]:
    cases = []
    for source in sources:
        original = _wire(source)
        payload = runner.build_payload(original, source_snapshots=source["snapshots"])
        cases.append(
            {
                "case_id": source["case_id"],
                "group": source["group"],
                "trial": 1,
                "arm": runner.ARM,
                "original_payload": original,
                "candidate_payload": payload,
                "prompt_input": deepcopy(source["prompt_input"]),
                "snapshots": deepcopy(source["snapshots"]),
                "historical_transport_sha256": runner.registered.transport_hash(original),
                "candidate_transport_sha256": runner.registered.transport_hash(payload),
                "candidate_input_sha256": object_hash(json.loads(payload["prompt"])["input"]),
            }
        )
    return {
        "cases": cases,
        "model": {"model_id": "qwen3.5:9b"},
        "historical_references": [],
        "scope": "SYNTHETIC_TEST_ONLY",
    }


def test_build_payload__native_first__changes_only_typed_status_in_both_copies(
    sources: list[dict[str, Any]],
) -> None:
    source = deepcopy(sources[0])
    original = _wire(source)
    before = deepcopy((source, original))
    result = runner.build_payload(original, source_snapshots=source["snapshots"])
    body, old_body = json.loads(result["prompt"]), json.loads(original["prompt"])
    assert body["prompt_ref"] == old_body["prompt_ref"]
    assert body["output_schema"] == old_body["output_schema"] == original["format"]
    expected = deepcopy(old_body["input"])
    expected["evidence"][0]["excerpt"] = "title: 작업 A\nstatus: incomplete\ndue: 2026-10-01"
    assert body["input"] == expected
    compact = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert result["system"].endswith(
        "Allowed current-Run input projection (JSON):\n" + compact + "\n"
    )
    assert {k: v for k, v in result.items() if k not in {"prompt", "system"}} == {
        k: v for k, v in original.items() if k not in {"prompt", "system"}
    }
    assert (source, original) == before


def test_build_payload__completed_only__preserves_exact_transport_without_generation(
    sources: list[dict[str, Any]],
) -> None:
    source = deepcopy(sources[1])
    _rebind(source, {"title": "완료 항목", "status": "completed", "notes": "needsAction 그대로"})
    original = _wire(source)
    result = runner.build_payload(original, source_snapshots=source["snapshots"])
    assert runner.registered.transport_hash(result) == runner.registered.transport_hash(original)


def test_project_status_presentation__enum_words_in_title_and_notes__preserves_literals(
    sources: list[dict[str, Any]],
) -> None:
    source = deepcopy(sources[1])
    _rebind(
        source,
        {
            "title": "needsAction 제목",
            "status": "needsAction",
            "notes": "status: needsAction\nneedsAction은 원문이다.",
        },
    )
    output = runner.project_status_presentation(source["prompt_input"], source["snapshots"])
    assert output["evidence"][0]["excerpt"] == (
        "title: needsAction 제목\nstatus: incomplete\n"
        "notes: status: needsAction\nneedsAction은 원문이다."
    )


@pytest.mark.parametrize(
    "damage",
    [
        "unknown",
        "null",
        "missing",
        "stale",
        "handle",
        "non_task",
        "unapproved",
        "missing_snapshot",
        "extra_snapshot",
        "truncated",
        "extra_body",
        "hidden_notes",
    ],
)
def test_project_status_presentation__invalid_authority_or_serialization__rejects(
    sources: list[dict[str, Any]],
    damage: str,
) -> None:
    source = deepcopy(sources[1])
    projection, snapshots = source["prompt_input"], source["snapshots"]
    item = projection["evidence"][0]
    ref = runner.registered._ref(item)
    if damage in {"unknown", "null", "missing"}:
        fields: dict[str, Any] = {"title": "항목"}
        if damage != "missing":
            fields["status"] = "working" if damage == "unknown" else None
        _rebind(source, fields)
    elif damage == "stale":
        snapshots[ref]["status"] = "completed"
    elif damage == "handle":
        item["resource_handle"] = "task:foreign"
    elif damage == "non_task":
        snapshots[ref]["resource_type"] = "calendar_event"
    elif damage == "unapproved":
        projection["answer_outline"]["evidence_refs"] = []
    elif damage == "missing_snapshot":
        snapshots.clear()
    elif damage == "extra_snapshot":
        snapshots["unapproved"] = deepcopy(snapshots[ref])
    elif damage == "truncated":
        item["excerpt"] = "title: 작업 A"
    elif damage == "extra_body":
        item["excerpt"] += "\nstatus: completed"
    else:
        _rebind(source, {"title": "항목", "status": "needsAction", "notes": "새 노출 금지"})
        item["excerpt"] = "title: 항목\nstatus: needsAction"
    with pytest.raises(ValueError):
        runner.project_status_presentation(projection, snapshots)


@pytest.mark.parametrize("damage", ["system", "body", "schema", "options", "repair"])
def test_build_payload__original_wire_tampered__rejects(
    sources: list[dict[str, Any]],
    damage: str,
) -> None:
    source = sources[1]
    original = _wire(source)
    if damage == "system":
        original["system"] += "changed"
    elif damage == "options":
        original["options"]["temperature"] = 0
    else:
        body = json.loads(original["prompt"])
        if damage == "body":
            body["input"]["evidence"][0]["excerpt"] += "changed"
        elif damage == "schema":
            original["format"] = {}
        else:
            body["input"]["candidate_output"] = {}
        original["prompt"] = json.dumps(body, ensure_ascii=False, sort_keys=True)
    with pytest.raises(ValueError):
        runner.build_payload(original, source_snapshots=source["snapshots"])


@pytest.mark.parametrize("damage", [None, "wrong_run", "wrong_snapshot", "unresolved"])
def test_lineage__historical_store_resolution__requires_same_run_and_snapshot(
    sources: list[dict[str, Any]],
    damage: str | None,
) -> None:
    source = sources[1]
    item = source["prompt_input"]["evidence"][0]
    ref = runner.registered._ref(item)
    observation = {
        "run_id": "original-run",
        "resolution": "RESOLVED",
        "resource_handle": item["resource_handle"],
        "source_version_ref": item["locator"]["source_version_ref"],
        "snapshot_sha256": object_hash(source["snapshots"][ref]),
    }
    trial = {
        "local_run": {"run_id": "original-run"},
        "input_binding_unchanged": True,
        "snapshot_resolutions": [observation],
    }
    if damage == "wrong_run":
        observation["run_id"] = "foreign-run"
    elif damage == "wrong_snapshot":
        observation["snapshot_sha256"] = "foreign-hash"
    elif damage == "unresolved":
        observation["resolution"] = "MISSING"
    if damage:
        with pytest.raises(ValueError):
            runner._lineage(source, trial)
    else:
        assert runner._lineage(source, trial)["run_id"] == "original-run"


@pytest.mark.parametrize(
    "failure", [None, "timeout", "wrong_model", "incomplete", "invalid_json", "invalid_schema"]
)
def test_execute_plan__fake_transport__records_firsts_and_stops_on_failure(
    plan: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(runner.recorder, "RESULTS", tmp_path)

    def post(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["path"] == "/api/generate" and kwargs["timeout_seconds"] == 180
        sent.append(runner.registered.transport_hash(kwargs["payload"]))
        if failure == "timeout":
            raise TimeoutError("synthetic timeout")
        refs = json.loads(kwargs["payload"]["prompt"])["input"]["answer_outline"]["evidence_refs"]
        content = json.dumps(
            {"schema_version": 2, "answer": "합성 테스트 답변", "evidence_refs": refs}
        )
        return {
            "model": "wrong" if failure == "wrong_model" else "qwen3.5:9b",
            "done": failure != "incomplete",
            "done_reason": "stop",
            "response": "not JSON"
            if failure == "invalid_json"
            else "{}"
            if failure == "invalid_schema"
            else content,
            "thinking": "NEVER_PERSIST_HIDDEN_CONTENT",
            "prompt_eval_count": 5,
            "eval_count": 3,
            "total_duration": 1_000_000,
            "load_duration": 0,
        }

    monkeypatch.setattr(runner.existing.transport, "_post_json", post)
    kwargs: dict[str, Any] = {
        "plan_sha256": object_hash(plan),
        "reconstruct_plan": lambda: deepcopy(plan),
    }
    raw = runner.execute_plan(plan, tmp_path / "trial", **kwargs)
    count = 1 if failure else 2
    assert raw["actual_http_calls"] == len(sent) == count
    assert raw["completed"] is (failure is None)
    assert raw["registered_router_calls"] == raw["graph_calls"] == raw["provider_calls"] == 0
    assert "NEVER_PERSIST_HIDDEN_CONTENT" not in json.dumps(raw)
    assert raw["semantic_verdict"] == "NOT_REVIEWED"
    if failure:
        assert raw["calls"][0]["state"] == "ERROR" and len(raw["not_dispatched"]) == 1
    else:
        assert all(row["answer_admission"]["validation"] == "VALID" for row in raw["calls"])
    with pytest.raises(FileExistsError):
        runner.execute_plan(plan, tmp_path / "again", **kwargs)
    assert len(sent) == count


@pytest.mark.parametrize("damage", ["input", "schema_order", "extra_call"])
def test_verify_wire_seals__undeclared_change__rejects(plan: dict[str, Any], damage: str) -> None:
    if damage == "input":
        plan["cases"][0]["prompt_input"]["coverage"] = "PARTIAL"
    elif damage == "schema_order":
        props = plan["cases"][0]["candidate_payload"]["format"]["properties"]
        props["schema_version"] = props.pop("schema_version")
    else:
        plan["cases"].append(deepcopy(plan["cases"][0]))
    with pytest.raises(ValueError):
        runner.verify_wire_seals(plan)
