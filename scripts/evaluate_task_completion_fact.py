"""Three sealed compose FIRSTs for an inactive, snapshot-bound Task fact input."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from scripts import evaluate_output_format_ablation as existing
from scripts import evaluate_read_answer_handoff as handoff
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import metrics, object_hash
from scripts.task_completion_fact_candidate import project_task_completion_facts
from tests.support.task_calendar_evidence import bind_task_calendar_snapshots

from google_work_agent.application.agents.planning.compose_answer import _validate_answer_candidate
from google_work_agent.application.agents.retrieval.normalize_segments import DEFAULT_CONTEXT_BUDGET
from google_work_agent.application.agents.retrieval.project_task_calendar_source_snapshots import (
    task_calendar_source_snapshot,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

ROOT, RESULTS = handoff.ROOT, handoff.RESULTS
PROMPT_ID = handoff.PROMPT_ID
EVALUATION_SLOT = "evaluation.planning.compose_answer_task_completion"
INPUT_VERSION = "evaluation-planning-task-completion-input-v1"
CRITERIA = "evaluation/experiments/068-task-completion-fact-criteria.md"
ORIGINAL = "067-query-ref-postfix-connected-t1"
ORIGINAL_CALLS_HASH = "dd9f77ae841d361d7e61200ed2b9ab4559c815f6a9ea70c338c022d06b4d84d2"
ORIGINAL_RAW_HASH = "d3cc865739d5671d0d0997d79472f9b28c21948041bbaa7968fb7f439db334ca"
LEGACY = "064-core005-goal-output-main-t3"
LEGACY_CALLS_HASH = "148dabca5044d08fa0a25c9e1bd2169b29ce813420c11dcdb740fdc42b8f2b0e"
CELL_IDS = (
    "CORE005_BOUND_CANDIDATE",
    "SYNTHETIC_COMPLETED_BASELINE",
    "SYNTHETIC_COMPLETED_CANDIDATE",
)


def read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def reconstruct_original(call: dict[str, Any]) -> dict[str, Any]:
    """Verify the original FIRST against current Product assembly without HTTP."""
    projection = handoff._wire_projection(call["input"])
    if (
        call["prompt_id"] != PROMPT_ID
        or call["prompt_ref"] != projection["prompt_ref"]
        or call["input_sha256"] != projection["input_sha256"]
        or call["output_schema"] != projection["schema"]
        or call["state"] != "RETURNED"
        or call["wire_request_count"] != 1
        or call["wire_path"] != projection["wire_path"]
        or call["wire_sha256"] != projection["wire_sha256"]
        or call["wire_options"] != projection["wire_payload"]["options"]
        or call["wire_think"] is not False
        or call["model"] != handoff.MODEL_ID
        or call["temperature"] is not None
        or call["seed"] != handoff.SEED
        or call["runtime_policy"]["sampling_temperature"] is not None
        or call["runtime_policy"]["sampling_seed"] != handoff.SEED
        or call["runtime_policy"]["local_timeout_seconds"] != handoff.TIMEOUT_SECONDS
        or any(
            key in call["input"]
            for key in ("base_projection", "candidate_output", "failure_record")
        )
    ):
        raise ValueError("original Product compose FIRST/wire/runtime drift")
    return projection


def snapshots_from_record(raw: dict[str, Any], projection: dict[str, Any]) -> dict[str, Any]:
    """Rebuild only snapshots in this recorded Run, retaining exact Provider fields."""
    run_id = raw["run_id"]
    if raw["snapshot"]["run"]["run_id"] != run_id or raw["persisted_run"]["id"] != run_id:
        raise ValueError("historical Run binding mismatch")
    observations: dict[str, list[dict[str, Any]]] = {}
    for row in raw["read_results"]:
        if row["tool_id"] != "tasks_get_task" or "error_type" in row:
            continue
        item = row["result"]["output"]["item"]
        if (
            item["resource_type"] != "task"
            or item["resource_id"] != row["arguments"]["task_id"]
            or item["parent_id"] != row["arguments"]["task_list_id"]
        ):
            raise ValueError("recorded Task read identity differs")
        handle = f"task:{item['resource_id']}"
        observation = task_calendar_source_snapshot(
            {**item, "resource_handle": handle},
            max_snapshot_chars=DEFAULT_CONTEXT_BUDGET.max_segment_chars,
        )
        if observation is None:
            raise ValueError("recorded Task snapshot is incomplete")
        observations.setdefault(handle, []).append(dict(observation))
    snapshots: dict[str, Any] = {}
    for evidence in projection["evidence"]:
        if not evidence["resource_handle"].startswith("task:"):
            continue
        candidates = observations.get(evidence["resource_handle"], [])
        versions = {item["source_version_ref"] for item in candidates}
        if versions != {evidence.get("locator", {}).get("source_version_ref")}:
            raise ValueError("recorded snapshot and approved Evidence version differ")
        snapshots[evidence["evidence_id"]] = candidates[0]["snapshot"]
    return snapshots


class _EvaluationRegistry:
    """An isolated input contract; the active Product loader stays strict."""

    def __init__(self, product_input: dict[str, Any], snapshots: dict[str, Any]) -> None:
        self.product_registry = PromptRegistry()
        product_ref = self.product_registry.lookup_for_evaluation(PROMPT_ID)
        self.prompt_ref = replace(
            product_ref,
            prompt_bundle_version="evaluation-task-completion-v1",
            prompt_id=EVALUATION_SLOT,
            input_schema_version=INPUT_VERSION,
        )
        self.instruction = self.product_registry.source_text(PROMPT_ID)
        self.expected_input = project_task_completion_facts(
            product_input, source_snapshots=snapshots
        )
        self.input_contract = self

    def lookup_for_evaluation(self, prompt_id: str) -> Any:
        if prompt_id != EVALUATION_SLOT:
            raise LookupError("unregistered evaluation Prompt")
        return self.prompt_ref

    def source_text(self, prompt_id: str) -> str:
        self.lookup_for_evaluation(prompt_id)
        return self.instruction

    def validate_projection(self, prompt_id: str, projection: Mapping[str, object]) -> None:
        self.lookup_for_evaluation(prompt_id)
        base = {key: value for key, value in projection.items() if key != "task_completion_facts"}
        self.product_registry.input_contract.validate_projection(PROMPT_ID, base)
        if dict(projection) != self.expected_input:
            raise ValueError("candidate facts differ from the exact snapshot-bound projection")


def candidate_wire(product_input: dict[str, Any], snapshots: dict[str, Any]) -> dict[str, Any]:
    registry = _EvaluationRegistry(product_input, snapshots)
    projection = registry.expected_input
    if not projection.get("task_completion_facts"):
        raise ValueError("model candidate requires verified Task facts")
    arguments = handoff._call_arguments(product_input)
    arguments.update(
        prompt_ref=registry.prompt_ref,
        prompt_input=projection,
        instruction_text=assemble_prompt(
            registry.prompt_ref,
            projection,
            registry=cast(Any, registry),
            execution_scope=EVALUATION,
        ),
    )
    captured: list[dict[str, Any]] = []

    def capture(**kwargs: Any) -> dict[str, str]:
        captured.append(deepcopy(kwargs))
        return {"response": "{}"}

    with patch.object(handoff.transport, "_post_json", capture):
        handoff.transport.OllamaHTTPClient().invoke_structured(**arguments)
    if len(captured) != 1 or captured[0]["path"] != "/api/generate":
        raise ValueError("one generate FIRST required")
    payload = captured[0]["payload"]
    original = handoff._wire_projection(product_input)
    if payload["options"] != original["wire_payload"]["options"] or payload["think"] is not False:
        raise ValueError("candidate changed runtime options")
    return {
        "prompt_ref": asdict(registry.prompt_ref),
        "input": projection,
        "input_sha256": object_hash(projection),
        "schema": original["schema"],
        "schema_sha256": original["schema_sha256"],
        "wire_path": "/api/generate",
        "wire_payload": payload,
        "wire_sha256": object_hash(payload),
    }


def synthetic_completed() -> tuple[dict[str, Any], dict[str, Any]]:
    case = deepcopy(handoff.fixtures()[2])
    value = case["pipeline_input"]
    request = "선택한 작업의 상태와 메모를 알려줘."
    intent = value["request_intent"]
    value["user_request"] = intent["goal"] = request
    intent["requested_work"]["work_units"][0]["request_provenance"][0].update(
        source_text=request, start_offset=0, end_offset=len(request)
    )
    required = ["completion_status", "notes"]
    intent["resource_responsibilities"]["source_reads"][0]["required_information"] = required
    intent["constraints"] = [
        item for item in intent["constraints"] if item["field"] != "required_information"
    ]
    intent["constraints"].extend(
        handoff.request_goal_candidate_schema.derive_source_information_constraints(
            intent["resource_responsibilities"]
        )
    )
    value["request_intent"] = handoff.validate_intent(
        intent, require_meta=True, provenance_sources={"USER_REQUEST": request}
    )
    fields = {
        "title": "장비 수령 확인",
        "status": "completed",
        "notes": "장비 수령 항목을 확인할 것.",
    }
    value["evidence"][0]["excerpt"] = "\n".join(f"{key}: {text}" for key, text in fields.items())
    value["source_snapshots"] = bind_task_calendar_snapshots(value["evidence"], {"e-task": fields})
    captured: dict[str, Any] = {}

    def capture(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        if prompt_id != PROMPT_ID or captured:
            raise ValueError("synthetic control no longer reaches one compose FIRST")
        captured.update(deepcopy(dict(prompt_input)))
        raise handoff._CapturedFirst

    with suppress(handoff._CapturedFirst):
        handoff._pipeline(case, capture, {})
    if not captured:
        raise ValueError("synthetic semantic control unexpectedly became deterministic")
    return captured, value["source_snapshots"]


def _bound_files() -> dict[str, str]:
    paths = (
        "scripts/evaluate_task_completion_fact.py",
        "scripts/task_completion_fact_candidate.py",
        "tests/evaluation/test_task_completion_fact_diagnostic.py",
        "tests/evaluation/test_task_completion_fact_candidate.py",
        "docs/canonical/05-context-retrieval.md",
        CRITERIA,
    )
    return {**handoff._bound_files(), **{path: existing.file_hash(ROOT / path) for path in paths}}


def load_history(model: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    calls_path, raw_path = RESULTS / ORIGINAL / "calls.json", RESULTS / ORIGINAL / "raw.json"
    legacy_path = RESULTS / LEGACY / "calls.json"
    for path, digest in (
        (calls_path, ORIGINAL_CALLS_HASH),
        (raw_path, ORIGINAL_RAW_HASH),
        (legacy_path, LEGACY_CALLS_HASH),
    ):
        if existing.file_hash(path) != digest:
            raise ValueError("historical raw binding changed")
    raw = read_json(raw_path)
    calls = [row for row in read_json(calls_path)["calls"] if row["prompt_id"] == PROMPT_ID]
    legacy = [row for row in read_json(legacy_path)["calls"] if row["prompt_id"] == PROMPT_ID]
    if len(calls) != 1 or len(legacy) != 1:
        raise ValueError("one original compose FIRST per historical Run required")
    case = existing.load_cases()["CASE-CORE-005"]
    if (
        raw["plan"]["case_id"] != "CASE-CORE-005"
        or raw["plan"]["case_sha256"] != object_hash(case.raw)
        or raw["plan"]["dataset_sha256"] != existing.file_hash(existing.DEFAULT_DATASET_PATH)
        or raw["plan"]["snapshot_sha256"]
        != existing.file_hash(existing.DEFAULT_PROVIDER_FIXTURE_PATH)
        or raw["plan"]["model"] != {"id": model["model_id"], "digest": model["model_digest"]}
        or calls[0]["input"]["user_request"] != case.raw["canonical_user_prompt"]
    ):
        raise ValueError("historical dataset/fixture/model/request binding differs")
    return calls[0], raw, legacy[0]


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    existing._validate_presence_version(model)
    if model.get("model_id") != handoff.MODEL_ID:
        raise ValueError("the fixed installed 9B model is required")
    call, raw, legacy = load_history(model)
    baseline = reconstruct_original(call)
    snapshots = snapshots_from_record(raw, call["input"])
    legacy_input = deepcopy(legacy["input"])
    if any(item.get("locator", {}).get("source_version_ref") for item in legacy_input["evidence"]):
        raise ValueError("legacy negative must remain unbound")
    negative = project_task_completion_facts(legacy_input, source_snapshots=snapshots)
    if negative != legacy_input:
        raise ValueError("unbound historical Evidence gained facts")
    synthetic, synthetic_snapshots = synthetic_completed()
    cells = [
        candidate_wire(call["input"], snapshots),
        handoff._wire_projection(synthetic),
        candidate_wire(synthetic, synthetic_snapshots),
    ]
    return {
        "kind": "TASK_COMPLETION_FACT_FIRST_DIAGNOSTIC",
        "head_sha": head(),
        "model": deepcopy(model),
        "source_hashes": _bound_files(),
        "original_run_id": raw["run_id"],
        "historical_plan": raw["plan"],
        "baseline": {
            "source_call": call,
            "source_call_sha256": object_hash(call),
            "first": baseline,
            "new_call": False,
        },
        "source_snapshots": snapshots,
        "synthetic_snapshots": synthetic_snapshots,
        "legacy_negative": {
            "source_call_sha256": object_hash(legacy),
            "original_calls_sha256": LEGACY_CALLS_HASH,
            "unchanged": True,
            "new_calls": 0,
        },
        "origins": {"raw_sha256": ORIGINAL_RAW_HASH, "calls_sha256": ORIGINAL_CALLS_HASH},
        "cells": [{"cell_id": name, **wire} for name, wire in zip(CELL_IDS, cells, strict=True)],
        "policy": {
            "max_new_calls": 3,
            "per_cell_first": 1,
            "repair": 0,
            "retry": 0,
            "concurrency": 1,
            "provider_calls": 0,
        },
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
    }


def validate_response(content: object, cell: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"semantic_verdict": "UNREVIEWED"}
    try:
        if not isinstance(content, str):
            raise ValueError("FIRST content must be JSON text")
        value = json.loads(content)
    except (ValueError, TypeError) as error:
        return {**result, "structural_result": "INVALID_JSON", "error": str(error)}
    errors = validate_output_schema(value, cell["schema"])
    if errors:
        return {**result, "structural_result": "INVALID_SCHEMA", "errors": list(errors)}
    projection = cell["input"]
    try:
        normalized = _validate_answer_candidate(
            value,
            prompt_input=projection,
            answer_outline=projection["answer_outline"],
            approved_evidence=projection["evidence"],
            user_request=projection["user_request"],
            retrieval_result=projection,
        )
    except ValueError as error:
        return {
            **result,
            "structural_result": "OWNER_VALIDATION_FAILED",
            "error": str(error),
            "reason_code": getattr(error, "reason_code", None),
        }
    return {**result, "structural_result": "VALID", "value": value, "normalized": normalized}


def _output_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == RESULTS.resolve() or not resolved.is_relative_to(RESULTS.resolve()):
        raise ValueError("dedicated evaluation/results directory required")
    return resolved


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    if (
        object_hash(plan) != plan_sha256
        or make_plan(existing.inspect_diagnostic_model("presence_zero")) != plan
    ):
        raise ValueError("plan/HEAD/code/model/input drift")
    if [cell["cell_id"] for cell in plan["cells"]] != list(CELL_IDS):
        raise ValueError("exact three FIRST cells required")
    output = _output_path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("previous result cannot be overwritten")
    write_json(
        RESULTS / ".task-completion-fact-trials" / f"{plan_sha256}.json",
        {"output": output.as_posix()},
        exclusive=True,
    )
    raw: dict[str, Any] = {
        "binding": plan,
        "calls": [],
        "completed": False,
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
        "provider_calls": 0,
    }
    path = output / "raw.json"
    write_json(path, raw, exclusive=True)
    for cell in plan["cells"]:
        row: dict[str, Any] = {
            **deepcopy(cell),
            "state": "DISPATCH_STARTED",
            "wire_request_count": 1,
            "started_at_utc": datetime.now(UTC).isoformat(),
        }
        raw["calls"].append(row)
        write_json(path, raw)
        start = time.monotonic()
        try:
            response = handoff.transport._post_json(
                endpoint=handoff.OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                path="/api/generate",
                payload=cell["wire_payload"],
                timeout_seconds=handoff.TIMEOUT_SECONDS,
            )
            row.update(
                state="RETURNED",
                content=response.get("response"),
                model=response.get("model"),
                done=response.get("done"),
                done_reason=response.get("done_reason"),
                input_tokens=response.get("prompt_eval_count"),
                output_tokens=response.get("eval_count"),
            )
            for source, target in (
                ("total_duration", "latency_ms"),
                ("load_duration", "load_duration_ms"),
                ("prompt_eval_duration", "prompt_eval_duration_ms"),
                ("eval_duration", "eval_duration_ms"),
            ):
                duration = response.get(source)
                row[target] = duration // 1_000_000 if type(duration) is int else None
            write_json(path, raw)
            if row["model"] != plan["model"]["model_id"]:
                raise ValueError("response model differs")
            row["validation"] = validate_response(row["content"], cell)
        except Exception as error:
            row.update(state="ERROR", error_type=type(error).__name__, error=str(error)[:500])
        finally:
            row["wall_latency_ms"] = int((time.monotonic() - start) * 1000)
            row["ended_at_utc"] = datetime.now(UTC).isoformat()
            write_json(path, raw)
    raw.update(
        completed=True,
        actual_http_calls=len(raw["calls"]),
        metrics=metrics(raw["calls"]),
        end_head=head(),
        source_binding_unchanged=_bound_files() == plan["source_hashes"],
        model_binding_unchanged=existing.inspect_diagnostic_model("presence_zero") == plan["model"],
    )
    write_json(path, raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--execute-plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    if args.execute_plan:
        if not args.expected_plan_sha256:
            parser.error("execution requires --expected-plan-sha256")
        raw = execute_plan(
            read_json(args.execute_plan), args.result_dir, plan_sha256=args.expected_plan_sha256
        )
        print(json.dumps({"calls": raw["actual_http_calls"], "semantic_verdict": "UNREVIEWED"}))
    else:
        plan = make_plan(existing.inspect_diagnostic_model("presence_zero"))
        path = _output_path(args.result_dir) / "preregistered-plan.json"
        write_json(path, plan, exclusive=True)
        print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "model_calls": 0}))


if __name__ == "__main__":
    main()
