"""Evaluate a bounded two-stage requested-work decomposition candidate."""

from __future__ import annotations

import hashlib
import json
import time
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
from typing import cast

from evaluation.dataset_v8 import load_cases, normalized_sha256
from scripts.evaluate_ru_requested_work_decomposition import (
    CORE24_EXPECTATIONS,
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


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--sampling-seed", type=int, default=20260920)
    arguments = parser.parse_args()
    if arguments.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")

    case_ids = arguments.case or list(CORE24_EXPECTATIONS)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate Case ID")
    if any(case_id not in CORE24_EXPECTATIONS for case_id in case_ids):
        raise ValueError("requested Case is not in the preregistered Core projection")

    cases = load_cases()
    identify_prompt = IDENTIFY_PROMPT.read_text(encoding="utf-8").rstrip()
    materialize_prompt = MATERIALIZE_PROMPT.read_text(encoding="utf-8").rstrip()
    identify_hash = hashlib.sha256(IDENTIFY_PROMPT.read_bytes()).hexdigest()
    materialize_hash = hashlib.sha256(MATERIALIZE_PROMPT.read_bytes()).hexdigest()
    expectation_hash = _sha256(
        {
            case_id: {
                "expected_units": expectation.expected_units,
                "expected_relations": expectation.expected_relations,
            }
            for case_id, expectation in CORE24_EXPECTATIONS.items()
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
        input_schema_version="user-request-only-v1",
        output_schema_version=IDENTIFIED_RESULTS_SCHEMA.schema_version,
    )
    materialize_ref = _prompt_ref(
        prompt_id="request_understanding.materialize_work_units",
        prompt_hash=materialize_hash,
        input_schema_version="user-request-plus-identified-results-v1",
        output_schema_version=DECOMPOSITION_SCHEMA.schema_version,
    )
    result: dict[str, object] = {
        "binding": {
            "product_sha": _git_head(),
            "dataset_sha256": normalized_sha256(DATASET),
            "expectation_sha256": expectation_hash,
            "identify_prompt_sha256": identify_hash,
            "materialize_prompt_sha256": materialize_hash,
            "candidate_id": "ru-requested-work-decomposition-two-stage-v1",
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
            "identify_boundary_matches": 0,
            "materialize_schema_valid": 0,
            "materialize_exact_carry_matches": 0,
            "candidate_structure_matches": 0,
            "relation_required_matches": 0,
            "first_divergence_counts": {},
        },
        "cases": [],
    }
    _write(arguments.result_path, result)
    records = cast(list[dict[str, object]], result["cases"])
    summary = cast(dict[str, object], result["summary"])
    divergence_counts: Counter[str] = Counter()

    for case_id in case_ids:
        raw = cases[case_id].raw
        if raw.get("split") != "CORE":
            raise ValueError(f"{case_id}: Holdout/Stress is not allowed for tuning")
        expectation = CORE24_EXPECTATIONS[case_id]
        request = str(raw["canonical_user_prompt"])

        identify_started = time.perf_counter()
        identify_response = client.invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=MODEL_ID,
            prompt_ref=identify_ref,
            prompt_input={"user_request": request},
            output_schema=IDENTIFIED_RESULTS_SCHEMA,
            timeout_seconds=180,
            instruction_text=identify_prompt,
            sampling_temperature=0.0,
            sampling_seed=arguments.sampling_seed,
        )
        identified = json.loads(cast(str, identify_response.content))
        identify_errors = [
            *validate_output_schema(identified, IDENTIFIED_RESULTS_SCHEMA.json_schema),
            *_validate_identified_results(identified),
        ]
        identified_results = (
            identified.get("identified_results", [])
            if isinstance(identified, dict)
            else []
        )
        identify_boundary_matches = (
            not identify_errors
            and len(identified_results) == len(expectation.expected_units)
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
            output_schema=DECOMPOSITION_SCHEMA,
            timeout_seconds=180,
            instruction_text=materialize_prompt,
            sampling_temperature=0.0,
            sampling_seed=arguments.sampling_seed,
        )
        candidate = json.loads(cast(str, materialize_response.content))
        materialize_errors = [
            *validate_output_schema(candidate, DECOMPOSITION_SCHEMA.json_schema),
            *_validate_decomposition(candidate),
        ]
        units = candidate.get("work_units", []) if isinstance(candidate, dict) else []
        relations = (
            candidate.get("work_relations", []) if isinstance(candidate, dict) else []
        )
        carry_matches = _has_exact_carry(identified_results, units)
        structure_matches = (
            not materialize_errors
            and len(units) == len(expectation.expected_units)
            and len(relations) == len(expectation.expected_relations)
        )
        relation_required_match = bool(expectation.expected_relations) and structure_matches
        first_divergence = _first_divergence(
            identify_errors=identify_errors,
            identify_boundary_matches=identify_boundary_matches,
            materialize_errors=materialize_errors,
            carry_matches=carry_matches,
            actual_relation_count=len(relations),
            expected_relation_count=len(expectation.expected_relations),
        )
        divergence_counts[first_divergence] += 1
        materialize_wall_ms = int((time.perf_counter() - materialize_started) * 1_000)

        records.append(
            {
                "case_id": case_id,
                "category": raw["category"],
                "user_request": request,
                "expectation": {
                    "units": list(expectation.expected_units),
                    "relations_by_unit_index": [
                        list(item) for item in expectation.expected_relations
                    ],
                },
                "identify": {
                    "candidate": identified,
                    "schema_errors": identify_errors,
                    "boundary_matches": identify_boundary_matches,
                    "input_tokens": identify_response.input_tokens,
                    "output_tokens": identify_response.output_tokens,
                    "latency_ms": identify_response.latency_ms,
                    "wall_ms": identify_wall_ms,
                },
                "materialize": {
                    "candidate": candidate,
                    "schema_errors": materialize_errors,
                    "exact_carry_matches": carry_matches,
                    "structure_matches": structure_matches,
                    "input_tokens": materialize_response.input_tokens,
                    "output_tokens": materialize_response.output_tokens,
                    "latency_ms": materialize_response.latency_ms,
                    "wall_ms": materialize_wall_ms,
                },
                "first_divergence": first_divergence,
            }
        )
        summary["identify_schema_valid"] = cast(
            int, summary["identify_schema_valid"]
        ) + int(not identify_errors)
        summary["identify_boundary_matches"] = cast(
            int, summary["identify_boundary_matches"]
        ) + int(identify_boundary_matches)
        summary["materialize_schema_valid"] = cast(
            int, summary["materialize_schema_valid"]
        ) + int(not materialize_errors)
        summary["materialize_exact_carry_matches"] = cast(
            int, summary["materialize_exact_carry_matches"]
        ) + int(carry_matches)
        summary["candidate_structure_matches"] = cast(
            int, summary["candidate_structure_matches"]
        ) + int(structure_matches)
        summary["relation_required_matches"] = cast(
            int, summary["relation_required_matches"]
        ) + int(relation_required_match)
        summary["first_divergence_counts"] = dict(sorted(divergence_counts.items()))
        _write(arguments.result_path, result)
        print(
            json.dumps(
                {
                    "case_id": case_id,
                    "expected_units": len(expectation.expected_units),
                    "identified_results": len(identified_results),
                    "actual_units": len(units),
                    "expected_relations": len(expectation.expected_relations),
                    "actual_relations": len(relations),
                    "first_divergence": first_divergence,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


def _prompt_ref(
    *,
    prompt_id: str,
    prompt_hash: str,
    input_schema_version: str,
    output_schema_version: str,
) -> PromptReference:
    return PromptReference(
        prompt_bundle_version="evaluation-only",
        prompt_id=prompt_id,
        prompt_version="requested-work-decomposition-two-stage-v1-eval",
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
    expected = [
        (item.get("result_id"), item.get("objective"))
        for item in identified_results
        if isinstance(item, dict)
    ]
    actual = [
        (item.get("unit_id"), item.get("objective"))
        for item in work_units
        if isinstance(item, dict)
    ]
    return len(expected) == len(identified_results) and expected == actual


def _first_divergence(
    *,
    identify_errors: list[str],
    identify_boundary_matches: bool,
    materialize_errors: list[str],
    carry_matches: bool,
    actual_relation_count: int,
    expected_relation_count: int,
) -> str:
    if identify_errors:
        return "STAGE1_SCHEMA"
    if not identify_boundary_matches:
        return "STAGE1_RESULT_BOUNDARY"
    if materialize_errors:
        return "STAGE2_SCHEMA"
    if not carry_matches:
        return "STAGE2_RESULT_CARRY"
    if actual_relation_count != expected_relation_count:
        return "STAGE2_RELATION"
    return "NONE"


if __name__ == "__main__":
    main()
