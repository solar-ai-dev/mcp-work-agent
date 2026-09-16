"""Compare Review decisions with Work Analysis omitted from frozen connected inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from scripts.evaluate_review_decomposition_node import MODEL_ID, PROMPT_ID, _runtime
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


def evaluate(source_path: Path, output_path: Path) -> dict[str, object]:
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    installed = {
        item.model_id: item.digest for item in OllamaHTTPClient().list_installed_models()
    }
    if installed.get(MODEL_ID) != source["binding"]["model_digest"]:
        raise ValueError("installed model digest differs from connected input")
    cases = [
        item for item in cast(list[dict[str, Any]], source["cases"])
        if item["case_id"] in {"CASE-CORE-023", "CASE-CORE-028"}
    ]
    if len(cases) != 2:
        raise ValueError("predeclared connected Review inputs changed")
    root = Path(tempfile.mkdtemp(prefix="gwa-review-work-analysis-projection-"))
    manifest = _candidate_manifest(root, optional_field="run_reference_time")
    runtime = _runtime(root / "runtime", manifest)
    reference = load_prompt_reference(PROMPT_ID, manifest, execution_scope=DEVELOPMENT_SMOKE)
    schema = review_inspector_output_schema(PROMPT_ID)
    result: dict[str, object] = {
        "binding": {
            "baseline_sha": "2523f699",
            "connected_source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "model_id": MODEL_ID,
            "model_digest": installed[MODEL_ID],
            "sampling_temperature": 0.0,
            "sampling_seed": 1729,
            "prompt_content_hash": reference.content_hash,
            "call_limit": 2,
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        details = [
            item for item in case["work_analysis"]["downstream"]["inference_details"]
            if item["prompt_id"] == PROMPT_ID
        ]
        if len(details) != 1:
            raise ValueError("predeclared Review prompt input missing")
        prompt_input = deepcopy(details[0]["prompt_input"])
        if "work_analysis" not in prompt_input:
            raise ValueError("Work Analysis is absent from the baseline")
        del prompt_input["work_analysis"]
        started_at_ms = cast(int, case["reference_started_at_ms"])
        started = time.perf_counter()
        trial: dict[str, object] = {
            "case_id": case["case_id"],
            "input_sha256": hashlib.sha256(
                json.dumps(prompt_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "prompt_input": prompt_input,
        }
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-work-analysis-projection-{case['case_id']}",
                    now_ms=lambda started_at_ms=started_at_ms, started=started: (
                        started_at_ms + int((time.perf_counter() - started) * 1_000)
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
                }
            )
        trial["duration_ms"] = int((time.perf_counter() - started) * 1_000)
        cast(list[dict[str, object]], result["trials"]).append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(case["case_id"], trial["outcome"], trial["duration_ms"], flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.source, args.output)


if __name__ == "__main__":
    main()
