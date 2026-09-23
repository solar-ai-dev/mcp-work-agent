"""Evaluate a bounded second-pass finalizer over already recorded RU Output candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import cast

from evaluation.dataset_v8 import load_cases
from scripts.evaluate_ru_output_input_projection import EXPECTED_OUTPUTS
from scripts.evaluate_ru_source_status_prompt import EXPECTED_MODEL_DIGEST, MODEL_ID

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

PROMPT = Path(
    "evaluation/prompt_candidates/ru-output-selected-verification-v1/sources/"
    "request_understanding.verify_selected_output_responsibilities.md"
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _identity(item: dict[str, object]) -> tuple[str, str, tuple[str, ...]]:
    return (
        str(item["resource_type"]),
        str(item["effect"]),
        tuple(str(unit_id) for unit_id in cast(list[object], item["work_unit_ids"])),
    )


def _schema(proposed: list[dict[str, object]]) -> OutputSchemaDefinition:
    variants = []
    coverage = []
    for item in proposed:
        resource_type, effect, work_unit_ids = _identity(item)
        identity_properties = {
            "resource_type": {"const": resource_type},
            "effect": {"const": effect},
            "work_unit_ids": {"const": list(work_unit_ids)},
        }
        identity_required = ["resource_type", "effect", "work_unit_ids"]
        match = {
            "type": "object",
            "properties": identity_properties,
            "required": identity_required,
        }
        variants.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": [*identity_required, "disposition"],
                "properties": {
                    **identity_properties,
                    "disposition": {"enum": ["KEEP", "DROP"]},
                },
            }
        )
        coverage.append({"contains": match, "minContains": 1, "maxContains": 1})
    return OutputSchemaDefinition(
        schema_version="request-output-selected-verification-v1-eval",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["decisions"],
            "properties": {
                "decisions": {
                    "type": "array",
                    "minItems": len(proposed),
                    "maxItems": len(proposed),
                    "uniqueItems": True,
                    "allOf": coverage,
                    "items": {"oneOf": variants},
                }
            },
        },
    )


def _pairs(items: list[dict[str, object]]) -> list[list[str]]:
    return sorted([[str(item["resource_type"]), str(item["effect"])] for item in items])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-result", type=Path, action="append", required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260923)
    args = parser.parse_args()
    if args.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")
    client = OllamaHTTPClient()
    model = next(
        (item for item in client.list_installed_models() if item.model_id == MODEL_ID),
        None,
    )
    if model is None or model.digest != EXPECTED_MODEL_DIGEST:
        raise ValueError("local model digest differs from the fixed comparison")
    cases = load_cases()
    prompt_ref = load_prompt_reference(
        "request_understanding.identify_output_responsibilities",
        default_prompt_manifest_path(),
        execution_scope=DEVELOPMENT_SMOKE,
    )
    prompt_bytes = PROMPT.read_bytes()
    prompt_source = prompt_bytes.decode("utf-8").rstrip()
    candidate_ref = replace(
        prompt_ref,
        prompt_id="request_understanding.verify_selected_output_responsibilities",
        purpose="verify_selected_output_responsibilities",
        prompt_version="selected-verification-v1-eval",
        content_hash=hashlib.sha256(prompt_bytes).hexdigest(),
    )
    result: dict[str, object] = {
        "binding": {
            "model_id": MODEL_ID,
            "model_digest": model.digest,
            "temperature": 0.0,
            "seed": args.seed,
            "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "scope": "EVALUATION_ONLY_OUTPUT_OWNER_FINALIZATION",
            "provider_reads": 0,
            "provider_writes": 0,
        },
        "cases": [],
    }
    _write(args.result_path, result)
    records = cast(list[dict[str, object]], result["cases"])
    for trial, input_path in enumerate(args.input_result, start=1):
        source = json.loads(input_path.read_text(encoding="utf-8"))
        for case in source["cases"]:
            case_id = str(case["case_id"])
            atomic = case.get("atomic", [])
            owner_call = next(
                (
                    item
                    for item in atomic
                    if item.get("prompt_id")
                    == "request_understanding.identify_output_responsibilities"
                    and item.get("attempt") == "FIRST"
                ),
                None,
            )
            if owner_call is None:
                continue
            proposed = deepcopy(owner_call["structured_output"]["output_responsibilities"])
            projection = {
                "user_request": cases[case_id].raw["canonical_user_prompt"],
                "requested_work": owner_call["input"]["requested_work"],
                "proposed_outputs": proposed,
            }
            decisions: list[dict[str, object]] = []
            response_metrics = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0}
            errors: list[str] = []
            if proposed:
                schema = _schema(proposed)
                instruction_text = (
                    prompt_source
                    + "\n\nAllowed evaluation input projection (JSON):\n"
                    + json.dumps(
                        projection,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    + "\n"
                )
                response = client.invoke_structured(
                    endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                    model_id=MODEL_ID,
                    prompt_ref=candidate_ref,
                    prompt_input=projection,
                    output_schema=schema,
                    timeout_seconds=180,
                    instruction_text=instruction_text,
                    sampling_temperature=0.0,
                    sampling_seed=args.seed,
                )
                raw = json.loads(cast(str, response.content))
                errors = validate_output_schema(raw, schema.json_schema)
                decisions = raw.get("decisions", []) if isinstance(raw, dict) else []
                response_metrics = {
                    "calls": 1,
                    "input_tokens": response.input_tokens or 0,
                    "output_tokens": response.output_tokens or 0,
                    "latency_ms": response.latency_ms,
                }
            kept = [
                {key: decision[key] for key in ("resource_type", "effect", "work_unit_ids")}
                for decision in decisions
                if decision.get("disposition") == "KEEP"
            ]
            expected = EXPECTED_OUTPUTS.get(case_id, [])
            record = {
                "trial": trial,
                "source_result": str(input_path),
                "case_id": case_id,
                "expected_output_pairs": expected,
                "proposed_output_pairs": _pairs(proposed),
                "candidate_output_pairs": _pairs(kept),
                "baseline_semantic_valid": _pairs(proposed) == sorted(expected),
                "candidate_semantic_valid": not errors and _pairs(kept) == sorted(expected),
                "validation_errors": errors,
                "decision_output": decisions,
                "llm": response_metrics,
            }
            records.append(record)
            _write(args.result_path, result)
            print(
                json.dumps(
                    {
                        "trial": trial,
                        "case_id": case_id,
                        "proposed": record["proposed_output_pairs"],
                        "candidate": record["candidate_output_pairs"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
