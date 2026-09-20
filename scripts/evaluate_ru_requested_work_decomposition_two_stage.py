"""Evaluate a bounded two-stage requested-work decomposition candidate."""

from __future__ import annotations

import hashlib
import json
import re
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
SEMANTIC_CARRY_PROMPT_ROOT = Path(
    "evaluation/prompt_candidates/"
    "ru-requested-work-decomposition-two-stage-semantic-carry-v2/sources"
)
SEMANTIC_CARRY_IDENTIFY_PROMPT = (
    SEMANTIC_CARRY_PROMPT_ROOT / "request_understanding.identify_independent_results.md"
)
SEMANTIC_CARRY_RELATION_PROMPT = (
    SEMANTIC_CARRY_PROMPT_ROOT / "request_understanding.identify_work_relations.md"
)
SPAN_BOUND_PROMPT_ROOT = Path(
    "evaluation/prompt_candidates/ru-requested-work-decomposition-two-stage-span-bound-v3/sources"
)
SPAN_BOUND_IDENTIFY_PROMPT = (
    SPAN_BOUND_PROMPT_ROOT / "request_understanding.identify_independent_results.md"
)
SPAN_BOUND_RELATION_PROMPT = (
    SPAN_BOUND_PROMPT_ROOT / "request_understanding.identify_work_relations.md"
)
REQUEST_REF_PROMPT_ROOT = Path(
    "evaluation/prompt_candidates/ru-requested-work-decomposition-two-stage-request-ref-v4/sources"
)
REQUEST_REF_IDENTIFY_PROMPT = (
    REQUEST_REF_PROMPT_ROOT / "request_understanding.identify_independent_results.md"
)
REQUEST_REF_RELATION_PROMPT = (
    REQUEST_REF_PROMPT_ROOT / "request_understanding.identify_work_relations.md"
)

REQUESTED_EFFECTS = ["ANSWER", "DRAFT", "SEND", "CREATE", "UPDATE", "DELETE"]
TYPED_RELATION_KINDS = [
    "CONSUMES_WORK_PRODUCT",
    "CONSUMES_PLANNED_SPECIFICATION",
]


def _optional_semantic_properties(*, include_requested_effects: bool = True) -> dict[str, object]:
    properties: dict[str, object] = {
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
    }
    if include_requested_effects:
        properties["requested_effects"] = {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "description": "User-requested response or external effects for this result.",
            "items": {"enum": REQUESTED_EFFECTS},
        }
    return properties


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

SEMANTIC_CARRY_IDENTIFIED_RESULTS_SCHEMA = OutputSchemaDefinition(
    schema_version="requested-independent-results-semantic-carry-v2-eval",
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
                        **_optional_semantic_properties(include_requested_effects=False),
                    },
                },
            }
        },
    },
)

SEMANTIC_CARRY_RELATIONS_SCHEMA = OutputSchemaDefinition(
    schema_version="requested-work-relations-semantic-carry-v2-eval",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["work_relations"],
        "properties": {
            "work_relations": DECOMPOSITION_SCHEMA.json_schema["properties"]["work_relations"]
        },
    },
)

SEMANTIC_CARRY_DECOMPOSITION_SCHEMA = OutputSchemaDefinition(
    schema_version="requested-work-decomposition-semantic-carry-v2-eval",
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
                        **_optional_semantic_properties(include_requested_effects=False),
                    },
                },
            },
            "work_relations": DECOMPOSITION_SCHEMA.json_schema["properties"]["work_relations"],
        },
    },
)

SPAN_BOUND_IDENTIFIED_RESULTS_SCHEMA = OutputSchemaDefinition(
    schema_version="requested-independent-results-span-bound-v3-eval",
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
                    "required": ["result_id", "request_spans"],
                    "properties": {
                        "result_id": {"type": "string", "minLength": 1},
                        "request_spans": {
                            "type": "array",
                            "minItems": 1,
                            "uniqueItems": True,
                            "description": (
                                "Exact contiguous substrings of the user request that define "
                                "this independently observable result."
                            ),
                            "items": {"type": "string", "minLength": 1},
                        },
                        **_optional_semantic_properties(include_requested_effects=False),
                    },
                },
            }
        },
    },
)

SPAN_BOUND_RELATION_SCHEMA_VERSION = "requested-work-relations-span-bound-v3-eval"
SPAN_BOUND_DECOMPOSITION_SCHEMA_VERSION = "requested-work-decomposition-span-bound-v3-eval"
REQUEST_REF_IDENTIFY_SCHEMA_VERSION = "requested-independent-results-request-ref-v4-eval"
REQUEST_REF_DECOMPOSITION_SCHEMA_VERSION = "requested-work-decomposition-request-ref-v4-eval"

SEMANTIC_REF_FIELDS = {
    "source_scope_refs": "source_scopes",
    "target_refs": "targets",
    "temporal_constraint_refs": "temporal_constraints",
    "quantity_constraint_refs": "quantity_constraints",
    "prohibition_refs": "prohibitions",
}


def _request_ref_identified_results_schema(token_ids: list[str]) -> OutputSchemaDefinition:
    span_ref = _request_span_ref_schema(token_ids)
    semantic_refs = _semantic_ref_properties(span_ref)
    return OutputSchemaDefinition(
        schema_version=REQUEST_REF_IDENTIFY_SCHEMA_VERSION,
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["shared_semantics", "identified_results"],
            "properties": {
                "shared_semantics": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": semantic_refs,
                },
                "identified_results": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["result_id", "request_span_refs"],
                        "properties": {
                            "result_id": {"type": "string", "minLength": 1},
                            "request_span_refs": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": span_ref,
                            },
                            **semantic_refs,
                        },
                    },
                },
            },
        },
    )


def _request_ref_decomposition_schema(result_ids: list[str]) -> OutputSchemaDefinition:
    semantic_values = _resolved_semantic_properties()
    return OutputSchemaDefinition(
        schema_version=REQUEST_REF_DECOMPOSITION_SCHEMA_VERSION,
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["shared_semantics", "work_units", "work_relations"],
            "properties": {
                "shared_semantics": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": semantic_values,
                },
                "work_units": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["unit_id", "objective", "request_spans"],
                        "properties": {
                            "unit_id": {"type": "string", "minLength": 1},
                            "objective": {"type": "string", "minLength": 1},
                            "request_spans": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"type": "string", "minLength": 1},
                            },
                            **semantic_values,
                        },
                    },
                },
                "work_relations": _closed_typed_relation_array_schema(result_ids),
            },
        },
    )


def _request_span_ref_schema(token_ids: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["start_token_id", "end_token_id"],
        "properties": {
            "start_token_id": {"enum": token_ids},
            "end_token_id": {"enum": token_ids},
        },
    }


def _semantic_ref_properties(span_ref: dict[str, object]) -> dict[str, object]:
    return {
        field: {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": span_ref,
        }
        for field in SEMANTIC_REF_FIELDS
    }


def _resolved_semantic_properties() -> dict[str, object]:
    return {
        field: {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        }
        for field in SEMANTIC_REF_FIELDS.values()
    }


def _closed_typed_relations_schema(result_ids: list[str]) -> OutputSchemaDefinition:
    relation_array = _closed_typed_relation_array_schema(result_ids)
    return OutputSchemaDefinition(
        schema_version=SPAN_BOUND_RELATION_SCHEMA_VERSION,
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["work_relations"],
            "properties": {"work_relations": relation_array},
        },
    )


def _span_bound_decomposition_schema(result_ids: list[str]) -> OutputSchemaDefinition:
    return OutputSchemaDefinition(
        schema_version=SPAN_BOUND_DECOMPOSITION_SCHEMA_VERSION,
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
                        "required": ["unit_id", "objective", "request_spans"],
                        "properties": {
                            "unit_id": {"type": "string", "minLength": 1},
                            "objective": {"type": "string", "minLength": 1},
                            "request_spans": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"type": "string", "minLength": 1},
                            },
                            **_optional_semantic_properties(include_requested_effects=False),
                        },
                    },
                },
                "work_relations": _closed_typed_relation_array_schema(result_ids),
            },
        },
    )


def _closed_typed_relation_array_schema(result_ids: list[str]) -> dict[str, object]:
    unique_ids = list(dict.fromkeys(result_ids))
    allowed_pairs = [
        (source_id, target_id)
        for source_id in unique_ids
        for target_id in unique_ids
        if source_id != target_id
    ]
    relation_array: dict[str, object] = {
        "type": "array",
        "maxItems": min(12, len(allowed_pairs)),
        "uniqueItems": True,
    }
    if not allowed_pairs:
        relation_array["items"] = {
            "type": "object",
            "additionalProperties": False,
        }
        return relation_array
    relation_array["items"] = {
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_unit_id", "target_unit_id", "kind"],
                "properties": {
                    "source_unit_id": {"const": source_id},
                    "target_unit_id": {"const": target_id},
                    "kind": {"enum": TYPED_RELATION_KINDS},
                },
            }
            for source_id, target_id in allowed_pairs
        ]
    }
    return relation_array


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--sampling-seed", type=int, default=20260920)
    parser.add_argument("--semantic-state", action="store_true")
    parser.add_argument("--deterministic-semantic-carry", action="store_true")
    parser.add_argument("--span-bound-typed-relations", action="store_true")
    parser.add_argument("--request-ref-shared-state", action="store_true")
    arguments = parser.parse_args()
    if arguments.result_path.exists():
        raise ValueError("result path already exists; preserve every prior trial")

    case_ids = arguments.case or list(CORE24_CASE_IDS)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate Case ID")
    if any(case_id not in CORE24_CASE_IDS for case_id in case_ids):
        raise ValueError("requested Case is not in the fixed Core comparison set")
    selected_candidates = sum(
        (
            arguments.semantic_state,
            arguments.deterministic_semantic_carry,
            arguments.span_bound_typed_relations,
            arguments.request_ref_shared_state,
        )
    )
    if selected_candidates > 1:
        raise ValueError("select only one two-stage candidate")

    cases = load_cases()
    if arguments.request_ref_shared_state:
        identify_prompt_path = REQUEST_REF_IDENTIFY_PROMPT
        materialize_prompt_path = REQUEST_REF_RELATION_PROMPT
        identify_schema = None
        materialize_schema = None
        decomposition_schema = None
        identify_input_schema_version = "user-request-plus-token-catalog-v1"
        identify_output_schema_version = REQUEST_REF_IDENTIFY_SCHEMA_VERSION
        materialize_output_schema_version = SPAN_BOUND_RELATION_SCHEMA_VERSION
        materialize_input_schema_version = "user-request-plus-shared-state-and-results-v1"
        candidate_id = "ru-requested-work-decomposition-two-stage-request-ref-v4"
        prompt_version = "requested-work-decomposition-two-stage-request-ref-v4-eval"
        materialize_prompt_id = "request_understanding.identify_work_relations"
    elif arguments.span_bound_typed_relations:
        identify_prompt_path = SPAN_BOUND_IDENTIFY_PROMPT
        materialize_prompt_path = SPAN_BOUND_RELATION_PROMPT
        identify_schema = SPAN_BOUND_IDENTIFIED_RESULTS_SCHEMA
        materialize_schema = None
        decomposition_schema = None
        identify_input_schema_version = "user-request-only-v1"
        identify_output_schema_version = identify_schema.schema_version
        materialize_output_schema_version = SPAN_BOUND_RELATION_SCHEMA_VERSION
        materialize_input_schema_version = "user-request-plus-identified-results-v1"
        candidate_id = "ru-requested-work-decomposition-two-stage-span-bound-v3"
        prompt_version = "requested-work-decomposition-two-stage-span-bound-v3-eval"
        materialize_prompt_id = "request_understanding.identify_work_relations"
    elif arguments.deterministic_semantic_carry:
        identify_prompt_path = SEMANTIC_CARRY_IDENTIFY_PROMPT
        materialize_prompt_path = SEMANTIC_CARRY_RELATION_PROMPT
        identify_schema = SEMANTIC_CARRY_IDENTIFIED_RESULTS_SCHEMA
        materialize_schema = SEMANTIC_CARRY_RELATIONS_SCHEMA
        decomposition_schema = SEMANTIC_CARRY_DECOMPOSITION_SCHEMA
        identify_input_schema_version = "user-request-only-v1"
        materialize_output_schema_version = materialize_schema.schema_version
        materialize_input_schema_version = "user-request-plus-identified-results-v1"
        identify_output_schema_version = identify_schema.schema_version
        candidate_id = "ru-requested-work-decomposition-two-stage-semantic-carry-v2"
        prompt_version = "requested-work-decomposition-two-stage-semantic-carry-v2-eval"
        materialize_prompt_id = "request_understanding.identify_work_relations"
    elif arguments.semantic_state:
        identify_prompt_path = SEMANTIC_STATE_IDENTIFY_PROMPT
        materialize_prompt_path = SEMANTIC_STATE_MATERIALIZE_PROMPT
        identify_schema = SEMANTIC_STATE_IDENTIFIED_RESULTS_SCHEMA
        materialize_schema = SEMANTIC_STATE_DECOMPOSITION_SCHEMA
        decomposition_schema = SEMANTIC_STATE_DECOMPOSITION_SCHEMA
        identify_input_schema_version = "user-request-only-v1"
        materialize_output_schema_version = materialize_schema.schema_version
        materialize_input_schema_version = "user-request-plus-identified-results-v1"
        identify_output_schema_version = identify_schema.schema_version
        candidate_id = "ru-requested-work-decomposition-two-stage-semantic-state-v1"
        prompt_version = "requested-work-decomposition-two-stage-semantic-state-v1-eval"
        materialize_prompt_id = "request_understanding.materialize_work_units"
    else:
        identify_prompt_path = IDENTIFY_PROMPT
        materialize_prompt_path = MATERIALIZE_PROMPT
        identify_schema = IDENTIFIED_RESULTS_SCHEMA
        materialize_schema = DECOMPOSITION_SCHEMA
        decomposition_schema = DECOMPOSITION_SCHEMA
        identify_input_schema_version = "user-request-only-v1"
        materialize_output_schema_version = materialize_schema.schema_version
        materialize_input_schema_version = "user-request-plus-identified-results-v1"
        identify_output_schema_version = identify_schema.schema_version
        candidate_id = "ru-requested-work-decomposition-two-stage-v1"
        prompt_version = "requested-work-decomposition-two-stage-v1-eval"
        materialize_prompt_id = "request_understanding.materialize_work_units"
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
        input_schema_version=identify_input_schema_version,
        output_schema_version=identify_output_schema_version,
    )
    materialize_ref = _prompt_ref(
        prompt_id=materialize_prompt_id,
        prompt_hash=materialize_hash,
        prompt_version=prompt_version,
        input_schema_version=materialize_input_schema_version,
        output_schema_version=materialize_output_schema_version,
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
        request_tokens = _request_token_catalog(request)
        if arguments.request_ref_shared_state:
            case_identify_schema = _request_ref_identified_results_schema(
                [str(token["token_id"]) for token in request_tokens]
            )
            identify_input = {
                "user_request": request,
                "request_tokens": [
                    {"token_id": token["token_id"], "text": token["text"]}
                    for token in request_tokens
                ],
            }
        else:
            if identify_schema is None:
                raise AssertionError("static two-stage identify schema is missing")
            case_identify_schema = identify_schema
            identify_input = {"user_request": request}

        identify_started = time.perf_counter()
        identify_response = client.invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=MODEL_ID,
            prompt_ref=identify_ref,
            prompt_input=identify_input,
            output_schema=case_identify_schema,
            timeout_seconds=180,
            instruction_text=identify_prompt,
            sampling_temperature=0.0,
            sampling_seed=arguments.sampling_seed,
        )
        identified = json.loads(cast(str, identify_response.content))
        identify_errors = [
            *validate_output_schema(identified, case_identify_schema.json_schema),
            *_validate_identified_results(identified),
        ]
        if arguments.request_ref_shared_state:
            identify_errors.extend(_validate_request_refs(identified, request_tokens))
        elif arguments.span_bound_typed_relations:
            identify_errors.extend(_validate_request_span_bindings(identified, request))
        identified_results = (
            identified.get("identified_results", []) if isinstance(identified, dict) else []
        )
        identify_wall_ms = int((time.perf_counter() - identify_started) * 1_000)

        shared_semantics = (
            identified.get("shared_semantics", {}) if isinstance(identified, dict) else {}
        )
        if arguments.request_ref_shared_state:
            result_ids = _identified_result_ids(identified_results)
            case_materialize_schema = _closed_typed_relations_schema(result_ids)
            case_decomposition_schema = _request_ref_decomposition_schema(result_ids)
        elif arguments.span_bound_typed_relations:
            result_ids = _identified_result_ids(identified_results)
            case_materialize_schema = _closed_typed_relations_schema(result_ids)
            case_decomposition_schema = _span_bound_decomposition_schema(result_ids)
        else:
            if materialize_schema is None or decomposition_schema is None:
                raise AssertionError("static two-stage candidate schema is missing")
            case_materialize_schema = materialize_schema
            case_decomposition_schema = decomposition_schema
        materialize_input = {
            "user_request": request,
            "identified_results": identified_results,
        }
        if arguments.request_ref_shared_state:
            materialize_input["shared_semantics"] = shared_semantics

        materialize_started = time.perf_counter()
        materialize_response = client.invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=MODEL_ID,
            prompt_ref=materialize_ref,
            prompt_input=materialize_input,
            output_schema=case_materialize_schema,
            timeout_seconds=180,
            instruction_text=materialize_prompt,
            sampling_temperature=0.0,
            sampling_seed=arguments.sampling_seed,
        )
        llm_candidate = json.loads(cast(str, materialize_response.content))
        if arguments.request_ref_shared_state:
            candidate = _project_request_ref_candidate(
                shared_semantics=shared_semantics,
                identified_results=identified_results,
                request=request,
                request_tokens=request_tokens,
                work_relations=(
                    llm_candidate.get("work_relations", [])
                    if isinstance(llm_candidate, dict)
                    else []
                ),
            )
        elif arguments.span_bound_typed_relations:
            candidate = {
                "work_units": _project_span_bound_results(identified_results),
                "work_relations": (
                    llm_candidate.get("work_relations", [])
                    if isinstance(llm_candidate, dict)
                    else []
                ),
            }
        elif arguments.deterministic_semantic_carry:
            candidate = {
                "work_units": _project_identified_results(identified_results),
                "work_relations": (
                    llm_candidate.get("work_relations", [])
                    if isinstance(llm_candidate, dict)
                    else []
                ),
            }
        else:
            candidate = llm_candidate
        materialize_errors = validate_output_schema(
            llm_candidate, case_materialize_schema.json_schema
        )
        if (
            arguments.deterministic_semantic_carry
            or arguments.span_bound_typed_relations
            or arguments.request_ref_shared_state
        ):
            materialize_errors.extend(
                validate_output_schema(candidate, case_decomposition_schema.json_schema)
            )
        materialize_errors.extend(_validate_decomposition(candidate))
        units = candidate.get("work_units", []) if isinstance(candidate, dict) else []
        relations = candidate.get("work_relations", []) if isinstance(candidate, dict) else []
        if arguments.request_ref_shared_state:
            carry_matches = candidate == _project_request_ref_candidate(
                shared_semantics=shared_semantics,
                identified_results=identified_results,
                request=request,
                request_tokens=request_tokens,
                work_relations=relations,
            )
        elif arguments.span_bound_typed_relations:
            carry_matches = _project_span_bound_results(identified_results) == units
        else:
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
                    "request_tokens": request_tokens if arguments.request_ref_shared_state else [],
                    "schema_errors": identify_errors,
                    "input_tokens": identify_response.input_tokens,
                    "output_tokens": identify_response.output_tokens,
                    "latency_ms": identify_response.latency_ms,
                    "wall_ms": identify_wall_ms,
                },
                "materialize": {
                    "llm_candidate": llm_candidate,
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


def _request_token_catalog(user_request: str) -> list[dict[str, object]]:
    return [
        {
            "token_id": f"T{index:03d}",
            "text": match.group(0),
            "start": match.start(),
            "end": match.end(),
        }
        for index, match in enumerate(re.finditer(r"\S+", user_request), start=1)
    ]


def _validate_request_refs(value: object, request_tokens: list[dict[str, object]]) -> list[str]:
    if not isinstance(value, dict):
        return []
    token_order = {str(token["token_id"]): index for index, token in enumerate(request_tokens)}
    errors: list[str] = []
    shared = value.get("shared_semantics")
    if isinstance(shared, dict):
        errors.extend(_validate_semantic_ref_fields(shared, token_order, "$.shared_semantics"))
    results = value.get("identified_results")
    if not isinstance(results, list):
        return errors
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            continue
        path = f"$.identified_results[{index}]"
        refs = item.get("request_span_refs")
        if isinstance(refs, list):
            errors.extend(
                _validate_ordered_span_refs(refs, token_order, f"{path}.request_span_refs")
            )
        errors.extend(_validate_semantic_ref_fields(item, token_order, path))
    return errors


def _validate_semantic_ref_fields(
    value: dict[object, object], token_order: dict[str, int], path: str
) -> list[str]:
    errors: list[str] = []
    for field in SEMANTIC_REF_FIELDS:
        refs = value.get(field)
        if isinstance(refs, list):
            errors.extend(_validate_ordered_span_refs(refs, token_order, f"{path}.{field}"))
    return errors


def _validate_ordered_span_refs(
    refs: list[object], token_order: dict[str, int], path: str
) -> list[str]:
    errors: list[str] = []
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict):
            continue
        start_id = ref.get("start_token_id")
        end_id = ref.get("end_token_id")
        if not isinstance(start_id, str) or not isinstance(end_id, str):
            continue
        if (
            start_id in token_order
            and end_id in token_order
            and token_order[start_id] > token_order[end_id]
        ):
            errors.append(f"{path}[{index}] start token must not follow end token")
    return errors


def _validate_request_span_bindings(value: object, user_request: str) -> list[str]:
    if not isinstance(value, dict):
        return []
    identified_results = value.get("identified_results")
    if not isinstance(identified_results, list):
        return []
    errors: list[str] = []
    for result_index, item in enumerate(identified_results):
        if not isinstance(item, dict):
            continue
        spans = item.get("request_spans")
        if not isinstance(spans, list):
            continue
        for span_index, span in enumerate(spans):
            if isinstance(span, str) and span not in user_request:
                errors.append(
                    f"$.identified_results[{result_index}].request_spans[{span_index}] "
                    "must be an exact user-request substring"
                )
    return errors


def _identified_result_ids(identified_results: object) -> list[str]:
    if not isinstance(identified_results, list):
        return []
    return [
        str(item["result_id"])
        for item in identified_results
        if isinstance(item, dict) and isinstance(item.get("result_id"), str)
    ]


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


def _project_identified_results(identified_results: object) -> list[dict[str, object]]:
    if not isinstance(identified_results, list):
        return []
    work_units: list[dict[str, object]] = []
    for item in identified_results:
        if not isinstance(item, dict):
            continue
        work_unit = dict(item)
        work_unit["unit_id"] = work_unit.pop("result_id", None)
        work_units.append(work_unit)
    return work_units


def _project_span_bound_results(identified_results: object) -> list[dict[str, object]]:
    if not isinstance(identified_results, list):
        return []
    work_units: list[dict[str, object]] = []
    for item in identified_results:
        if not isinstance(item, dict):
            continue
        work_unit = dict(item)
        work_unit["unit_id"] = work_unit.pop("result_id", None)
        spans = work_unit.get("request_spans")
        exact_spans = (
            [span for span in spans if isinstance(span, str)] if isinstance(spans, list) else []
        )
        work_unit["objective"] = " ".join(exact_spans)
        work_units.append(work_unit)
    return work_units


def _project_request_ref_candidate(
    *,
    shared_semantics: object,
    identified_results: object,
    request: str,
    request_tokens: list[dict[str, object]],
    work_relations: object,
) -> dict[str, object]:
    token_positions = {
        str(token["token_id"]): (int(token["start"]), int(token["end"])) for token in request_tokens
    }
    projected_shared = _resolve_semantic_refs(
        shared_semantics, request=request, token_positions=token_positions
    )
    work_units: list[dict[str, object]] = []
    if isinstance(identified_results, list):
        for item in identified_results:
            if not isinstance(item, dict):
                continue
            request_spans = _resolve_ref_list(
                item.get("request_span_refs"),
                request=request,
                token_positions=token_positions,
            )
            work_unit: dict[str, object] = {
                "unit_id": item.get("result_id"),
                "objective": " ".join(request_spans),
                "request_spans": request_spans,
                **_resolve_semantic_refs(item, request=request, token_positions=token_positions),
            }
            work_units.append(work_unit)
    return {
        "shared_semantics": projected_shared,
        "work_units": work_units,
        "work_relations": work_relations if isinstance(work_relations, list) else [],
    }


def _resolve_semantic_refs(
    value: object,
    *,
    request: str,
    token_positions: dict[str, tuple[int, int]],
) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    resolved: dict[str, object] = {}
    for ref_field, value_field in SEMANTIC_REF_FIELDS.items():
        spans = _resolve_ref_list(
            value.get(ref_field), request=request, token_positions=token_positions
        )
        if spans:
            resolved[value_field] = spans
    return resolved


def _resolve_ref_list(
    refs: object,
    *,
    request: str,
    token_positions: dict[str, tuple[int, int]],
) -> list[str]:
    if not isinstance(refs, list):
        return []
    resolved: list[str] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        start = token_positions.get(str(ref.get("start_token_id")))
        end = token_positions.get(str(ref.get("end_token_id")))
        if start is None or end is None or start[0] > end[0]:
            continue
        span = request[start[0] : end[1]]
        if span and span not in resolved:
            resolved.append(span)
    return resolved


if __name__ == "__main__":
    main()
