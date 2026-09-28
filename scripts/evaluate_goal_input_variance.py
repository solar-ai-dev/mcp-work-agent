"""Two crossed Goal FIRSTs: UUID/time input sensitivity, not a quality candidate."""

from __future__ import annotations

import argparse
import json
import time
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID

from scripts import evaluate_output_format_ablation as existing
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import metrics, object_hash

from google_work_agent.application.agents.request_understanding.contracts.request_goal_candidate_schema import (  # noqa: E501
    identify_goal_output_schema,
    validate_request_goal_candidate,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

ROOT = existing.ROOT
RESULTS = existing.RESULTS
PROMPT_ID = "request_understanding.identify_goal"
CASE_ID = "CASE-CORE-005"
CRITERIA = "evaluation/experiments/067-goal-input-variance-criteria.md"
ORIGINS = (
    (
        "old",
        "066-core005-main-graph-t3",
        "b86202441c8ebc80a605025bd70d7e09f2eb2bdb83b26098340fec550033497d",
    ),
    (
        "new",
        "067-query-ref-postfix-connected-t1",
        "dd9f77ae841d361d7e61200ed2b9ab4559c815f6a9ea70c338c022d06b4d84d2",
    ),
)
CELLS = ("uuid_old__time_new", "uuid_new__time_old")


def read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def work_ids(projection: dict[str, Any]) -> list[str]:
    return [unit["unit_id"] for unit in projection["requested_work"]["work_units"]]


def reconstruct_payload(
    call: dict[str, Any], *, projection: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Use the current Product assembler and transport without sending HTTP."""
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    source = call["input"]
    schema = identify_goal_output_schema(work_ids(source))
    if (
        call["prompt_id"] != PROMPT_ID
        or call["prompt_ref"] != asdict(ref)
        or call["output_schema"] != schema.json_schema
        or call["input_sha256"] != object_hash(source)
        or call["state"] != "RETURNED"
        or call["wire_request_count"] != 1
        or call["wire_path"] != "/api/generate"
        or any(key in source for key in ("base_projection", "failure_record", "candidate_output"))
        or call["runtime_policy"]["local_timeout_seconds"] != existing.TIMEOUT_SECONDS
        or call["temperature"] != call["runtime_policy"]["sampling_temperature"]
        or call["seed"] != call["runtime_policy"]["sampling_seed"]
    ):
        raise ValueError("original single-wire Goal FIRST/schema/runtime required")
    actual_input = source if projection is None else projection
    captured: list[dict[str, Any]] = []

    def capture(**kwargs: Any) -> dict[str, Any]:
        captured.append(deepcopy(kwargs))
        return {"response": "{}"}

    with patch.object(existing.transport, "_post_json", capture):
        existing.transport.OllamaHTTPClient().invoke_structured(
            endpoint=existing.OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=call["model"],
            prompt_ref=ref,
            prompt_input=actual_input,
            output_schema=schema,
            timeout_seconds=existing.TIMEOUT_SECONDS,
            instruction_text=assemble_prompt(
                ref, actual_input, registry=registry, execution_scope=EVALUATION
            ),
            sampling_temperature=call["temperature"],
            sampling_seed=call["seed"],
        )
    if len(captured) != 1 or captured[0]["path"] != "/api/generate":
        raise ValueError("one captured Product generate request required")
    payload = cast(dict[str, Any], captured[0]["payload"])
    if (
        payload["options"] != call["wire_options"]
        or payload["think"] != call["wire_think"]
        or (projection is None and object_hash(payload) != call["wire_sha256"])
    ):
        raise ValueError("reconstructed wire differs from original Product call")
    return payload


def crossed_inputs(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    """Reject any difference except the one selected UUID and reference timestamp."""
    stripped = []
    for value in (old, new):
        item = deepcopy(value)
        refs = item["selected_resource_refs"]
        if len(refs) != 1:
            raise ValueError("this diagnostic requires exactly one selected Resource")
        UUID(refs[0].pop("resource_ref_id"))
        timestamp = item["run_reference_time"].pop("reference_time")
        if datetime.fromisoformat(timestamp).tzinfo is None:
            raise ValueError("timezone-aware historical reference timestamp required")
        stripped.append(item)
    if stripped[0] != stripped[1]:
        raise ValueError("inputs differ beyond UUID and timestamp")
    if (
        old["selected_resource_refs"][0]["resource_ref_id"]
        == new["selected_resource_refs"][0]["resource_ref_id"]
        or old["run_reference_time"] == new["run_reference_time"]
    ):
        raise ValueError("both historical factors must differ")
    first, second = deepcopy(old), deepcopy(new)
    first["run_reference_time"] = deepcopy(new["run_reference_time"])
    second["run_reference_time"] = deepcopy(old["run_reference_time"])
    return [first, second]


def validate_response(content: object, projection: dict[str, Any]) -> dict[str, Any]:
    """Goal-only admission; empty non-owner envelopes are not Source/effect decisions."""
    result: dict[str, Any] = {
        "semantic_verdict": "UNREVIEWED",
        "non_owner_semantics": "NOT_EVALUATED",
        "normalization_context": "EMPTY_NON_OWNER_ENVELOPES_FOR_GOAL_ONLY",
    }
    try:
        if not isinstance(content, str):
            raise ValueError("Goal response is not text")
        value = json.loads(content)
    except (ValueError, TypeError) as error:
        return {**result, "structural_result": "INVALID_JSON", "error": str(error)[:500]}
    schema = identify_goal_output_schema(work_ids(projection))
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        return {**result, "structural_result": "INVALID_SCHEMA", "errors": list(errors)}
    try:
        normalized = validate_request_goal_candidate(
            value,
            schema=schema,
            resource_responsibilities={"source_reads": [], "outputs": []},
            source_statuses={"statuses": []},
            effect_prohibitions={"effect_prohibitions": []},
            requested_work=projection["requested_work"],
            work_unit_ids=work_ids(projection),
            provenance_sources={"USER_REQUEST": projection["user_request"]},
        )
    except ValueError as error:
        return {
            **result,
            "structural_result": "OWNER_LOCAL_VALIDATION_FAILED",
            "error": str(error)[:500],
        }
    return {**result, "structural_result": "VALID", "value": value, "normalized": normalized}


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    existing._validate_presence_version(model)
    case = existing.load_cases()[CASE_ID]
    historical = []
    for label, directory, digest in ORIGINS:
        calls_path = RESULTS / directory / "calls.json"
        raw_path = RESULTS / directory / "raw.json"
        if existing.file_hash(calls_path) != digest:
            raise ValueError("original calls file changed")
        original = read_json(raw_path)["plan"]
        calls = [
            call
            for call in read_json(calls_path)["calls"]
            if call["prompt_id"] == PROMPT_ID and "base_projection" not in call["input"]
        ]
        if len(calls) != 1:
            raise ValueError("one original Goal FIRST required per historical Run")
        call = calls[0]
        if (
            original["case_id"] != CASE_ID
            or original["case_sha256"] != object_hash(case.raw)
            or original["dataset_sha256"] != existing.file_hash(existing.DEFAULT_DATASET_PATH)
            or original["snapshot_sha256"]
            != existing.file_hash(existing.DEFAULT_PROVIDER_FIXTURE_PATH)
            or original["model"] != {"id": model["model_id"], "digest": model["model_digest"]}
            or call["model"] != model["model_id"]
            or call["input"]["user_request"] != case.raw["canonical_user_prompt"]
        ):
            raise ValueError("historical Case/dataset/snapshot/model binding differs")
        payload = reconstruct_payload(call)
        historical.append(
            {
                "cell_id": f"uuid_{label}__time_{label}",
                "source_call": deepcopy(call),
                "source_call_sha256": object_hash(call),
                "source_calls_path": calls_path.as_posix(),
                "source_calls_sha256": digest,
                "source_raw_path": raw_path.as_posix(),
                "source_raw_sha256": existing.file_hash(raw_path),
                "source_head_sha": original["head_sha"],
                "payload": payload,
                "validation": validate_response(call["content"], call["input"]),
                "new_call": False,
            }
        )
    old, new = [row["source_call"] for row in historical]
    for field in (
        "prompt_ref",
        "output_schema",
        "runtime_policy",
        "model",
        "wire_options",
        "wire_think",
    ):
        if old[field] != new[field]:
            raise ValueError(f"historical non-factor field differs: {field}")
    cells = []
    for cell_id, projection in zip(CELLS, crossed_inputs(old["input"], new["input"]), strict=True):
        payload = reconstruct_payload(old, projection=projection)
        cells.append(
            {
                "cell_id": cell_id,
                "input": projection,
                "input_sha256": object_hash(projection),
                "payload": payload,
                "wire_sha256": object_hash(payload),
            }
        )
    paths = {
        "scripts/evaluate_goal_input_variance.py",
        "tests/evaluation/test_goal_input_variance.py",
        "scripts/evaluate_output_format_ablation.py",
        "scripts/evaluate_effect_prohibition_sampler.py",
        "scripts/ru_observation.py",
        CRITERIA,
        "src/google_work_agent/adapters/llm/ollama/transport.py",
        "src/google_work_agent/ports/llm/output_schema_validation.py",
        "docs/canonical/15-agent-capability-failure-prompt-contract.md",
    }
    for folder in ("application/agents/request_understanding", "application/prompt_runtime"):
        paths.update(
            p.relative_to(ROOT).as_posix()
            for p in (ROOT / "src/google_work_agent" / folder).rglob("*")
            if p.is_file() and p.suffix in {".py", ".json", ".md"}
        )
    return {
        "kind": "GOAL_UUID_TIME_TWO_FACTOR_DIAGNOSTIC",
        "head_sha": head(),
        "model": model,
        "case_id": CASE_ID,
        "case_sha256": object_hash(case.raw),
        "dataset_sha256": existing.file_hash(existing.DEFAULT_DATASET_PATH),
        "fixture_sha256": existing.file_hash(existing.DEFAULT_PROVIDER_FIXTURE_PATH),
        "source_hashes": {path: existing.file_hash(ROOT / path) for path in sorted(paths)},
        "reused_results": historical,
        "cells": cells,
        "historical_runtime_limitation": (
            "ORIGINAL_WIRE_AND_MODEL_DIGEST_VERIFIED_NOT_FRESH_PAIRED_TRIALS"
        ),
        "policy": {
            "max_new_calls": 2,
            "trials_per_cell": 1,
            "concurrency": 1,
            "repair": 0,
            "retry": 0,
            "provider_calls": 0,
        },
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
    }


def _output_path(output: Path) -> Path:
    output = output.resolve()
    if output == RESULTS.resolve() or not output.is_relative_to(RESULTS.resolve()):
        raise ValueError("dedicated evaluation/results directory required")
    return output


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    if object_hash(plan) != plan_sha256:
        raise ValueError("plan hash mismatch")
    if make_plan(existing.inspect_diagnostic_model("presence_zero")) != plan:
        raise ValueError("HEAD/code/input/model/runtime drift")
    if [cell["cell_id"] for cell in plan["cells"]] != list(CELLS):
        raise ValueError("exact two crossed cells required")
    output = _output_path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("previous result cannot be overwritten")
    write_json(
        RESULTS / ".goal-input-variance-trials" / f"{plan_sha256}.json",
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
            "cell_id": cell["cell_id"],
            "state": "DISPATCH_STARTED",
            "payload": cell["payload"],
            "wire_sha256": cell["wire_sha256"],
            "wire_request_count": 1,
            "input_sha256": cell["input_sha256"],
            "started_at_utc": datetime.now(UTC).isoformat(),
        }
        raw["calls"].append(row)
        write_json(path, raw)
        start = time.monotonic()
        try:
            response = existing.transport._post_json(
                endpoint=existing.OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                path="/api/generate",
                payload=cell["payload"],
                timeout_seconds=existing.TIMEOUT_SECONDS,
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
                raise ValueError("response model differs from registered model")
            row["validation"] = validate_response(row["content"], cell["input"])
        except Exception as error:
            row.update(state="ERROR", error_type=type(error).__name__, error=str(error)[:500])
        finally:
            row["wall_latency_ms"] = int((time.monotonic() - start) * 1000)
            row["ended_at_utc"] = datetime.now(UTC).isoformat()
            write_json(path, raw)
    raw.update(
        completed=True,
        actual_http_calls=len(raw["calls"]),
        metrics={
            "new_crossed": metrics(raw["calls"]),
            "reused_diagonal": metrics([row["source_call"] for row in plan["reused_results"]]),
        },
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
