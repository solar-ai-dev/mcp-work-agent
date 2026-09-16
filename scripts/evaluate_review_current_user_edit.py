"""Compare Review Goal inputs with exact current-Preview edit bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from scripts.evaluate_review_decomposition_node import MODEL_ID, _runtime
from scripts.evaluate_review_reference_time_node import _candidate_manifest

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_inspector_output_schema,
    validate_review_inspector_result,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget

PROMPT_ID = "review.inspect_goal_and_evidence"
FIELD = "current_user_edit_bindings"


def _goal_input(case: dict[str, Any]) -> dict[str, Any]:
    stage = case["stages"][0]
    return deepcopy(
        next(
            item["prompt_input"]
            for item in stage["inference_details"]
            if item["prompt_id"] == PROMPT_ID
        )
    )


def _rows(
    cycle: dict[str, Any], connected: dict[str, Any], *, comparison: str = "initial"
) -> list[tuple[str, str, dict[str, Any], int]]:
    cases = {item["label"]: item for item in cycle["cases"]}
    upstream = {item["case_id"]: item for item in connected["cases"]}
    edited_023 = _goal_input(cases["USER_EDIT_023"])
    edited_028 = _goal_input(cases["NORMAL_028"])
    action_028 = edited_028["planning_result"]["actions"][0]
    action_028["arguments"]["payload"]["title"] = "Kestrel 일정 후속 점검"
    edited_028["user_action_modifications"] = [
        {
            "action_id": action_028["action_id"],
            "argument_overrides": {"payload.title": "Kestrel 일정 후속 점검"},
        }
    ]
    mismatch_023 = deepcopy(edited_023)
    mismatch_023["planning_result"]["actions"][0]["arguments"]["payload"]["title"] = _goal_input(
        cases["NORMAL_023"]
    )["planning_result"]["actions"][0]["arguments"]["payload"]["title"]
    inputs = {
        "USER_EDIT_023": (edited_023, "CASE-CORE-023"),
        "USER_EDIT_028_SYNTHETIC": (edited_028, "CASE-CORE-028"),
        "EDIT_MISMATCH_023_SYNTHETIC": (mismatch_023, "CASE-CORE-023"),
        "NORMAL_023": (_goal_input(cases["NORMAL_023"]), "CASE-CORE-023"),
        "NORMAL_028": (_goal_input(cases["NORMAL_028"]), "CASE-CORE-028"),
    }
    if comparison == "initial":
        order = (
            ("USER_EDIT_023", "A"),
            ("USER_EDIT_023", "B"),
            ("USER_EDIT_028_SYNTHETIC", "B"),
            ("USER_EDIT_028_SYNTHETIC", "A"),
            ("EDIT_MISMATCH_023_SYNTHETIC", "A"),
            ("EDIT_MISMATCH_023_SYNTHETIC", "B"),
            ("NORMAL_023", "A"),
            ("NORMAL_028", "A"),
        )
    elif comparison == "prior":
        order = (
            ("USER_EDIT_023", "B"),
            ("USER_EDIT_023", "C"),
            ("USER_EDIT_028_SYNTHETIC", "C"),
            ("USER_EDIT_028_SYNTHETIC", "B"),
            ("EDIT_MISMATCH_023_SYNTHETIC", "B"),
            ("EDIT_MISMATCH_023_SYNTHETIC", "C"),
        )
    else:
        order = (
            ("USER_EDIT_023", "A"),
            ("USER_EDIT_023", "D"),
            ("USER_EDIT_028_SYNTHETIC", "D"),
            ("USER_EDIT_028_SYNTHETIC", "A"),
            ("EDIT_MISMATCH_023_SYNTHETIC", "A"),
            ("EDIT_MISMATCH_023_SYNTHETIC", "D"),
        )
    rows = []
    for label, arm in order:
        original, source_case = inputs[label]
        prompt_input = deepcopy(original)
        if arm in {"B", "C"}:
            prompt_input[FIELD] = current_user_edit_bindings(
                prompt_input, include_prior_constraint=arm == "C"
            )
        elif arm == "D":
            prompt_input["request_intent"] = materialize_current_request(prompt_input)
        rows.append((label, arm, prompt_input, upstream[source_case]["reference_started_at_ms"]))
    return rows


def current_user_edit_bindings(
    prompt_input: dict[str, Any], *, include_prior_constraint: bool = False
) -> list[dict[str, Any]]:
    """Bind trusted changed paths to current Actions without deciding semantic validity."""
    actions = prompt_input["planning_result"]["actions"]
    by_id = {action["action_id"]: action for action in actions}
    if len(by_id) != len(actions):
        raise ValueError("Plan action IDs must be unique")
    result: list[dict[str, Any]] = []
    for modification in prompt_input.get("user_action_modifications", []):
        action_id = modification["action_id"]
        action = by_id.get(action_id)
        if action is None:
            raise ValueError("User modification references no current Action")
        for path, selected_value in modification["argument_overrides"].items():
            if (
                not isinstance(path, str)
                or not path
                or not isinstance(
                    selected_value, str | int | float | bool | list | dict | type(None)
                )
            ):
                raise ValueError("User modification path/value is invalid")
            current: Any = action["arguments"]
            present = True
            for segment in path.split("."):
                if not segment or not isinstance(current, dict) or segment not in current:
                    present = False
                    break
                current = current[segment]
            binding: dict[str, Any] = {
                "action_id": action_id,
                "route_id": action["route_id"],
                "argument_path": path,
                "current_user_value": selected_value,
                "current_plan_value": {
                    "present": present,
                    "value": current if present else None,
                },
            }
            if include_prior_constraint:
                field = path.rsplit(".", 1)[-1]
                matches = [
                    constraint
                    for constraint in prompt_input["request_intent"]["constraints"]
                    if constraint.get("field") == field
                ]
                if len(matches) == 1:
                    binding["superseded_request_constraint"] = matches[0]
            result.append(binding)
    return result


def materialize_current_request(prompt_input: dict[str, Any]) -> dict[str, Any]:
    """Apply unambiguous validated Preview values to a Review-only Intent projection."""
    intent = deepcopy(prompt_input["request_intent"])
    actions = prompt_input["planning_result"]["actions"]
    modifications = prompt_input.get("user_action_modifications", [])
    if len(actions) != 1 or not modifications:
        return intent
    action = actions[0]
    if any(item.get("action_id") != action["action_id"] for item in modifications):
        return intent
    constraints = intent["constraints"]
    for modification in modifications:
        for path, selected_value in modification["argument_overrides"].items():
            if not isinstance(path, str) or not path:
                continue
            if not isinstance(selected_value, str) and not (
                isinstance(selected_value, list)
                and all(isinstance(value, str) for value in selected_value)
            ):
                continue
            field = path.rsplit(".", 1)[-1]
            matches = [constraint for constraint in constraints if constraint.get("field") == field]
            if len(matches) != 1 or "provenance" in matches[0]:
                continue
            matches[0]["value"] = selected_value
    return intent


def evaluate(
    cycle_path: Path, connected_path: Path, output_path: Path, *, comparison: str = "initial"
) -> None:
    cycle_bytes = cycle_path.read_bytes()
    connected_bytes = connected_path.read_bytes()
    cycle = json.loads(cycle_bytes)
    connected = json.loads(connected_bytes)
    digest = next(
        (
            item.digest
            for item in OllamaHTTPClient().list_installed_models()
            if item.model_id == MODEL_ID
        ),
        None,
    )
    if digest != cycle["binding"]["model_digest"]:
        raise ValueError("installed model differs from frozen cycle")
    rows = _rows(cycle, connected, comparison=comparison)
    if len(rows) != (8 if comparison == "initial" else 6):
        raise ValueError("predeclared comparison size changed")
    root = Path(tempfile.mkdtemp(prefix="gwa-review-current-edit-"))
    manifest = _candidate_manifest(root, optional_field=FIELD, prompt_id=PROMPT_ID)
    runtime = _runtime(root / "runtime", manifest)
    reference = load_prompt_reference(PROMPT_ID, manifest, execution_scope=DEVELOPMENT_SMOKE)
    schema = review_inspector_output_schema(PROMPT_ID)
    result: dict[str, Any] = {
        "binding": {
            "baseline_sha": "53842ae6",
            "comparison": comparison,
            "cycle_sha256": hashlib.sha256(cycle_bytes).hexdigest(),
            "connected_sha256": hashlib.sha256(connected_bytes).hexdigest(),
            "model_id": MODEL_ID,
            "model_digest": digest,
            "sampling_temperature": 0.0,
            "sampling_seed": 1729,
            "prompt_hash": reference.content_hash,
            "call_limit": len(rows),
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label, arm, prompt_input, started_at_ms in rows:
        started = time.perf_counter()
        trial: dict[str, Any] = {
            "label": label,
            "arm": arm,
            "input_sha256": hashlib.sha256(
                json.dumps(prompt_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "prompt_input": prompt_input,
        }
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-current-edit-{label}-{arm}",
                    now_ms=lambda base=started_at_ms, start=started: (
                        base + int((time.perf_counter() - start) * 1_000)
                    ),
                ),
                provider_dispatch_budget_scope(
                    build_default_run_budget(started_at_ms=started_at_ms)
                ),
            ):
                inference = runtime.infer("LOCAL_GPU", reference, prompt_input, schema)
            trial.update(
                {
                    "outcome": "COMPLETED",
                    "structured_output": validate_review_inspector_result(
                        inference.structured_output, expected_dimension=PROMPT_ID
                    ),
                    "input_tokens": inference.input_tokens,
                    "output_tokens": inference.output_tokens,
                    "provider_latency_ms": inference.latency_ms,
                }
            )
        except Exception as error:
            code = getattr(error, "code", None)
            trial.update(
                {
                    "outcome": "FAILED",
                    "error_type": type(error).__name__,
                    "error_code": getattr(code, "value", None),
                    "message": str(error),
                }
            )
        trial["duration_ms"] = int((time.perf_counter() - started) * 1_000)
        cast(list[dict[str, Any]], result["trials"]).append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, arm, trial["outcome"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", type=Path, required=True)
    parser.add_argument("--connected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--comparison", choices=("initial", "prior", "materialized"), default="initial"
    )
    args = parser.parse_args()
    evaluate(args.cycle, args.connected, args.output, comparison=args.comparison)


if __name__ == "__main__":
    main()
