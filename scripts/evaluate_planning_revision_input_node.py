"""Compare frozen Planning argument input with a route-scoped revision context."""

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
from google_work_agent.application.agents.planning.compose_arguments_per_output_route import (
    tool_argument_candidate_output_schema,
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

PROMPT_ID = "planning.compose_arguments_per_output_route"


def _rows(
    connected: dict[str, Any], reviewed: dict[str, Any]
) -> list[tuple[str, str, dict[str, object], int]]:
    case = next(
        item for item in connected["cases"] if item["case_id"] == "CASE-CORE-023"
    )
    details = [
        item for item in case["work_analysis"]["downstream"]["inference_details"]
        if item["prompt_id"] == PROMPT_ID
    ]
    if len(details) != 1:
        raise ValueError("frozen Planning composer input missing")
    original = cast(dict[str, object], details[0]["prompt_input"])
    route_id = cast(dict[str, object], original["output_route"])["route_id"]
    started_at_ms = cast(int, case["reference_started_at_ms"])
    trials = {
        item["label"]: item for item in reviewed["trials"]
        if item["label"] in {"WRONG_ACTION_DATE", "FORBIDDEN_ATTENDEE"}
    }
    if len(trials) != 2:
        raise ValueError("predeclared Review findings missing")
    rows: list[tuple[str, str, dict[str, object], int]] = []
    for label, arms in (
        ("WRONG_ACTION_DATE", ("A", "B")),
        ("FORBIDDEN_ATTENDEE", ("B", "A")),
    ):
        trial = trials[label]
        prior = trial["prompt_input"]["planning_result"]["actions"]
        findings = trial["structured_output"]["findings"]
        if len(prior) != 1 or not findings:
            raise ValueError("predeclared prior action or finding missing")
        prior_action = prior[0]
        if prior_action["route_id"] != route_id:
            raise ValueError("prior action route differs from frozen composer route")
        issues = [
            {
                "code": item["code"],
                "description": item["description"],
                "affected_action_ids": item["affected_action_ids"],
                "affected_route_ids": item["affected_route_ids"],
                "evidence_refs": item["evidence_refs"],
            }
            for item in findings
            if item["finding_kind"] == "ISSUE"
        ]
        if not issues:
            raise ValueError("predeclared Review issue missing")
        for arm in arms:
            prompt_input = deepcopy(original)
            if arm == "B":
                prompt_input["revision_context"] = {
                    "prior_action": prior_action,
                    "review_issues": issues,
                }
            rows.append((label, arm, prompt_input, started_at_ms))
    return rows


def evaluate(connected_path: Path, reviewed_path: Path, output_path: Path) -> dict[str, object]:
    connected_bytes = connected_path.read_bytes()
    reviewed_bytes = reviewed_path.read_bytes()
    connected = json.loads(connected_bytes)
    reviewed = json.loads(reviewed_bytes)
    installed = {
        item.model_id: item.digest for item in OllamaHTTPClient().list_installed_models()
    }
    if installed.get(MODEL_ID) != connected["binding"]["model_digest"]:
        raise ValueError("installed model digest differs from frozen connected input")
    rows = _rows(connected, reviewed)
    root = Path(tempfile.mkdtemp(prefix="gwa-planning-revision-input-"))
    manifest = _candidate_manifest(
        root, optional_field="revision_context", prompt_id=PROMPT_ID
    )
    runtime = _runtime(root / "runtime", manifest)
    reference = load_prompt_reference(PROMPT_ID, manifest, execution_scope=DEVELOPMENT_SMOKE)
    result: dict[str, object] = {
        "binding": {
            "baseline_sha": "b02ad1eb",
            "connected_source_sha256": hashlib.sha256(connected_bytes).hexdigest(),
            "review_source_sha256": hashlib.sha256(reviewed_bytes).hexdigest(),
            "model_id": MODEL_ID,
            "model_digest": installed[MODEL_ID],
            "sampling_temperature": 0.0,
            "sampling_seed": 1729,
            "prompt_content_hash": reference.content_hash,
            "call_limit": len(rows),
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label, arm, prompt_input, started_at_ms in rows:
        started = time.perf_counter()
        trial: dict[str, object] = {
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
                    run_id=f"planning-revision-input-{label}-{arm}",
                    now_ms=lambda started_at_ms=started_at_ms, started=started: (
                        started_at_ms + int((time.perf_counter() - started) * 1_000)
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
                    tool_argument_candidate_output_schema(prompt_input),
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
                }
            )
        trial["duration_ms"] = int((time.perf_counter() - started) * 1_000)
        cast(list[dict[str, object]], result["trials"]).append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, arm, trial["outcome"], trial["duration_ms"], flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connected", type=Path, required=True)
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.connected, args.reviewed, args.output)


if __name__ == "__main__":
    main()
