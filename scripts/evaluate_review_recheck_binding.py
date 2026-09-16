"""Compare current-action binding on two frozen Review RECHECK inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from scripts.evaluate_review_decomposition_node import MODEL_ID, _runtime

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_recheck_output_schema,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget

LABELS = ("WRONG_DATE_023", "FORBIDDEN_ATTENDEE_023")
PROMPT_ID = "review.recheck_affected_dimensions"


def evaluate(source_path: Path, connected_path: Path, output_path: Path) -> None:
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    digest = next(
        (
            item.digest
            for item in OllamaHTTPClient().list_installed_models()
            if item.model_id == MODEL_ID
        ),
        None,
    )
    if digest != source["binding"]["model_digest"]:
        raise ValueError("model digest differs from frozen cycle")
    cases = {item["label"]: item for item in source["cases"]}
    connected = {
        item["case_id"]: item
        for item in json.loads(connected_path.read_text(encoding="utf-8"))["cases"]
    }
    runtime = _runtime(
        Path(tempfile.mkdtemp(prefix="gwa-review-binding-")),
        default_prompt_manifest_path(),
    )
    reference = load_prompt_reference(
        PROMPT_ID, default_prompt_manifest_path(), execution_scope=DEVELOPMENT_SMOKE
    )
    result: dict[str, Any] = {
        "binding": {
            "source_cycle_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "model_id": MODEL_ID,
            "model_digest": digest,
            "prompt_hash": reference.content_hash,
            "temperature": 0.0,
            "seed": 1729,
            "max_llm_calls": 2,
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label in LABELS:
        started_at_ms = connected[cases[label]["source_case"]]["reference_started_at_ms"]
        stage = next(
            item for item in cases[label]["stages"] if item["stage"] == "review_recheck"
        )
        original = stage["inference_details"][0]["prompt_input"]
        prompt_input = json.loads(json.dumps(original, ensure_ascii=False))
        routes = set(prompt_input["affected_route_ids"])
        current_action_ids = [
            action["action_id"]
            for action in prompt_input["planning_result"]["actions"]
            if action["route_id"] in routes
        ]
        if not current_action_ids or set(current_action_ids) == set(
            prompt_input["affected_action_ids"]
        ):
            raise ValueError(f"{label} does not contain stale action bindings")
        prompt_input["affected_action_ids"] = current_action_ids
        started = time.perf_counter()
        trial: dict[str, Any] = {
            "label": label,
            "old_action_ids": original["affected_action_ids"],
            "current_action_ids": current_action_ids,
            "old_input_sha256": _fingerprint(original),
            "candidate_input_sha256": _fingerprint(prompt_input),
            "prompt_input": prompt_input,
        }
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-recheck-binding-{label}",
                    now_ms=lambda started=started, base=started_at_ms: base
                    + int((time.perf_counter() - started) * 1_000),
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
            trial.update(
                {"outcome": "FAILED", "error_type": type(error).__name__, "message": str(error)}
            )
        trial["duration_ms"] = int((time.perf_counter() - started) * 1_000)
        result["trials"].append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, trial["outcome"], flush=True)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--connected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.source, args.connected, args.output)


if __name__ == "__main__":
    main()
