"""Evaluate a bounded two-stage requested-work decomposition candidate."""

from __future__ import annotations

import hashlib
import json
import time
from argparse import ArgumentParser
from pathlib import Path
from typing import cast

from evaluation.dataset_v8 import load_cases, normalized_sha256
from scripts.evaluate_ru_requested_work_decomposition import (
    CORE24_CASE_IDS,
    DATASET,
    DECOMPOSITION_SCHEMA,
    EXPECTED_MODEL_DIGEST,
    MODEL_ID,
    _git_head,
    _sha256,
    _validate_decomposition,
    _write,
)

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)

PROMPT_ROOT = Path(
    "evaluation/prompt_candidates/ru-requested-work-decomposition-two-stage-v1/sources"
)
IDENTIFY_PROMPT = PROMPT_ROOT / "request_understanding.identify_independent_results.md"
MATERIALIZE_PROMPT = PROMPT_ROOT / "request_understanding.materialize_work_units.md"
SEMANTIC_STATE_PROMPT_ROOT = Path(
    "evaluation/prompt_candidates/"
    "ru-requested-work-decomposition-two-stage-semantic-state-v1/sources"
)
SEMANTIC_STATE_IDENTIFY_PROMPT = (
    SEMANTIC_STATE_PROMPT_ROOT / "request_understanding.identify_independent_results.md"
)
SEMANTIC_STATE_MATERIALIZE_PROMPT = (
    SEMANTIC_STATE_PROMPT_ROOT / "request_understanding.materialize_work_units.md"
)

REQUESTED_EFFECTS = ["ANSWER", "DRAFT", "SEND", "CREATE", "UPDATE", "DELETE"]


def _optional_semantic_properties() -> dict[str, object]:
    return {
        "source_scopes": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "description": "User-specified source or input scopes needed for this result.",
            "items": {"type": "string", "minLength": 1},
        },
        "targets": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "description": "User-specified targets or recipients for this result.",
            "items": {"type": "string", "minLength": 1},
        },
        "temporal_constraints": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "description": "Explicit temporal constraints that belong to this result.",
            "items": {"type": "string", "minLength": 1},
        },
        "quantity_constraints": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "description": "Explicit quantity constraints that belong to this result.",
            "items": {"type": "string", "minLength": 1},
        },
        "prohibitions": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "description": "Explicit user prohibitions that constrain this result.",
            "items": {"type": "string", "minLength": 1},
        },
        "requested_effects": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "description": "User-requested response or external effects for this result.",
            "items": {"enum": REQUESTED_EFFECTS},
        },
    }


IDENTIFIED_RESULTS_SCHEMA = OutputSchemaDefinition(
    schema_version="requested-independent-results-v1-eval",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["identified_results"],
        "properties": {
            "identified_results": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["result_id", "objective"],
                    "properties": {
                        "result_id": {"type": "string", "minLength": 1},
                        "objective": {"type": "string", "minLength": 1},
                    },
                },
            }
        },
    },
)

SEMANTIC_STATE_IDENTIFIED_RESULTS_SCHEMA = OutputSchemaDefinition(
    schema_version="requested-independent-results-semantic-state-v1-eval",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["identified_results"],
        "properties": {
            "identified_results": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["result_id", "objective"],
                    "properties": {
                        "result_id": {"type": "string", "minLength": 1},
                        "objective": {"type": "string", "minLength": 1},
                        **_optional_semantic_properties(),
                    },
                },
            }
        },
    },
)

SEMANTIC_STATE_DECOMPOSITION_SCHEMA = OutputSchemaDefinition(
    schema_version="requested-work-decomposition-semantic-state-v1-eval",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["work_units", "work_relations"],
        "properties": {
            "work_units": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["unit_id", "objective"],
                    "properties": {
                        "unit_id": {"type": "string", "minLength": 1},
                        "objective": {"type": "string", "minLength": 1},
                        **_optional_semantic_properties(),
                    },
                },
            },
            "work_relations": DECOMPOSITION_SCHEMA.json_schema["properties"]["work_relations"],
        },
    },
)


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--sampling-seed", type=int, default=20260920)
    parser.add_argument("--semantic-state", action="store_true")
    arguments = parser.parse_args()
    if arguments.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")

    case_ids = arguments.case or list(CORE24_CASE_IDS)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate Case ID")
    if any(case_id not in CORE24_CASE_IDS for case_id in case_ids):
        raise ValueError("requested Case is not in the fixed Core comparison set")

    cases = load_cases()
    identify_prompt_path = (
        SEMANTIC_STATE_IDENTIFY_PROMPT if arguments.semantic_state else IDENTIFY_PROMPT
    )
    materialize_prompt_path = (
        SEMANTIC_STATE_MATERIALIZE_PROMPT if arguments.semantic_state else MATERIALIZE_PROMPT
    )
    identify_schema = (
        SEMANTIC_STATE_IDENTIFIED_RESULTS_SCHEMA
        if arguments.semantic_state
        else IDENTIFIED_RESULTS_SCHEMA
    )
    decomposition_schema = (
        SEMANTIC_STATE_DECOMPOSITION_SCHEMA if arguments.semantic_state else DECOMPOSITION_SCHEMA
    )
    candidate_id = (
        "ru-requested-work-decomposition-two-stage-semantic-state-v1"
        if arguments.semantic_state
        else "ru-requested-work-decomposition-two-stage-v1"
    )
    prompt_version = (
        "requested-work-decomposition-two-stage-semantic-state-v1-eval"
        if arguments.semantic_state
        else "requested-work-decomposition-two-stage-v1-eval"
    )
    identify_prompt = identify_prompt_path.read_text(encoding="utf-8").rstrip()
    materialize_prompt = materialize_prompt_path.read_text(encoding="utf-8").rstrip()
    identify_hash = hashlib.sha256(identify_prompt_path.read_bytes()).hexdigest()
    materialize_hash = hashlib.sha256(materialize_prompt_path.read_bytes()).hexdigest()
    canonical_authority_hash = _sha256(
        {
            case_id: {
                "canonical_user_prompt": cases[case_id].raw["canonical_user_prompt"],
                "required_semantics": cases[case_id].raw["evaluation_gold"]["required_semantics"],
                "forbidden_semantics": cases[case_id].raw["evaluation_gold"]["forbidden_semantics"],
            }
            for case_id in CORE24_CASE_IDS
        }
    )

    client = OllamaHTTPClient()
    model_digest = next(
        (model.digest for model in client.list_installed_models() if model.model_id == MODEL_ID),
        None,
    )
    if model_digest != EXPECTED_MODEL_DIGEST:
        raise ValueError("local model digest differs from the preregistered comparison")

    identify_ref = _prompt_ref(
        prompt_id="request_understanding.identify_independent_results",
        prompt_hash=identify_hash,
        prompt_version=prompt_version,
        input_schema_version="user-request-only-v1",
        output_schema_version=identify_schema.schema_version,
    )
    materialize_ref = _prompt_ref(
        prompt_id="request_understanding.materialize_work_units",
        prompt_hash=materialize_hash,
        prompt_version=prompt_version,
        input_schema_version="user-request-plus-identified-results-v1",
        output_schema_version=decomposition_schema.schema_version,
    )
    result: dict[str, object] = {
        "binding": {
            "product_sha": _git_head(),
            "dataset_sha256": normalized_sha256(DATASET),
            "canonical_authority_sha256": canonical_authority_hash,
            "identify_prompt_sha256": identify_hash,
            "materialize_prompt_sha256": materialize_hash,
            "candidate_id": candidate_id,
            "model_id": MODEL_ID,
            "model_digest": model_digest,
            "temperature": 0.0,
            "seed": arguments.sampling_seed,
            "scope": "EVALUATION_ONLY_RU_REQUESTED_WORK_DECOMPOSITION",
            "candidate_calls_per_case": 2,
            "provider_read_count": 0,
            "provider_write_count": 0,
        },
        "summary": {
            "case_count": len(case_ids),
            "identify_schema_valid": 0,
            "materialize_schema_valid": 0,
            "materialize_exact_carry_matches": 0,
        },
        "cases": [],
    }
    _write(arguments.result_path, result)
    records = cast(list[dict[str, object]], result["cases"])
    summary = cast(dict[str, object], result["summary"])
    for case_id in case_ids:
        raw = cases[case_id].raw
        if raw.get("split") != "CORE":
            raise ValueError(f"{case_id}: Holdout/Stress is not allowed for tuning")
        request = str(raw["canonical_user_prompt"])

        identify_started = time.perf_counter()
        identify_response = client.invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=MODEL_ID,
            prompt_ref=identify_ref,
            prompt_input={"user_request": request},
            output_schema=identify_schema,
            timeout_seconds=180,
            instruction_text=identify_prompt,
            sampling_temperature=0.0,
            sampling_seed=arguments.sampling_seed,
        )
        identified = json.loads(cast(str, identify_response.content))
        identify_errors = [
            *validate_output_schema(identified, identify_schema.json_schema),
            *_validate_identified_results(identified),
        ]
        identified_results = (
            identified.get("identified_results", []) if isinstance(identified, dict) else []
        )
        identify_wall_ms = int((time.perf_counter() - identify_started) * 1_000)

        materialize_started = time.perf_counter()
        materialize_response = client.invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=MODEL_ID,
            prompt_ref=materialize_ref,
            prompt_input={
                "user_request": request,
                "identified_results": identified_results,
            },
            output_schema=decomposition_schema,
            timeout_seconds=180,
            instruction_text=materialize_prompt,
            sampling_temperature=0.0,
            sampling_seed=arguments.sampling_seed,
        )
        candidate = json.loads(cast(str, materialize_response.content))
        materialize_errors = [
            *validate_output_schema(candidate, decomposition_schema.json_schema),
            *_validate_decomposition(candidate),
        ]
        units = candidate.get("work_units", []) if isinstance(candidate, dict) else []
        relations = candidate.get("work_relations", []) if isinstance(candidate, dict) else []
        carry_matches = _has_exact_carry(identified_results, units)
        materialize_wall_ms = int((time.perf_counter() - materialize_started) * 1_000)

        records.append(
            {
                "case_id": case_id,
                "category": raw["category"],
                "user_request": request,
                "canonical_authority": {
                    "required_semantics": raw["evaluation_gold"]["required_semantics"],
                    "forbidden_semantics": raw["evaluation_gold"]["forbidden_semantics"],
                },
                "identify": {
                    "candidate": identified,
                    "schema_errors": identify_errors,
                    "input_tokens": identify_response.input_tokens,
                    "output_tokens": identify_response.output_tokens,
                    "latency_ms": identify_response.latency_ms,
                    "wall_ms": identify_wall_ms,
                },
                "materialize": {
                    "candidate": candidate,
                    "schema_errors": materialize_errors,
                    "exact_carry_matches": carry_matches,
                    "input_tokens": materialize_response.input_tokens,
                    "output_tokens": materialize_response.output_tokens,
                    "latency_ms": materialize_response.latency_ms,
                    "wall_ms": materialize_wall_ms,
                },
            }
        )
        summary["identify_schema_valid"] = cast(int, summary["identify_schema_valid"]) + int(
            not identify_errors
        )
        summary["materialize_schema_valid"] = cast(int, summary["materialize_schema_valid"]) + int(
            not materialize_errors
        )
        summary["materialize_exact_carry_matches"] = cast(
            int, summary["materialize_exact_carry_matches"]
        ) + int(carry_matches)
        _write(arguments.result_path, result)
        print(
            json.dumps(
                {
                    "case_id": case_id,
                    "identified_results": len(identified_results),
                    "actual_units": len(units),
                    "actual_relations": len(relations),
                    "identify_schema_valid": not identify_errors,
                    "materialize_schema_valid": not materialize_errors,
                    "exact_carry_matches": carry_matches,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


def _prompt_ref(
    *,
    prompt_id: str,
    prompt_hash: str,
    prompt_version: str,
    input_schema_version: str,
    output_schema_version: str,
) -> PromptReference:
    return PromptReference(
        prompt_bundle_version="evaluation-only",
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        content_hash=prompt_hash,
        agent_role="REQUEST_UNDERSTANDING",
        subgraph_name="request_understanding",
        node_name=prompt_id.rsplit(".", 1)[-1],
        node_state="INITIAL",
        purpose="EVALUATION_ONLY_REQUESTED_WORK_DECOMPOSITION",
        input_schema_version=input_schema_version,
        output_schema_version=output_schema_version,
    )


def _validate_identified_results(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["candidate is not an object"]
    identified_results = value.get("identified_results")
    if not isinstance(identified_results, list):
        return []
    result_ids = [
        str(item.get("result_id"))
        for item in identified_results
        if isinstance(item, dict) and isinstance(item.get("result_id"), str)
    ]
    if len(result_ids) != len(set(result_ids)):
        return ["identified result ids must be unique"]
    return []


def _has_exact_carry(identified_results: object, work_units: object) -> bool:
    if not isinstance(identified_results, list) or not isinstance(work_units, list):
        return False
    expected = []
    for item in identified_results:
        if not isinstance(item, dict):
            continue
        carried = dict(item)
        carried["unit_id"] = carried.pop("result_id", None)
        expected.append(carried)
    actual = [item for item in work_units if isinstance(item, dict)]
    return len(expected) == len(identified_results) and expected == actual


if __name__ == "__main__":
    main()
