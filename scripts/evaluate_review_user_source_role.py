"""Compare separating current-Run original request from external Review evidence."""

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
from scripts.evaluate_review_edit_provenance import _inputs
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


def separate_original_user_request(prompt_input: dict[str, Any]) -> dict[str, Any]:
    projected = deepcopy(prompt_input)
    evidence = projected["evidence"]
    user_items = [item for item in evidence if item.get("origin_type") == "USER_MESSAGE"]
    if len(user_items) != 1:
        raise ValueError("Review requires exactly one current user message")
    original = user_items[0]
    if not isinstance(original.get("message_id"), str) or not original["message_id"]:
        raise ValueError("Review user message ID is required")
    if not isinstance(original.get("excerpt"), str) or not original["excerpt"]:
        raise ValueError("Review original request text is required")
    projected["evidence"] = [
        item for item in evidence if item.get("origin_type") != "USER_MESSAGE"
    ]
    projected["original_user_request"] = original
    return projected


def evaluate(cycle_path: Path, baseline_path: Path, output_path: Path) -> None:
    cycle_bytes = cycle_path.read_bytes()
    cycle = json.loads(cycle_bytes)
    baseline_bytes = baseline_path.read_bytes()
    baseline = json.loads(baseline_bytes)
    rows = _inputs(cycle)
    if len(rows) != 8 or len(baseline["trials"]) != 16:
        raise ValueError("frozen eight-input baseline changed")
    digest = next(
        (
            item.digest
            for item in OllamaHTTPClient().list_installed_models()
            if item.model_id == MODEL_ID
        ),
        None,
    )
    if digest != cycle["binding"]["model_digest"] or digest != baseline["binding"]["model_digest"]:
        raise ValueError("installed model differs from frozen comparison")
    baseline_trials = {item["label"]: item for item in baseline["trials"] if item["arm"] == "A"}
    root = Path(tempfile.mkdtemp(prefix="gwa-review-user-source-role-"))
    manifest = _candidate_manifest(
        root, optional_field="original_user_request", prompt_id=PROMPT_ID
    )
    runtime = _runtime(root / "runtime", manifest)
    reference = load_prompt_reference(PROMPT_ID, manifest, execution_scope=DEVELOPMENT_SMOKE)
    if reference.content_hash != baseline["binding"]["prompt_hash"]:
        raise ValueError("baseline and candidate Prompt source changed")
    schema = review_inspector_output_schema(PROMPT_ID)
    result: dict[str, Any] = {
        "binding": {
            "baseline_sha": "0407b006",
            "cycle_sha256": hashlib.sha256(cycle_bytes).hexdigest(),
            "baseline_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
            "model_digest": digest,
            "prompt_hash": reference.content_hash,
            "output_schema_version": schema.schema_version,
            "temperature": 0.0,
            "seed": 1729,
            "call_limit": 8,
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label, original, _ in rows:
        expected_hash = hashlib.sha256(
            json.dumps(original, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if baseline_trials[label]["input_sha256"] != expected_hash:
            raise ValueError(f"{label} baseline input fingerprint changed")
        prompt_input = separate_original_user_request(original)
        trial: dict[str, Any] = {
            "label": label,
            "arm": "B",
            "baseline_input_sha256": expected_hash,
            "input_sha256": hashlib.sha256(
                json.dumps(prompt_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "prompt_input": prompt_input,
        }
        started = time.perf_counter()
        started_at_ms = 1786060800000
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-user-source-role-{label}",
                    now_ms=lambda start=started, base=started_at_ms: base
                    + int((time.perf_counter() - start) * 1000),
                ),
                provider_dispatch_budget_scope(
                    build_default_run_budget(started_at_ms=started_at_ms)
                ),
            ):
                inference = runtime.infer("LOCAL_GPU", reference, prompt_input, schema)
            trial.update(
                outcome="COMPLETED",
                structured_output=validate_review_inspector_result(
                    inference.structured_output, expected_dimension=PROMPT_ID
                ),
                fallback_reason=inference.fallback_reason,
                input_tokens=inference.input_tokens,
                output_tokens=inference.output_tokens,
                provider_latency_ms=inference.latency_ms,
            )
        except Exception as error:
            code = getattr(error, "code", None)
            trial.update(
                outcome="FAILED",
                error_type=type(error).__name__,
                error_code=getattr(code, "value", None),
                message=str(error),
            )
        trial["duration_ms"] = int((time.perf_counter() - started) * 1000)
        cast(list[dict[str, Any]], result["trials"]).append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, trial["outcome"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.cycle, args.baseline, args.output)


if __name__ == "__main__":
    main()
