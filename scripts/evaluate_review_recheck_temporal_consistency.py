"""Replay frozen RECHECK inputs with the adopted initial temporal projection."""

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

from google_work_agent.adapters.langgraph.subgraphs.review.projections.inspect_goal_and_evidence_projection import (  # noqa: E501
    _is_event_time_only,
    _separate_gmail_receipt_metadata,
)
from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.project_run_reference_time import (
    project_run_reference_time,
)
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
    ("WRONG_DATE_023", "A"),
    ("WRONG_DATE_023", "B"),
    ("FORBIDDEN_ATTENDEE_023", "B"),
    ("FORBIDDEN_ATTENDEE_023", "A"),
)


def temporal_projection(prompt_input: dict[str, Any], started_at_ms: int) -> dict[str, Any]:
    """Share initial Goal's already-adopted EVENT_TIME boundary with RECHECK."""
    result = deepcopy(prompt_input)
    if (
        result.get("confirmation_response") is not None
        or result.get("user_action_modifications")
        or not _is_event_time_only(result["request_intent"])
    ):
        return result
    evidence, separated = _separate_gmail_receipt_metadata(result["evidence"])
    if not separated:
        return result
    reference = project_run_reference_time({"started_at_ms": started_at_ms})
    if reference is None:
        return result
    result["evidence"] = evidence
    result["run_reference_time"] = reference
    return result


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _static_contrasts(prompt_input: dict[str, Any], started_at_ms: int) -> dict[str, bool]:
    variants: dict[str, dict[str, Any]] = {}
    for label, axes in (
        ("message_time", ["MESSAGE_TIME"]),
        ("mixed_time", ["EVENT_TIME", "MESSAGE_TIME"]),
    ):
        variant = deepcopy(prompt_input)
        for constraint in variant["request_intent"]["constraints"]:
            if constraint.get("field") == "temporal_axis":
                constraint["value"] = axes
        variants[label] = variant
    malformed = deepcopy(prompt_input)
    for item in malformed["evidence"]:
        excerpt = item.get("excerpt")
        if isinstance(excerpt, str) and "Received: " in excerpt:
            item["excerpt"] = excerpt.replace("Received: ", "Received on ", 1)
            break
    variants["unrecognized_envelope"] = malformed
    return {
        label: temporal_projection(value, started_at_ms) == value
        for label, value in variants.items()
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
    root = Path(tempfile.mkdtemp(prefix="gwa-review-recheck-temporal-"))
    manifest = _candidate_manifest(root, optional_field="run_reference_time", prompt_id=PROMPT_ID)
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
    for label, arm in ORDER:
        case = cases[label]
        source = upstream[case["source_case"]]
        started_at_ms = source["reference_started_at_ms"]
        original = next(
            item["prompt_input"]
            for item in case["stages"][-1]["inference_details"]
            if item["prompt_id"] == PROMPT_ID
        )
        if arm == "B":
            prompt_input = temporal_projection(original, started_at_ms)
            if prompt_input == original:
                raise ValueError(f"{label} temporal projection was not applied")
        else:
            prompt_input = deepcopy(original)
        started = time.perf_counter()
        trial: dict[str, Any] = {
            "label": label,
            "arm": arm,
            "input_sha256": _fingerprint(prompt_input),
            "static_contrasts": _static_contrasts(original, started_at_ms),
            "prompt_input": prompt_input,
        }
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-recheck-temporal-{label}-{arm}",
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
        print(label, arm, trial["outcome"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", type=Path, required=True)
    parser.add_argument("--connected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.cycle, args.connected, args.output)


if __name__ == "__main__":
    main()
