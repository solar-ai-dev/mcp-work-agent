"""Replay two frozen corrected RECHECK inputs against the active output schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any, cast

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

PROMPT_ID = "review.recheck_affected_dimensions"
LABELS = ("WRONG_DATE_023", "FORBIDDEN_ATTENDEE_023")


def evaluate(source_path: Path, output_path: Path) -> None:
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    cases = {item["label"]: item for item in source["cases"]}
    digest = next(
        (
            item.digest
            for item in OllamaHTTPClient().list_installed_models()
            if item.model_id == MODEL_ID
        ),
        None,
    )
    if digest != source["binding"]["model_digest"]:
        raise ValueError("installed model differs from frozen source")
    root = Path(tempfile.mkdtemp(prefix="gwa-review-recheck-schema-"))
    runtime = _runtime(root / "runtime", default_prompt_manifest_path())
    reference = load_prompt_reference(
        PROMPT_ID, default_prompt_manifest_path(), execution_scope=DEVELOPMENT_SMOKE
    )
    dispatch_count = 0
    before_dispatch = runtime.before_provider_dispatch

    def count_dispatch() -> None:
        nonlocal dispatch_count
        before_dispatch()
        dispatch_count += 1

    runtime.before_provider_dispatch = count_dispatch
    result: dict[str, Any] = {
        "binding": {
            "baseline_sha": "021224fa",
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "model_digest": digest,
            "prompt_hash": reference.content_hash,
            "temperature": 0.0,
            "seed": 1729,
            "call_limit": 2,
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for label in LABELS:
        case = cases[label]
        recheck = next(stage for stage in case["stages"] if stage["stage"] == "review_recheck")
        original = next(
            item for item in recheck["inference_details"] if item["prompt_id"] == PROMPT_ID
        )
        prompt_input = original["prompt_input"]
        historical = prompt_input["proposal_transition"]["historical_review_issues"]
        schema = review_recheck_output_schema(
            tuple(prompt_input["affected_dimensions"]), len(historical)
        )
        trial: dict[str, Any] = {
            "label": label,
            "input_sha256": hashlib.sha256(
                json.dumps(prompt_input, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest(),
            "prompt_input": prompt_input,
            "previous_output": original["structured_output"],
            "schema_version": schema.schema_version,
        }
        before = dispatch_count
        started = time.perf_counter()
        base_ms = 1786060800000
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"recheck-schema-{label}",
                    now_ms=lambda start=started, base=base_ms: base
                    + int((time.perf_counter() - start) * 1000),
                ),
                provider_dispatch_budget_scope(build_default_run_budget(started_at_ms=base_ms)),
            ):
                inference = runtime.infer("LOCAL_GPU", reference, prompt_input, schema)
            trial.update(
                outcome="COMPLETED",
                structured_output=inference.structured_output,
                input_tokens=inference.input_tokens,
                output_tokens=inference.output_tokens,
                provider_latency_ms=inference.latency_ms,
                fallback_reason=inference.fallback_reason,
            )
        except Exception as error:
            code = getattr(error, "code", None)
            trial.update(
                outcome="FAILED",
                error_type=type(error).__name__,
                error_code=getattr(code, "value", None),
                message=str(error),
            )
        trial["provider_dispatches"] = dispatch_count - before
        trial["duration_ms"] = int((time.perf_counter() - started) * 1000)
        cast(list[dict[str, Any]], result["trials"]).append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, trial["outcome"], trial["provider_dispatches"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.source, args.output)


if __name__ == "__main__":
    main()
