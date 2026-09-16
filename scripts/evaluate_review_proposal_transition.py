"""Compare frozen RECHECK inputs with a bounded previous/current proposal relation."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.evaluate_review_decomposition_node import MODEL_ID, _runtime
from scripts.evaluate_review_reference_time_node import _candidate_manifest

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_recheck_output_schema,
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

PROMPT_ID = "review.recheck_affected_dimensions"
ORDER = (
    ("WRONG_DATE_023", "corrected", "A"),
    ("WRONG_DATE_023", "corrected", "B"),
    ("FORBIDDEN_ATTENDEE_023", "corrected", "B"),
    ("FORBIDDEN_ATTENDEE_023", "corrected", "A"),
    ("WRONG_DATE_023", "unresolved", "B"),
    ("WRONG_DATE_023", "unresolved", "A"),
    ("FORBIDDEN_ATTENDEE_023", "unresolved", "A"),
    ("FORBIDDEN_ATTENDEE_023", "unresolved", "B"),
)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _changed_values(previous: object, current: object, path: str = "") -> list[dict[str, Any]]:
    if isinstance(previous, dict) and isinstance(current, dict):
        result: list[dict[str, Any]] = []
        for key in sorted(previous.keys() | current.keys()):
            nested = f"{path}/{key.replace('~', '~0').replace('/', '~1')}"
            if key not in previous:
                result.append({"path": nested, "previous": None, "current": current[key]})
            elif key not in current:
                result.append({"path": nested, "previous": previous[key], "current": None})
            else:
                result.extend(_changed_values(previous[key], current[key], nested))
        return result
    if previous == current:
        return []
    return [{"path": path, "previous": previous, "current": current}]


def _proposal_transition(case: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    previous_plan = case["plan_before"]
    prior_review = case["stages"][0]["review_result"]
    if prior_review["status"] != "REVISE":
        raise ValueError("frozen Review finding is not REVISE")
    previous_actions = previous_plan["actions"]
    current_actions = current["actions"]
    route_ids = {
        route_id for issue in prior_review["issues"] for route_id in issue["affected_route_ids"]
    }
    if len(route_ids) != 1:
        raise ValueError("candidate requires an unambiguous affected route")
    route_id = next(iter(route_ids))
    previous = [action for action in previous_actions if action["route_id"] == route_id]
    latest = [action for action in current_actions if action["route_id"] == route_id]
    if len(previous) != 1 or len(latest) != 1:
        raise ValueError("candidate cannot bind ambiguous Action multiplicity")
    return {
        "stage": "PROPOSAL_REVIEW_BEFORE_EXECUTION",
        "previous_plan_ref": previous_plan["meta"],
        "current_plan_ref": current["meta"],
        "route_id": route_id,
        "previous_action_id": previous[0]["action_id"],
        "current_action_id": latest[0]["action_id"],
        "changed_arguments": _changed_values(previous[0]["arguments"], latest[0]["arguments"]),
        "historical_review_issues": [
            {
                "dimension": issue["affected_dimensions"],
                "code": issue["code"],
                "description": issue["description"],
                "affected_action_ids": issue["affected_action_ids"],
                "affected_route_ids": issue["affected_route_ids"],
            }
            for issue in prior_review["issues"]
            if route_id in issue["affected_route_ids"]
        ],
    }


def evaluate(cycle_path: Path, connected_path: Path, output_path: Path) -> None:
    cycle_bytes = cycle_path.read_bytes()
    connected_bytes = connected_path.read_bytes()
    cycle = json.loads(cycle_bytes)
    connected = json.loads(connected_bytes)
    installed = {item.model_id: item.digest for item in OllamaHTTPClient().list_installed_models()}
    if installed.get(MODEL_ID) != cycle["binding"]["model_digest"]:
        raise ValueError("installed model differs from frozen Review cycle")
    cases = {item["label"]: item for item in cycle["cases"]}
    upstream = {item["case_id"]: item for item in connected["cases"]}
    root = Path(tempfile.mkdtemp(prefix="gwa-review-proposal-transition-"))
    manifest = _candidate_manifest(root, optional_field="proposal_transition", prompt_id=PROMPT_ID)
    runtime = _runtime(root / "runtime", manifest)
    reference = load_prompt_reference(PROMPT_ID, manifest, execution_scope=DEVELOPMENT_SMOKE)
    result: dict[str, Any] = {
        "binding": {
            "baseline_sha": "53842ae6",
            "cycle_sha256": hashlib.sha256(cycle_bytes).hexdigest(),
            "connected_sha256": hashlib.sha256(connected_bytes).hexdigest(),
            "model_id": MODEL_ID,
            "model_digest": installed[MODEL_ID],
            "sampling_temperature": 0.0,
            "sampling_seed": 1729,
            "prompt_hash": reference.content_hash,
            "call_limit": len(ORDER),
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label, status, arm in ORDER:
        case = cases[label]
        source = upstream[case["source_case"]]
        started_at_ms = source["reference_started_at_ms"]
        prompt_input = deepcopy(
            next(
                item["prompt_input"]
                for item in case["stages"][-1]["inference_details"]
                if item["prompt_id"] == PROMPT_ID
            )
        )
        if status == "unresolved":
            prompt_input["planning_result"] = deepcopy(case["plan_before"])
        if arm == "B":
            prompt_input["proposal_transition"] = _proposal_transition(
                case, prompt_input["planning_result"]
            )
        started = time.perf_counter()
        trial: dict[str, Any] = {
            "label": label,
            "status": status,
            "arm": arm,
            "input_sha256": _fingerprint(prompt_input),
            "prompt_input": prompt_input,
        }
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-transition-{label}-{status}-{arm}",
                    now_ms=lambda base=started_at_ms, start=started: (
                        base + int((time.perf_counter() - start) * 1_000)
                    ),
                ),
                provider_dispatch_budget_scope(
                    build_default_run_budget(started_at_ms=started_at_ms)
                ),
            ):
                inference = runtime.infer(
                    "LOCAL_GPU",
                    reference,
                    prompt_input,
                    review_recheck_output_schema(tuple(prompt_input["affected_dimensions"])),
                )
            trial.update(
                {
                    "outcome": "COMPLETED",
                    "structured_output": inference.structured_output,
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
        result["trials"].append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, status, arm, trial["outcome"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", type=Path, required=True)
    parser.add_argument("--connected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.cycle, args.connected, args.output)


if __name__ == "__main__":
    main()
