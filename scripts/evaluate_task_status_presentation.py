"""095: sealed Task status presentation probe; no Product artifact or Graph mutation."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from scripts import evaluate_output_format_ablation as existing
from scripts import evaluate_registered_answer_choice as registered
from scripts import evaluate_ru_semantic_capability as recorder
from scripts.evaluate_effect_prohibition_sampler import head, write_json
from scripts.ru_observation import metrics, object_hash

from google_work_agent.application.agents.planning.project_task_read_answer import _task_status
from google_work_agent.application.agents.retrieval.resolve_task_calendar_snapshot import (
    resolve_task_calendar_snapshot,
    resolve_unique_task_calendar_snapshots,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

ROOT, RESULTS = registered.ROOT, recorder.RESULTS
HISTORY = RESULTS / "094-product-task-field-scope-t1/raw.json"
HISTORY_PLAN = RESULTS / "094-product-task-field-scope-plan/plan.json"
HISTORY_HASH = "c105a18762ceda2b070dea3b82995e502d4aec447a3f3376a1940c11f4676f14"
HISTORY_PLAN_HASH = "28231426a7d7249f7e629ba67104e10e18eb5ef0c403552263b2e4c4809e522b"
CRITERIA = "evaluation/experiments/095-task-status-presentation-criteria.md"
CONTRACT = "evaluation-task-status-presentation-input-v1"
ARM = "CANONICAL_STATUS_PRESENTATION"
GROUPS = registered.TASK_FIELD_GROUPS
WALL_SECONDS = 420


def project_status_presentation(
    prompt_input: dict[str, Any], source_snapshots: dict[str, Any]
) -> dict[str, Any]:
    """Require full synthetic serialization; never parse or replace arbitrary excerpt text.

    Snapshot identity/hash is checked here. Same-Run authority is separately verified
    from sealed 094 store observations, not inferred from source_version_ref.
    """
    result = deepcopy(prompt_input)
    evidence = result["evidence"]
    refs = [registered._ref(item) for item in evidence]
    approved = result["answer_outline"]["evidence_refs"]
    if (
        not refs
        or len(set(refs)) != len(refs)
        or set(refs) != set(approved)
        or set(refs) != set(source_snapshots)
        or resolve_unique_task_calendar_snapshots(evidence, source_snapshots) is None
    ):
        raise ValueError("exact approved Evidence and valid non-conflicting snapshots required")
    for item, ref in zip(evidence, refs, strict=True):
        snapshot = source_snapshots[ref]
        fields = resolve_task_calendar_snapshot(item, source_snapshots)
        if snapshot.get("resource_type") != "task" or fields is None:
            raise ValueError("only exact Task snapshots supported")
        status = _task_status(fields.get("status"), korean=False)
        if status is None or any(not isinstance(value, str) for value in fields.values()):
            raise ValueError("known status and complete visible scalar fields required")
        original_excerpt = "\n".join(f"{field}: {value}" for field, value in fields.items())
        if item.get("excerpt") != original_excerpt:
            raise ValueError("whole synthetic typed-field serialization must match excerpt")
        item["excerpt"] = "\n".join(
            f"{field}: {status if field == 'status' else value}" for field, value in fields.items()
        )
    return result


def build_payload(original: dict[str, Any], *, source_snapshots: dict[str, Any]) -> dict[str, Any]:
    body = json.loads(original["prompt"])
    original_input = body["input"]
    rebuilt = registered.expected_first(
        original_input, source_snapshots, planning_mode=registered.PRODUCT_TASK_FIELD_SCOPE
    )
    if registered.transport_hash(original) != registered.transport_hash(rebuilt["payload"]):
        raise ValueError("current native Product FIRST wire drift")
    if json.dumps(body, ensure_ascii=False, sort_keys=True) != original["prompt"]:
        raise ValueError("canonical original body serialization required")
    projection = project_status_presentation(original_input, source_snapshots)
    old_json = json.dumps(original_input, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    new_json = json.dumps(projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    suffix = "Allowed current-Run input projection (JSON):\n" + old_json + "\n"
    if not original["system"].endswith(suffix):
        raise ValueError("exact assembled original input suffix required")
    payload = deepcopy(original)
    payload["system"] = original["system"][: -len(old_json + "\n")] + new_json + "\n"
    body["input"] = projection
    payload["prompt"] = json.dumps(body, ensure_ascii=False, sort_keys=True)
    return payload


def _lineage(source: dict[str, Any], trial: dict[str, Any]) -> dict[str, Any]:
    run_id = trial["local_run"].get("run_id")
    observations = trial["snapshot_resolutions"]
    if not run_id or not observations or not trial.get("input_binding_unchanged"):
        raise ValueError("historical Run and immutable input binding required")
    expected = {
        (
            item["resource_handle"],
            item["locator"]["source_version_ref"],
            object_hash(source["snapshots"][registered._ref(item)]),
        )
        for item in source["prompt_input"]["evidence"]
    }
    actual = set()
    for item in observations:
        if item["run_id"] != run_id or item["resolution"] != "RESOLVED":
            raise ValueError("foreign Run or unresolved snapshot observation")
        actual.add((item["resource_handle"], item["source_version_ref"], item["snapshot_sha256"]))
    if actual != expected:
        raise ValueError("historical same-Run snapshot hash/version/handle mismatch")
    return {"run_id": run_id, "trial_sha256": object_hash(trial), "resolutions": observations}


def verify_wire_seals(plan: dict[str, Any]) -> None:
    if [(c["group"], c["trial"]) for c in plan["cases"]] != [(g, 1) for g in GROUPS]:
        raise ValueError("fixed FULL then PARTIAL, one FIRST each required")
    for case in plan["cases"]:
        payload = build_payload(case["original_payload"], source_snapshots=case["snapshots"])
        if (
            case["arm"] != ARM
            or registered.transport_hash(case["original_payload"])
            != case["historical_transport_sha256"]
            or registered.transport_hash(payload) != case["candidate_transport_sha256"]
            or registered.transport_hash(case["candidate_payload"])
            != case["candidate_transport_sha256"]
            or case["prompt_input"] != json.loads(case["original_payload"]["prompt"])["input"]
            or object_hash(json.loads(payload["prompt"])["input"]) != case["candidate_input_sha256"]
        ):
            raise ValueError("status-only wire/input seal changed")


def make_plan(model: dict[str, Any]) -> dict[str, Any]:
    if (
        existing.file_hash(HISTORY) != HISTORY_HASH
        or existing.file_hash(HISTORY_PLAN) != HISTORY_PLAN_HASH
    ):
        raise ValueError("sealed 094 raw/plan changed")
    raw, binding = registered._read(HISTORY), registered._read(HISTORY_PLAN)
    if (
        raw["binding"] != binding
        or not raw["completed"]
        or not raw["binding_unchanged"]
        or not raw["model_binding_unchanged"]
        or raw["fake_wire"]
        or binding["planning_mode"] != registered.PRODUCT_TASK_FIELD_SCOPE
        or model != binding["model"]
        or len(raw["calls"]) != 2
    ):
        raise ValueError("completed native 094 baseline and identical actual runtime required")
    cases, references = [], []
    for group in GROUPS:
        sources = [c for c in binding["cases"] if c["group"] == group and c["trial"] == 1]
        if len(sources) != 1:
            raise ValueError("one fixed historical input required")
        source = sources[0]
        rows = [r for r in raw["calls"] if r["case_id"] == source["case_id"]]
        trials = [t for t in raw["trials"] if t["case_id"] == source["case_id"]]
        if len(rows) != 1 or len(trials) != 1:
            raise ValueError("one historical FIRST and local Run lineage required")
        row, trial = rows[0], trials[0]
        payload = row["payload"]
        if (
            row["phase"] != "FIRST"
            or row["state"] != "RETURNED"
            or row["wire_request_count"] != 1
            or row["provider_response_metadata"].get("done") is not True
            or row["actual_model"] != model["model_id"]
            or registered.transport_hash(payload) != row["transport_sha256"]
            or registered.transport_hash(payload) != source["expected_first"]["transport_sha256"]
            or row["input"] != source["prompt_input"]
            or object_hash(row["input"]) != row["input_sha256"]
            or source["input_binding_sha256"]
            != object_hash([source["prompt_input"], source["snapshots"], source["component_state"]])
        ):
            raise ValueError("historical native FIRST input/wire/binding drift")
        candidate = build_payload(payload, source_snapshots=source["snapshots"])
        cases.append(
            {
                "case_id": f"{group}-STATUS_PRESENTATION-T1",
                "group": group,
                "trial": 1,
                "arm": ARM,
                "prompt_input": deepcopy(source["prompt_input"]),
                "snapshots": deepcopy(source["snapshots"]),
                "lineage": _lineage(source, trial),
                "reference_time": source["reference_time"],
                "fault_profile": source["fault_profile"],
                "historical_case_id": source["case_id"],
                "historical_row_sha256": object_hash(row),
                "original_payload": deepcopy(payload),
                "historical_transport_sha256": row["transport_sha256"],
                "candidate_payload": candidate,
                "candidate_transport_sha256": registered.transport_hash(candidate),
                "candidate_input_sha256": object_hash(json.loads(candidate["prompt"])["input"]),
            }
        )
        references.append(deepcopy(row))
    paths = (
        set(binding["source_hashes"])
        | {p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py")}
        | {
            "scripts/evaluate_task_status_presentation.py",
            "tests/evaluation/test_task_status_presentation.py",
            "scripts/evaluate_ru_semantic_capability.py",
            "docs/canonical/05-context-retrieval.md",
            "docs/canonical/15-agent-capability-failure-prompt-contract.md",
            CRITERIA,
        }
    )
    plan = {
        "kind": "095_TASK_STATUS_PRESENTATION",
        "head_sha": head(),
        "model": model,
        "evaluation_input_contract": CONTRACT,
        "cases": cases,
        "historical_references": references,
        "historical_head_sha": binding["head_sha"],
        "history_hashes": {
            HISTORY.relative_to(ROOT).as_posix(): HISTORY_HASH,
            HISTORY_PLAN.relative_to(ROOT).as_posix(): HISTORY_PLAN_HASH,
        },
        "source_hashes": {p: existing.file_hash(ROOT / p) for p in sorted(paths)},
        "scope": "UNREGISTERED_WIRE_VIEW_NOT_PRODUCT_GRAPH_OR_RUN_RESUME",
        "prompt_ref_status": "UNCHANGED_HISTORICAL_PROVENANCE_NOT_REGISTERED_NEW_VIEW",
        "snapshot_authority": "SEALED_094_SAME_RUN_LINEAGE_NOT_CURRENT_STORE_EXECUTION",
        "policy": {
            "new_calls": 2,
            "unique_historical_calls": 2,
            "maximum_generate_calls": 2,
            "repair": 0,
            "retry": 0,
            "concurrency": 1,
            "timeout_seconds": 180,
            "wall_seconds": WALL_SECONDS,
            "wall_enforcement": "BEFORE_NEXT_DISPATCH",
        },
        "semantic_verdict": "NOT_REVIEWED",
        "business_success": "NOT_EVALUATED",
    }
    verify_wire_seals(plan)
    return plan


def record_admission(row: dict[str, Any], case: dict[str, Any]) -> str | None:
    schema = json.loads(case["original_payload"]["prompt"])["output_schema"]
    try:
        value = json.loads(row["content"])
    except (ValueError, TypeError):
        row["answer_admission"] = {"validation": "INVALID_JSON"}
        return "INVALID_JSON"
    errors = validate_output_schema(value, schema)
    row["answer_admission"] = {
        "validation": "INVALID_SCHEMA" if errors else "VALID",
        "errors": errors,
        "value": value,
        "semantic_verdict": "NOT_REVIEWED",
    }
    return "INVALID_SCHEMA" if errors else None


def execute_plan(
    plan: dict[str, Any],
    output: Path,
    *,
    plan_sha256: str,
    reconstruct_plan: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    verify_wire_seals(plan)
    start, post = time.monotonic(), existing.transport._post_json
    dispatched: list[str] = []

    def bounded_post(**kwargs: Any) -> dict[str, Any]:
        if kwargs["path"] == "/api/generate":
            if time.monotonic() - start >= WALL_SECONDS or len(dispatched) >= 2:
                raise TimeoutError("095 next-dispatch wall/call bound reached")
            dispatched.append(registered.transport_hash(kwargs["payload"]))
        return cast(dict[str, Any], post(**kwargs))

    def reconstruct() -> dict[str, Any]:
        fresh = reconstruct_plan()
        verify_wire_seals(fresh)
        return fresh

    with patch.object(existing.transport, "_post_json", bounded_post):
        raw = recorder.execute_registered_plan(
            plan,
            output,
            plan_sha256=plan_sha256,
            reconstruct_plan=reconstruct,
            claim_directory=".task-status-presentation-trials",
            reference_results=plan["historical_references"],
            reference_metric="094_historical_two_firsts",
            stop_after_response=record_admission,
        )
    for index, row in enumerate(raw["calls"]):
        sent = index < len(dispatched)
        row.update(arm=ARM, wire_request_count=int(sent), actual_http_dispatched=sent)
        if not sent:
            row["state"] = "NOT_DISPATCHED"
    raw.update(
        actual_http_calls=len(dispatched),
        transport_dispatch_sha256=dispatched,
        registered_router_calls=0,
        scope=plan["scope"],
    )
    raw["metrics"]["control_new"] = metrics(
        [r for r in raw["calls"] if r["actual_http_dispatched"]]
    )
    write_json(output / "raw.json", raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute-plan", type=Path)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if args.prepare:
        directory = recorder._output_directory(args.result_dir)
        plan = make_plan(existing.inspect_diagnostic_model("presence_zero"))
        path = directory / "preregistered-plan.json"
        write_json(path, plan, exclusive=True)
        print(json.dumps({"plan": str(path), "sha256": object_hash(plan), "generation_calls": 0}))
        return
    if not args.plan_sha256:
        parser.error("--execute-plan requires --plan-sha256")
    raw = execute_plan(
        registered._read(args.execute_plan),
        args.result_dir,
        plan_sha256=args.plan_sha256,
        reconstruct_plan=lambda: make_plan(existing.inspect_diagnostic_model("presence_zero")),
    )
    print(json.dumps({k: raw[k] for k in ("diagnostic_status", "actual_http_calls")}))
    raise SystemExit(0 if raw["diagnostic_status"] == "RECORDED" else 1)


if __name__ == "__main__":
    main()
