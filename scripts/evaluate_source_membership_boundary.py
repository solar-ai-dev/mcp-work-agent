"""Sealed Source membership/details diagnostic; no Graph, repair, or Provider I/O."""

from __future__ import annotations

import argparse
import json
import time
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from scripts import evaluate_output_format_ablation as existing
from scripts import ru_source_membership_candidate as candidate
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import metrics, object_hash

from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation/results"
BASELINE = RESULTS / "064-source-presence-v42-t1/raw.json"
BASELINE_SHA256 = "f5b40bd0d4e36e0f7d9138d00d9d0bdd45cbebc5cd954a110ced1d3a50c6ee52"
CONTROLS = ROOT / "evaluation/experiments/064-source-membership-v43-controls.json"
CRITERIA = ROOT / "evaluation/experiments/064-source-membership-v43-criteria.md"
CORE_IDS = tuple(row[0] for row in existing.SOURCE_CONCISE_SOURCES)
CONTROL_IDS = ("SYNTHETIC-DRAFT-UPDATE", "SYNTHETIC-DRAFT-CREATE")
ARMS = ("baseline", "membership_details")
MAX_CALLS = 16
INPUT_KEYS = {
    "user_request",
    "selected_resource_refs",
    "requested_work",
    "run_reference_time",
    "goal_candidate",
    "source_candidates",
}


def _read(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _source_call(
    projection: dict[str, Any],
    template: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Construct controls with the Product assembler, then replay its actual transport."""
    if set(projection) != INPUT_KEYS:
        raise ValueError("control input may contain only existing Source input fields")
    call = {
        key: deepcopy(template[key])
        for key in (
            "prompt_id",
            "runtime_policy",
            "temperature",
            "seed",
            "model",
            "wire_options",
            "wire_think",
        )
    }
    call["source_call_kind"] = "SYNTHETIC_INPUT_NOT_OBSERVED"
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(existing.SOURCE_PROMPT_ID)
    schema = existing.build_source_dependency_output_schema(
        projection["source_candidates"],
        work_unit_ids=[w["unit_id"] for w in projection["requested_work"]["work_units"]],
    )
    call.update(
        input=deepcopy(projection),
        input_sha256=object_hash(projection),
        output_schema=schema.json_schema,
        prompt_ref=asdict(ref),
    )
    payload = existing.reconstruct_payload(template)
    payload.update(
        system=assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION),
        prompt=json.dumps(
            {
                "prompt_ref": {
                    k: asdict(ref)[k] for k in ("prompt_id", "prompt_version", "content_hash")
                },
                "input": projection,
                "output_schema": schema.json_schema,
            },
            sort_keys=True,
            ensure_ascii=False,
        ),
        format=schema.json_schema,
    )
    call["wire_sha256"] = object_hash(payload)
    # These admission flags are only a local transport-reconstruction adapter;
    # no observed response/usage/status is placed in the synthetic plan input.
    dry_call = {
        **call,
        "state": "RETURNED",
        "wire_request_count": 1,
        "wire_path": "/api/generate",
    }
    if existing.reconstruct_payload(dry_call) != payload:
        raise ValueError("control wire does not match actual Product assembly")
    return call, payload


def _validate_runtime(model: dict[str, Any], historical: dict[str, Any]) -> None:
    existing._validate_presence_version(model)
    if model != historical:
        raise ValueError("model digest/version/show parameters differ from reused baseline")


def _core_cases(raw: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    if existing.file_hash(path) != BASELINE_SHA256:
        raise ValueError("v42 original raw hash differs from the fixed baseline")
    binding = raw["binding"]
    if (
        raw.get("completed") is not True
        or raw.get("actual_http_calls") != 10
        or raw.get("reused_http_calls") != 0
        or binding.get("candidate_mode") != "presence_zero"
        or binding["dataset_sha256"] != existing.file_hash(existing.DEFAULT_DATASET_PATH)
        or binding["fixture_sha256"] != existing.file_hash(existing.DEFAULT_PROVIDER_FIXTURE_PATH)
    ):
        raise ValueError("complete v42 fresh paired baseline and current Dataset required")
    for name, digest in binding["source_hashes"].items():
        if name.startswith("src/") and existing.file_hash(ROOT / name) != digest:
            raise ValueError(f"Product dependency changed since baseline: {name}")
    source_cases = binding["cases"]
    if tuple(c["case_id"] for c in source_cases) != CORE_IDS:
        raise ValueError("only preregistered Core5 is allowed")
    canonical = existing.load_cases()
    cases = []
    for source in source_cases:
        case_id = source["case_id"]
        rows = [
            r
            for r in raw["results"]
            if r["case_id"] == case_id and r["arm"] == "schema_constrained"
        ]
        if len(rows) != 1:
            raise ValueError("exactly one actual default baseline FIRST required")
        row = rows[0]
        call = source["source_call"]
        payload = existing.reconstruct_payload(call)
        if (
            row["state"] != "RETURNED"
            or row["wire_request_count"] != 1
            or row["wire_sha256"] != object_hash(payload)
            or row["wire_options"] != payload["options"]
            or row["wire_think"] != payload["think"]
            or row["input_sha256"] != object_hash(call["input"])
            or row["prompt_ref"] != call["prompt_ref"]
            or row["model"] != binding["model"]["model_id"]
            or "presence_penalty" in payload["options"]
            or payload["options"]["temperature"] != 0.05
            or source["case_binding"]["case_sha256"] != object_hash(canonical[case_id].raw)
            or call["input"]["user_request"] != canonical[case_id].raw["canonical_user_prompt"]
        ):
            raise ValueError("baseline input/Prompt/runtime/Case authority mismatch")
        validation = existing.validate_response(row["content"], source)
        if validation != row["validation"]:
            raise ValueError("baseline current owner validation differs from original")
        baseline = {
            **deepcopy(row),
            "arm": "baseline",
            "new_call": False,
            "group": "core",
            "origin_path": path.resolve().as_posix(),
            "origin_raw_sha256": existing.file_hash(path),
            "origin_row_sha256": object_hash(row),
        }
        cases.append(
            {
                "case_id": case_id,
                "group": "core",
                "owner": "source",
                "source_call": deepcopy(call),
                "payload": payload,
                "case_binding": deepcopy(source["case_binding"]),
                "origin_case_sha256": object_hash(source),
                "baseline": baseline,
            }
        )
    return cases


def make_plan(
    model: dict[str, Any],
    *,
    baseline_path: Path = BASELINE,
    controls_path: Path = CONTROLS,
) -> dict[str, Any]:
    raw = _read(baseline_path)
    _validate_runtime(model, raw["binding"]["model"])
    cases = _core_cases(raw, baseline_path)
    controls = _read(controls_path)
    if (
        controls.get("schema_version") != 1
        or tuple(c["case_id"] for c in controls["controls"]) != CONTROL_IDS
    ):
        raise ValueError("exactly the two preregistered synthetic controls required")
    template = cases[0]["source_call"]
    for control in controls["controls"]:
        projection = deepcopy(control["input"])
        catalog = template["input"]["source_candidates"]
        if "source_candidates" in projection and projection["source_candidates"] != catalog:
            raise ValueError("control Source catalog differs from frozen Product catalog")
        projection["source_candidates"] = deepcopy(catalog)
        call, payload = _source_call(projection, template)
        cases.append(
            {
                "case_id": control["case_id"],
                "group": "synthetic",
                "owner": "source",
                "source_call": call,
                "payload": payload,
                "control_definition": deepcopy(control),
                "control_sha256": object_hash(control),
                "provider_fixture_claim": False,
            }
        )
    for case in cases:
        stage1 = candidate.build_stage_payload(case["payload"], stage="membership")
        if stage1 is None:
            raise ValueError("membership FIRST cannot be skipped")
        case.update(
            baseline_wire_sha256=object_hash(case["payload"]),
            membership_payload=stage1,
            membership_wire_sha256=object_hash(stage1),
        )
    dependencies = {
        **raw["binding"]["source_hashes"],
        "scripts/evaluate_source_membership_boundary.py": "",
        "scripts/ru_source_membership_candidate.py": "",
        "tests/evaluation/test_evaluate_source_membership_boundary.py": "",
        "docs/canonical/15-agent-capability-failure-prompt-contract.md": "",
        CRITERIA.relative_to(ROOT).as_posix(): "",
    }
    for path in candidate.PROMPT_PATHS.values():
        dependencies[Path(path).resolve().relative_to(ROOT).as_posix()] = ""
    return {
        "schema_version": 1,
        "kind": "SOURCE_MEMBERSHIP_DETAILS_V43",
        "head_sha": head(),
        "model": deepcopy(model),
        "dataset_sha256": existing.file_hash(existing.DEFAULT_DATASET_PATH),
        "fixture_sha256": existing.file_hash(existing.DEFAULT_PROVIDER_FIXTURE_PATH),
        "baseline_path": baseline_path.resolve().as_posix(),
        "baseline_sha256": existing.file_hash(baseline_path),
        "controls_path": controls_path.resolve().as_posix(),
        "controls_sha256": existing.file_hash(controls_path),
        "source_hashes": {p: existing.file_hash(ROOT / p) for p in dependencies},
        "cases": cases,
        "arms": list(ARMS),
        "execution_order": [
            {"case_id": c["case_id"], "arm": arm}
            for c in cases
            for arm in (ARMS if c["group"] == "synthetic" else (ARMS[1],))
        ],
        "policy": {
            "trials_per_case_arm": 1,
            "max_http_generation_calls": MAX_CALLS,
            "reused_core_baseline_calls": 5,
            "new_core_calls_max": 10,
            "new_synthetic_calls_max": 6,
            "concurrent_generation_calls": 1,
            "timeout_seconds_per_call": existing.TIMEOUT_SECONDS,
            "schema_repairs": 0,
            "semantic_revisions": 0,
            "http_retries": 0,
            "codec_admission": 0,
            "rerun_to_pass": 0,
            "graph_calls": 0,
            "provider_calls": 0,
            "runtime_options": "EXACT_DEFAULT_BASELINE_OPTIONS",
        },
        "baseline_reuse_limit": "NONCONTEMPORANEOUS_LATENCY_NOT_CAUSAL",
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
    }


def _stage_validation(
    content: object,
    payload: dict[str, Any],
    case: dict[str, Any],
    *,
    stage: str,
    membership: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        value = json.loads(content) if isinstance(content, str) else None
    except json.JSONDecodeError as error:
        return {"structural_result": "INVALID_JSON", "error": str(error)}
    errors = list(validate_output_schema(value, payload["format"]))
    if errors:
        return {"structural_result": "INVALID_SCHEMA", "schema_errors": errors}
    projection = case["source_call"]["input"]
    try:
        validated: Any
        if stage == "membership":
            validated = candidate.validate_membership(value, projection["source_candidates"])
        else:
            validated = candidate.materialize_decisions(
                membership,
                value,
                projection["source_candidates"],
                [w["unit_id"] for w in projection["requested_work"]["work_units"]],
            )
    except ValueError as error:
        return {"structural_result": "OWNER_REJECTED", "error": str(error)}
    if stage == "details":
        return existing.validate_response(json.dumps(validated), case)
    return {"structural_result": "VALIDATED", "validated_output": validated}


def _dispatch(
    case: dict[str, Any],
    arm: str,
    stage: str,
    payload: dict[str, Any],
    *,
    raw: dict[str, Any],
    path: Path,
    membership: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(raw["calls"]) >= MAX_CALLS:
        raise ValueError("fixed generation cap reached")
    record: dict[str, Any] = {
        "case_id": case["case_id"],
        "group": case["group"],
        "arm": arm,
        "stage": stage,
        "state": "DISPATCH_STARTED",
        "new_call": True,
        "wire_request_count": 1,
        "dispatch_started_at_utc": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "payload": deepcopy(payload),
        "wire_sha256": object_hash(payload),
        "input_sha256": object_hash(json.loads(payload["prompt"])["input"]),
        "parent_membership_sha256": object_hash(membership) if membership is not None else None,
        "parent_membership": deepcopy(membership),
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
    }
    raw["calls"].append(record)
    write_json(path, raw)
    started = time.monotonic()
    try:
        response = existing.transport._post_json(
            endpoint=existing.OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            path="/api/generate",
            payload=payload,
            timeout_seconds=existing.TIMEOUT_SECONDS,
        )
        thinking = response.get("thinking")
        record.update(
            state="RETURNED",
            content=response.get("response"),
            model=response.get("model"),
            done=response.get("done"),
            done_reason=response.get("done_reason"),
            thinking_present=bool(thinking),
            thinking_characters=len(thinking) if isinstance(thinking, str) else 0,
            input_tokens=response.get("prompt_eval_count"),
            output_tokens=response.get("eval_count"),
        )
        for field, key in (
            ("total_duration", "latency_ms"),
            ("load_duration", "load_duration_ms"),
            ("prompt_eval_duration", "prompt_eval_duration_ms"),
            ("eval_duration", "eval_duration_ms"),
        ):
            duration = response.get(field)
            record[key] = duration // 1_000_000 if type(duration) is int else None
        write_json(path, raw)
        record["validation"] = (
            existing.validate_response(record["content"], case)
            if stage == "baseline"
            else _stage_validation(
                record["content"],
                payload,
                case,
                stage=stage,
                membership=membership,
            )
        )
    except Exception as error:
        record.update(state="ERROR", error_type=type(error).__name__, error=str(error)[:500])
    finally:
        record["wall_latency_ms"] = int((time.monotonic() - started) * 1000)
        write_json(path, raw)
    return record


def _run_candidate(case: dict[str, Any], raw: dict[str, Any], path: Path) -> dict[str, Any]:
    first = _dispatch(
        case,
        ARMS[1],
        "membership",
        case["membership_payload"],
        raw=raw,
        path=path,
    )
    validation = first.get("validation", {"structural_result": first["state"]})
    if validation["structural_result"] != "VALIDATED":
        return {"validation": validation, "details_skipped": "MEMBERSHIP_FAILED"}
    membership = validation["validated_output"]
    payload = candidate.build_stage_payload(case["payload"], stage="details", membership=membership)
    if payload is not None:
        details = _dispatch(
            case,
            ARMS[1],
            "details",
            payload,
            raw=raw,
            path=path,
            membership=membership,
        )
        return {
            "membership": membership,
            "validation": details.get("validation", {"structural_result": details["state"]}),
        }
    projection = case["source_call"]["input"]
    decisions = candidate.materialize_decisions(
        membership,
        None,
        projection["source_candidates"],
        [w["unit_id"] for w in projection["requested_work"]["work_units"]],
    )
    return {
        "membership": membership,
        "details_skipped": "NO_SOURCE_SELECTED",
        "validation": existing.validate_response(json.dumps(decisions), case),
    }


def execute_plan(plan: dict[str, Any], output: Path, *, plan_sha256: str) -> dict[str, Any]:
    if object_hash(plan) != plan_sha256:
        raise ValueError("sealed plan hash mismatch")
    current = make_plan(
        existing.inspect_diagnostic_model("presence_zero"),
        baseline_path=Path(plan["baseline_path"]),
        controls_path=Path(plan["controls_path"]),
    )
    if current != plan:
        raise ValueError("HEAD/model/runtime/Prompt/input/Schema/origin binding drift")
    output = output.resolve()
    if output == RESULTS.resolve() or not output.is_relative_to(RESULTS.resolve()):
        raise ValueError("dedicated evaluation/results directory required")
    if output.exists() and any(p.name != "preregistered-plan.json" for p in output.iterdir()):
        raise ValueError("prior partial/failed trial must remain untouched")
    write_json(
        RESULTS / ".source-membership-trials" / f"{plan_sha256}.json",
        {"output": output.as_posix()},
        exclusive=True,
    )
    raw: dict[str, Any] = {
        "binding": plan,
        "calls": [],
        "results": [],
        "completed": False,
        "reused_results": [deepcopy(c["baseline"]) for c in plan["cases"] if c["group"] == "core"],
        "semantic_verdict": "UNREVIEWED",
        "business_success": "NOT_EVALUATED",
        "provider_calls": 0,
    }
    path = output / "raw.json"
    write_json(path, raw, exclusive=True)
    cases = {c["case_id"]: c for c in plan["cases"]}
    for entry in plan["execution_order"]:
        case = cases[entry["case_id"]]
        result: dict[str, Any] = {**entry, "group": case["group"], "semantic_verdict": "UNREVIEWED"}
        raw["results"].append(result)
        write_json(path, raw)
        try:
            if entry["arm"] == "baseline":
                record = _dispatch(case, ARMS[0], "baseline", case["payload"], raw=raw, path=path)
                result["validation"] = record.get(
                    "validation", {"structural_result": record["state"]}
                )
            else:
                result.update(_run_candidate(case, raw, path))
        except Exception as error:
            result.update(state="ERROR", error_type=type(error).__name__, error=str(error)[:500])
        write_json(path, raw)
    raw.update(
        completed=True,
        actual_http_calls=len(raw["calls"]),
        reused_http_calls=len(raw["reused_results"]),
        new_call_metrics=metrics(raw["calls"]),
        reused_call_metrics=metrics(raw["reused_results"]),
        metrics_by_group={
            group: {
                arm: metrics(
                    [
                        c
                        for c in [*raw["calls"], *raw["reused_results"]]
                        if c["group"] == group and c["arm"] == arm
                    ]
                )
                for arm in ARMS
            }
            for group in ("core", "synthetic")
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
    if args.execute_plan is not None:
        if not args.expected_plan_sha256:
            raise ValueError("sealed plan hash required")
        raw = execute_plan(
            _read(args.execute_plan), args.result_dir, plan_sha256=args.expected_plan_sha256
        )
        print(
            json.dumps(
                {"actual_http_calls": raw["actual_http_calls"], "semantic_verdict": "UNREVIEWED"}
            )
        )
        return
    output = args.result_dir.resolve()
    if output == RESULTS.resolve() or not output.is_relative_to(RESULTS.resolve()):
        raise ValueError("dedicated evaluation/results directory required")
    plan = make_plan(existing.inspect_diagnostic_model("presence_zero"))
    path = output / "preregistered-plan.json"
    write_json(path, plan, exclusive=True)
    print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "model_calls": 0}))


if __name__ == "__main__":
    main()
