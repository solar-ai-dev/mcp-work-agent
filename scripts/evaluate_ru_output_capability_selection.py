"""Compare compact capability selection against recorded RU Output owner calls."""

from __future__ import annotations

import argparse
import hashlib
import json
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
    "evaluation/prompt_candidates/ru-output-capability-selection-v1/sources/"
    "request_understanding.select_output_capabilities.md"
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _pairs(value: object) -> list[list[str]]:
    if not isinstance(value, dict):
        return []
    raw = value.get("output_responsibilities")
    if not isinstance(raw, list):
        return []
    return sorted(
        [
            [str(item["resource_type"]), str(item["effect"])]
            for item in raw
            if isinstance(item, dict)
        ]
    )


def _schema(capability_ids: list[str], work_unit_ids: list[str]) -> OutputSchemaDefinition:
    return OutputSchemaDefinition(
        schema_version="request-output-capability-selection-v1-eval",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["selected_capabilities"],
            "properties": {
                "selected_capabilities": {
                    "type": "array",
                    "maxItems": len(capability_ids) * len(work_unit_ids),
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["capability_id", "work_unit_ids"],
                        "properties": {
                            "capability_id": {"enum": capability_ids},
                            "work_unit_ids": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"enum": work_unit_ids},
                            },
                        },
                    },
                }
            },
        },
    )


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
    base_ref = load_prompt_reference(
        "request_understanding.identify_output_responsibilities",
        default_prompt_manifest_path(),
        execution_scope=DEVELOPMENT_SMOKE,
    )
    prompt_bytes = PROMPT.read_bytes()
    prompt_source = prompt_bytes.decode("utf-8").rstrip()
    candidate_ref = replace(
        base_ref,
        prompt_id="request_understanding.select_output_capabilities",
        purpose="select_output_capabilities",
        prompt_version="output-capability-selection-v1-eval",
        content_hash=hashlib.sha256(prompt_bytes).hexdigest(),
    )
    cases = load_cases()
    result: dict[str, object] = {
        "binding": {
            "model_id": MODEL_ID,
            "model_digest": model.digest,
            "temperature": 0.0,
            "seed": args.seed,
            "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "candidate": "OUTPUT_CAPABILITY_SELECTION_V1",
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
            owner_call = next(
                (
                    item
                    for item in case.get("atomic", [])
                    if item.get("prompt_id")
                    == "request_understanding.identify_output_responsibilities"
                    and item.get("attempt") == "FIRST"
                ),
                None,
            )
            if owner_call is None:
                continue
            owner_input = owner_call["input"]
            capabilities = [
                {
                    "capability_id": (
                        f"{candidate['resource_type']}__{effect}"
                    ),
                    "resource_type": candidate["resource_type"],
                    "effect": effect,
                }
                for candidate in owner_input["output_candidates"]
                for effect in candidate["allowed_output_effects"]
            ]
            by_id = {item["capability_id"]: item for item in capabilities}
            work_unit_ids = [
                str(unit["unit_id"])
                for unit in owner_input["requested_work"]["work_units"]
            ]
            projection = {
                "user_request": owner_input["user_request"],
                "selected_resource_refs": owner_input["selected_resource_refs"],
                "requested_work": owner_input["requested_work"],
                "goal_candidate": owner_input["goal_candidate"],
                "effect_prohibitions": owner_input["effect_prohibitions"],
                "output_capabilities": capabilities,
            }
            schema = _schema(list(by_id), work_unit_ids)
            instruction = (
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
                instruction_text=instruction,
                sampling_temperature=0.0,
                sampling_seed=args.seed,
            )
            raw = json.loads(cast(str, response.content))
            errors = validate_output_schema(raw, schema.json_schema)
            selected = raw.get("selected_capabilities", []) if isinstance(raw, dict) else []
            candidate = {
                "output_responsibilities": [
                    {
                        "resource_type": by_id[item["capability_id"]]["resource_type"],
                        "effect": by_id[item["capability_id"]]["effect"],
                        "work_unit_ids": item["work_unit_ids"],
                    }
                    for item in selected
                ]
            }
            expected = EXPECTED_OUTPUTS.get(case_id, [])
            baseline_pairs = _pairs(owner_call["structured_output"])
            candidate_pairs = _pairs(candidate)
            record = {
                "trial": trial,
                "source_result": str(input_path),
                "case_id": case_id,
                "expected_output_pairs": expected,
                "baseline_output_pairs": baseline_pairs,
                "candidate_output_pairs": candidate_pairs,
                "baseline_semantic_valid": baseline_pairs == sorted(expected),
                "candidate_semantic_valid": not errors and candidate_pairs == sorted(expected),
                "validation_errors": errors,
                "candidate_output": candidate,
                "raw_output": raw,
                "llm": {
                    "calls": 1,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "latency_ms": response.latency_ms,
                },
                "canonical_required_semantics": cases[case_id].gold.get(
                    "required_semantics"
                ),
                "canonical_forbidden_semantics": cases[case_id].gold.get(
                    "forbidden_semantics"
                ),
            }
            records.append(record)
            _write(args.result_path, result)
            print(
                json.dumps(
                    {
                        "trial": trial,
                        "case_id": case_id,
                        "baseline": baseline_pairs,
                        "candidate": candidate_pairs,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
