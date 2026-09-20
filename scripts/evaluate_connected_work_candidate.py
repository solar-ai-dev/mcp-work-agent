"""Run the connected-work structure candidate on Canonical Core fixtures.

This is a bounded development diagnostic.  It compiles an evaluation-only
LangGraph and never constructs a Product connector-write capability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from evaluation.dataset_v8 import DEFAULT_DATASET_PATH, load_cases, normalized_sha256
from evaluation.harness.connected_work_candidate import (
    ConstraintProjectionV1,
    EvidenceProjectionV1,
    IntermediateWorkProductV1,
    PlannedActionSpecificationV1,
    RequestedWorkDefinitionV1,
    RequestedWorkUnitV1,
    compile_connected_work_candidate,
)
from scripts.evaluate_retrieval_plan_query_node import _load_latest_state

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    REQUEST_RESOURCE_TYPES,
    WRITE_EFFECT_RESOURCE_TYPES,
)
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)

ROOT = Path(__file__).resolve().parents[1]
PROMPT_ROOT = ROOT / "evaluation/prompt_candidates/ru-connected-work-v4/sources"
PROVIDER_FIXTURE = (
    ROOT / "evaluation/datasets/e2e/fixtures/google_workspace/provider-snapshot-v8.json"
)
MODEL_ID = "qwen3.5:9b"
MODEL_DIGEST = "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7"


class _CandidateRuntime:
    def __init__(self, *, temperature: float, seed: int) -> None:
        self._client = OllamaHTTPClient()
        self._temperature = temperature
        self._seed = seed
        self.calls: list[dict[str, object]] = []

    def invoke(
        self,
        *,
        prompt_id: str,
        source_name: str,
        prompt_input: Mapping[str, object],
        schema: OutputSchemaDefinition,
    ) -> dict[str, object]:
        source_path = PROMPT_ROOT / source_name
        source = source_path.read_text(encoding="utf-8").rstrip()
        source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        prompt_ref = PromptReference(
            prompt_bundle_version="ru-connected-work-v4-eval",
            prompt_id=prompt_id,
            prompt_version="1.0.0-candidate",
            content_hash=source_hash,
            agent_role=(
                "request_understanding"
                if prompt_id.startswith("request_understanding.")
                else "intermediate_work_product"
            ),
            subgraph_name="connected_work_candidate",
            node_name=prompt_id.rsplit(".", 1)[-1],
            node_state="BASE",
            purpose="EVALUATION_ONLY_CONNECTED_WORK",
            input_schema_version="connected-work-v3-eval",
            output_schema_version=schema.schema_version,
        )
        response = self._client.invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=MODEL_ID,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            output_schema=schema,
            timeout_seconds=180,
            instruction_text=source,
            sampling_temperature=self._temperature,
            sampling_seed=self._seed,
        )
        content = response.content
        candidate = json.loads(content) if isinstance(content, str) else content
        if not isinstance(candidate, Mapping):
            raise ValueError(f"{prompt_id}: structured output is not an object")
        self.calls.append(
            {
                "prompt_id": prompt_id,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "latency_ms": response.latency_ms,
                "structured_output": dict(candidate),
            }
        )
        return dict(candidate)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--sampling-temperature", type=float, default=0.0)
    parser.add_argument("--sampling-seed", type=int, default=20260920)
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        default=ROOT / "runtime/evaluation-v8/canonical92-v8-652b07a6-b926950fa1",
    )
    arguments = parser.parse_args()
    if arguments.result_path.exists():
        raise ValueError("result path already exists; prior trials must be preserved")
    cases = load_cases()
    unknown = sorted(set(arguments.case) - set(cases))
    if unknown:
        raise ValueError(f"unknown Canonical Case: {unknown[0]}")
    if any(cases[case_id].raw.get("split") != "CORE" for case_id in arguments.case):
        raise ValueError("connected-work tuning accepts Canonical Core only")
    if len(arguments.case) != len(set(arguments.case)):
        raise ValueError("each Case is executed exactly once")
    client = OllamaHTTPClient()
    digest = next(
        (item.digest for item in client.list_installed_models() if item.model_id == MODEL_ID),
        None,
    )
    if digest != MODEL_DIGEST:
        raise ValueError("installed local model digest differs from the fixed candidate binding")

    fixtures = json.loads(PROVIDER_FIXTURE.read_text(encoding="utf-8"))["resource_packs"]
    runtime = _CandidateRuntime(
        temperature=arguments.sampling_temperature,
        seed=arguments.sampling_seed,
    )
    records: list[dict[str, object]] = []
    for case_id in arguments.case:
        case = cases[case_id]
        request = str(case.raw["canonical_user_prompt"])
        evidence = _fixture_evidence(
            fixtures,
            cast(list[str], case.raw.get("resource_packs", [])),
        )
        intent_projection = _intent_projection(
            arguments.checkpoint_root / case_id / "state/data/google_work_agent.db"
        )
        constraint_catalog = cast(
            list[ConstraintProjectionV1], intent_projection["constraint_catalog"]
        )
        call_start = len(runtime.calls)
        started = time.perf_counter()
        error: Exception | None = None
        result: Mapping[str, object] = {}
        try:
            graph = compile_connected_work_candidate(
                define_work=lambda user_request, projection=intent_projection: _define_work_v4(
                    runtime,
                    user_request=user_request,
                    intent_projection=projection,
                ),
                materialize_product=lambda unit, projected, upstream, conditions: _materialize(
                    runtime,
                    unit=unit,
                    evidence=projected,
                    upstream_products=upstream,
                    conditions=conditions,
                ),
                consume_work=lambda unit, projected, products, specifications, conditions: _consume(
                    runtime,
                    unit=unit,
                    evidence=projected,
                    products=products,
                    specifications=specifications,
                    conditions=conditions,
                ),
            )
            result = cast(
                Mapping[str, object],
                graph.invoke(
                    {
                        "user_request": request,
                        "evidence": evidence,
                        "constraint_catalog": constraint_catalog,
                    }
                ),
            )
        except Exception as caught:
            error = caught
        calls = runtime.calls[call_start:]
        record = _record(
            case_id=case_id,
            result=result,
            calls=calls,
            duration_ms=int((time.perf_counter() - started) * 1_000),
            error=error,
        )
        records.append(record)
        _write_result(
            arguments.result_path,
            records=records,
            case_ids=arguments.case,
            digest=digest,
            temperature=arguments.sampling_temperature,
            seed=arguments.sampling_seed,
        )
        print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)


def _definition_schema() -> OutputSchemaDefinition:
    condition = {
        "type": "object",
        "additionalProperties": False,
        "required": ["condition_id", "kind", "source_text"],
        "properties": {
            "condition_id": {"type": "string", "minLength": 1},
            "kind": {"enum": ["TARGET", "QUANTITY", "TEMPORAL", "PROHIBITION", "REQUIREMENT"]},
            "source_text": {"type": "string", "minLength": 1},
        },
    }
    resource_input = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "resource_type", "required_information"],
        "properties": {
            "kind": {"const": "RESOURCE"},
            "resource_type": {"enum": list(REQUEST_RESOURCE_TYPES)},
            "required_information": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    }
    product_input = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "product_ref"],
        "properties": {
            "kind": {"const": "WORK_PRODUCT"},
            "product_ref": {"type": "string", "minLength": 1},
        },
    }
    spec_input = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "specification_ref"],
        "properties": {
            "kind": {"const": "PLANNED_SPECIFICATION"},
            "specification_ref": {"type": "string", "minLength": 1},
        },
    }
    external_outputs = [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "specification_ref", "resource_type", "effect"],
            "properties": {
                "kind": {"const": "EXTERNAL_ACTION_SPECIFICATION"},
                "specification_ref": {"type": "string", "minLength": 1},
                "resource_type": {"const": resource_type},
                "effect": {"const": effect},
            },
        }
        for effect, resource_types in WRITE_EFFECT_RESOURCE_TYPES.items()
        for resource_type in sorted(resource_types)
    ]
    return OutputSchemaDefinition(
        schema_version="connected-work-definition-v1-eval",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "common_conditions", "work_units", "relations"],
            "properties": {
                "schema_version": {"const": 1},
                "common_conditions": {"type": "array", "maxItems": 12, "items": condition},
                "work_units": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "unit_id",
                            "objective",
                            "operation",
                            "input_bindings",
                            "conditions",
                            "output",
                        ],
                        "properties": {
                            "unit_id": {"type": "string", "minLength": 1},
                            "objective": {"type": "string", "minLength": 1},
                            "operation": {
                                "enum": [
                                    "ANSWER",
                                    "SUMMARIZE",
                                    "ANALYZE",
                                    "COMPOSE",
                                    "PREPARE_ACTION",
                                ]
                            },
                            "input_bindings": {
                                "type": "array",
                                "maxItems": 12,
                                "items": {"oneOf": [resource_input, product_input, spec_input]},
                            },
                            "conditions": {"type": "array", "maxItems": 12, "items": condition},
                            "output": {
                                "oneOf": [
                                    {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["kind"],
                                        "properties": {"kind": {"const": "USER_RESPONSE"}},
                                    },
                                    {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["kind", "product_ref", "product_kind"],
                                        "properties": {
                                            "kind": {"const": "INTERMEDIATE_WORK_PRODUCT"},
                                            "product_ref": {"type": "string", "minLength": 1},
                                            "product_kind": {
                                                "enum": ["SUMMARY", "ANALYSIS", "CONTENT"]
                                            },
                                        },
                                    },
                                    *external_outputs,
                                ]
                            },
                        },
                    },
                },
                "relations": {
                    "type": "array",
                    "maxItems": 16,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "relation_id",
                            "kind",
                            "source_unit_id",
                            "target_unit_id",
                            "artifact_ref",
                        ],
                        "properties": {
                            "relation_id": {"type": "string", "minLength": 1},
                            "kind": {
                                "enum": [
                                    "CONSUMES_WORK_PRODUCT",
                                    "CONSUMES_PLANNED_SPECIFICATION",
                                ]
                            },
                            "source_unit_id": {"type": "string", "minLength": 1},
                            "target_unit_id": {"type": "string", "minLength": 1},
                            "artifact_ref": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
        },
    )


def _decomposition_schema(
    *, source_refs: Sequence[str], output_refs: Sequence[str]
) -> OutputSchemaDefinition:
    common_properties = {
        "unit_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]+$"},
        "objective": {"type": "string", "minLength": 1},
        "source_responsibility_refs": {
            "type": "array",
            "maxItems": 8,
            "uniqueItems": True,
            "items": {"enum": list(source_refs)},
        },
    }
    unit_variants: list[dict[str, object]] = [
        {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "unit_id",
                "objective",
                "operation",
                "source_responsibility_refs",
                "output_kind",
            ],
            "properties": {
                **common_properties,
                "operation": {"const": "ANSWER"},
                "output_kind": {"const": "USER_RESPONSE"},
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "unit_id",
                "objective",
                "operation",
                "source_responsibility_refs",
                "output_kind",
                "product_kind",
            ],
            "properties": {
                **common_properties,
                "operation": {"enum": ["SUMMARIZE", "ANALYZE", "COMPOSE"]},
                "output_kind": {"const": "INTERMEDIATE_WORK_PRODUCT"},
                "product_kind": {"enum": ["SUMMARY", "ANALYSIS", "CONTENT"]},
            },
        },
    ]
    if output_refs:
        unit_variants.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "unit_id",
                    "objective",
                    "operation",
                    "source_responsibility_refs",
                    "output_kind",
                    "output_responsibility_ref",
                ],
                "properties": {
                    **common_properties,
                    "operation": {"const": "PREPARE_ACTION"},
                    "output_kind": {"const": "EXTERNAL_ACTION_SPECIFICATION"},
                    "output_responsibility_ref": {"enum": list(output_refs)},
                },
            }
        )
    return OutputSchemaDefinition(
        schema_version="requested-work-decomposition-v4-eval",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "work_units"],
            "properties": {
                "schema_version": {"const": 1},
                "work_units": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10,
                    "items": {"oneOf": unit_variants},
                },
            },
        },
    )


def _condition_schema(
    unit_ids: Sequence[str], constraint_refs: Sequence[str]
) -> OutputSchemaDefinition:
    return OutputSchemaDefinition(
        schema_version="requested-work-conditions-v1-eval",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "conditions"],
            "properties": {
                "schema_version": {"const": 1},
                "conditions": {
                    "type": "array",
                    "maxItems": 16,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "constraint_ref",
                            "applies_to_unit_ids",
                        ],
                        "properties": {
                            "constraint_ref": {"enum": list(constraint_refs)},
                            "applies_to_unit_ids": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"enum": list(unit_ids)},
                            },
                        },
                    },
                },
            },
        },
    )


def _relation_schema(
    *, unit_ids: Sequence[str], artifact_refs: Sequence[str]
) -> OutputSchemaDefinition:
    return OutputSchemaDefinition(
        schema_version="requested-work-relations-v1-eval",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "relations"],
            "properties": {
                "schema_version": {"const": 1},
                "relations": {
                    "type": "array",
                    "maxItems": 16,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["artifact_ref", "target_unit_id"],
                        "properties": {
                            "artifact_ref": {"enum": list(artifact_refs)},
                            "target_unit_id": {"enum": list(unit_ids)},
                        },
                    },
                },
            },
        },
    )


def _define_work_v4(
    runtime: _CandidateRuntime,
    *,
    user_request: str,
    intent_projection: Mapping[str, object],
) -> RequestedWorkDefinitionV1:
    source_catalog = cast(
        list[Mapping[str, object]], intent_projection.get("source_responsibilities", [])
    )
    output_catalog = cast(
        list[Mapping[str, object]], intent_projection.get("output_responsibilities", [])
    )
    decomposition = runtime.invoke(
        prompt_id="request_understanding.decompose_requested_work",
        source_name="request_understanding.decompose_requested_work.md",
        prompt_input={
            "user_request": user_request,
            "validated_goal": intent_projection.get("goal"),
            "validated_completion_conditions": intent_projection.get("completion_conditions", []),
            "source_responsibility_catalog": source_catalog,
            "output_responsibility_catalog": output_catalog,
        },
        schema=_decomposition_schema(
            source_refs=[cast(str, item["responsibility_ref"]) for item in source_catalog],
            output_refs=[cast(str, item["responsibility_ref"]) for item in output_catalog],
        ),
    )
    raw_units = decomposition.get("work_units")
    if not isinstance(raw_units, list) or not raw_units:
        raise ValueError("decomposition returned no work units")
    unit_ids = [
        str(unit["unit_id"])
        for unit in raw_units
        if isinstance(unit, Mapping) and isinstance(unit.get("unit_id"), str)
    ]
    if len(unit_ids) != len(raw_units) or len(unit_ids) != len(set(unit_ids)):
        raise ValueError("decomposition work unit ids must be complete and unique")
    artifact_catalog = _artifact_catalog(cast(list[Mapping[str, object]], raw_units))
    raw_relations: list[Mapping[str, object]] = []
    if artifact_catalog and len(raw_units) > 1:
        relation_result = runtime.invoke(
            prompt_id="request_understanding.attribute_work_relations",
            source_name="request_understanding.attribute_work_relations.md",
            prompt_input={
                "work_units": raw_units,
                "artifact_catalog": artifact_catalog,
            },
            schema=_relation_schema(
                unit_ids=unit_ids,
                artifact_refs=[cast(str, item["artifact_ref"]) for item in artifact_catalog],
            ),
        )
        raw_relations = cast(list[Mapping[str, object]], relation_result.get("relations", []))
    constraint_catalog = cast(
        list[ConstraintProjectionV1], intent_projection.get("constraint_catalog", [])
    )
    raw_conditions: list[Mapping[str, object]] = []
    if constraint_catalog:
        conditions = runtime.invoke(
            prompt_id="request_understanding.attribute_work_conditions",
            source_name="request_understanding.attribute_work_conditions.md",
            prompt_input={
                "work_units": raw_units,
                "constraint_catalog": constraint_catalog,
            },
            schema=_condition_schema(
                unit_ids, [item["constraint_ref"] for item in constraint_catalog]
            ),
        )
        raw_conditions = cast(list[Mapping[str, object]], conditions.get("conditions", []))
    return _assemble_work_definition_v4(
        raw_units=cast(list[Mapping[str, object]], raw_units),
        raw_relations=raw_relations,
        raw_condition_assignments=raw_conditions,
        constraint_catalog=constraint_catalog,
        source_catalog=source_catalog,
        output_catalog=output_catalog,
    )


def _artifact_catalog(
    raw_units: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for raw in raw_units:
        unit_id = raw.get("unit_id")
        output_kind = raw.get("output_kind")
        if not isinstance(unit_id, str):
            raise ValueError("decomposed work unit requires a stable id")
        if output_kind == "INTERMEDIATE_WORK_PRODUCT":
            result.append(
                {
                    "artifact_ref": f"work-product:{unit_id}",
                    "artifact_kind": "WORK_PRODUCT",
                    "source_unit_id": unit_id,
                }
            )
        elif output_kind == "EXTERNAL_ACTION_SPECIFICATION":
            result.append(
                {
                    "artifact_ref": f"planned-specification:{unit_id}",
                    "artifact_kind": "PLANNED_SPECIFICATION",
                    "source_unit_id": unit_id,
                }
            )
        elif output_kind != "USER_RESPONSE":
            raise ValueError(f"{unit_id}: unsupported decomposed output")
    return result


def _assemble_work_definition_v4(
    *,
    raw_units: list[Mapping[str, object]],
    raw_relations: list[Mapping[str, object]],
    raw_condition_assignments: list[Mapping[str, object]],
    constraint_catalog: Sequence[ConstraintProjectionV1],
    source_catalog: Sequence[Mapping[str, object]],
    output_catalog: Sequence[Mapping[str, object]],
) -> RequestedWorkDefinitionV1:
    unit_ids = [cast(str, unit["unit_id"]) for unit in raw_units]
    unit_id_set = set(unit_ids)
    raw_by_id = {cast(str, unit["unit_id"]): unit for unit in raw_units}
    artifacts_by_ref = {item["artifact_ref"]: item for item in _artifact_catalog(raw_units)}
    source_by_ref = {cast(str, item["responsibility_ref"]): item for item in source_catalog}
    output_by_ref = {cast(str, item["responsibility_ref"]): item for item in output_catalog}

    conditions_by_unit: dict[str, list[dict[str, str]]] = {unit_id: [] for unit_id in unit_ids}
    common_conditions: list[dict[str, str]] = []
    known_refs = {item["constraint_ref"] for item in constraint_catalog}
    seen_condition_refs: set[str] = set()
    for raw in raw_condition_assignments:
        constraint_ref = raw.get("constraint_ref")
        applies = raw.get("applies_to_unit_ids")
        if (
            not isinstance(constraint_ref, str)
            or constraint_ref not in known_refs
            or constraint_ref in seen_condition_refs
            or not isinstance(applies, list)
            or not applies
            or not set(cast(list[str], applies)).issubset(unit_id_set)
        ):
            raise ValueError("condition attribution is not exact and closed")
        seen_condition_refs.add(constraint_ref)
        base = {"constraint_ref": constraint_ref}
        applies_set = set(cast(list[str], applies))
        if applies_set == unit_id_set:
            common_conditions.append(base)
        else:
            for unit_id in unit_ids:
                if unit_id in applies_set:
                    conditions_by_unit[unit_id].append(dict(base))

    dependencies_by_target: dict[str, list[dict[str, object]]] = {
        unit_id: [] for unit_id in unit_ids
    }
    relations: list[dict[str, object]] = []
    seen_relations: set[tuple[str, str]] = set()
    for raw in raw_relations:
        artifact_ref = raw.get("artifact_ref")
        target_id = raw.get("target_unit_id")
        artifact = artifacts_by_ref.get(cast(str, artifact_ref))
        pair = (cast(str, artifact_ref), cast(str, target_id))
        if (
            artifact is None
            or target_id not in unit_id_set
            or artifact["source_unit_id"] == target_id
            or pair in seen_relations
        ):
            raise ValueError("work relation attribution is not exact and closed")
        seen_relations.add(pair)
        artifact_kind = artifact["artifact_kind"]
        ref_field = "product_ref" if artifact_kind == "WORK_PRODUCT" else "specification_ref"
        dependencies_by_target[cast(str, target_id)].append(
            {"kind": artifact_kind, ref_field: artifact_ref}
        )
        relations.append(
            {
                "relation_id": f"relation-{len(relations) + 1}",
                "kind": (
                    "CONSUMES_WORK_PRODUCT"
                    if artifact_kind == "WORK_PRODUCT"
                    else "CONSUMES_PLANNED_SPECIFICATION"
                ),
                "source_unit_id": artifact["source_unit_id"],
                "target_unit_id": target_id,
                "artifact_ref": artifact_ref,
            }
        )

    units: list[dict[str, object]] = []
    used_source_refs: set[str] = set()
    used_output_refs: set[str] = set()
    for unit_id in unit_ids:
        raw = raw_by_id[unit_id]
        bindings: list[dict[str, object]] = []
        for source_ref in cast(list[str], raw.get("source_responsibility_refs", [])):
            source = source_by_ref.get(source_ref)
            if source is None:
                raise ValueError(f"{unit_id}: unknown source responsibility ref")
            used_source_refs.add(source_ref)
            bindings.append(
                {
                    "kind": "RESOURCE",
                    "resource_type": source["resource_type"],
                    "required_information": list(
                        cast(list[str], source.get("required_information", []))
                    ),
                }
            )
        bindings.extend(dependencies_by_target[unit_id])
        output_kind = raw["output_kind"]
        if output_kind == "USER_RESPONSE":
            output: dict[str, object] = {"kind": "USER_RESPONSE"}
        elif output_kind == "INTERMEDIATE_WORK_PRODUCT":
            output = {
                "kind": output_kind,
                "product_ref": f"work-product:{unit_id}",
                "product_kind": raw["product_kind"],
            }
        else:
            output_ref = cast(str, raw.get("output_responsibility_ref"))
            output_responsibility = output_by_ref.get(output_ref)
            if output_responsibility is None or output_ref in used_output_refs:
                raise ValueError(f"{unit_id}: invalid output responsibility ref")
            used_output_refs.add(output_ref)
            output = {
                "kind": output_kind,
                "specification_ref": f"planned-specification:{unit_id}",
                "resource_type": output_responsibility["resource_type"],
                "effect": output_responsibility["effect"],
            }
        units.append(
            {
                "unit_id": unit_id,
                "objective": raw["objective"],
                "operation": raw["operation"],
                "input_bindings": bindings,
                "condition_refs": conditions_by_unit[unit_id],
                "output": output,
            }
        )
    if used_source_refs != set(source_by_ref):
        raise ValueError("every validated source responsibility must be assigned")
    if used_output_refs != set(output_by_ref):
        raise ValueError("every validated output responsibility must be assigned exactly once")
    return cast(
        RequestedWorkDefinitionV1,
        {
            "schema_version": 1,
            "common_condition_refs": common_conditions,
            "work_units": units,
            "relations": relations,
        },
    )


def _materialize(
    runtime: _CandidateRuntime,
    *,
    unit: RequestedWorkUnitV1,
    evidence: Sequence[EvidenceProjectionV1],
    upstream_products: Sequence[IntermediateWorkProductV1],
    conditions: Sequence[ConstraintProjectionV1],
) -> dict[str, object]:
    output = unit["output"]
    assert output["kind"] == "INTERMEDIATE_WORK_PRODUCT"
    evidence_refs = [item["evidence_ref"] for item in evidence]
    upstream_refs = [item["product_ref"] for item in upstream_products]
    return runtime.invoke(
        prompt_id="work_product.materialize",
        source_name="work_product.materialize.md",
        prompt_input={
            "work_unit": unit,
            "evidence": list(evidence),
            "upstream_work_products": list(upstream_products),
            "conditions": list(conditions),
            "required_identity": {
                "product_ref": output["product_ref"],
                "producer_work_unit_id": unit["unit_id"],
                "producer_boundary": "INTERMEDIATE_WORK_PRODUCT_MATERIALIZER",
                "product_kind": output["product_kind"],
            },
        },
        schema=OutputSchemaDefinition(
            schema_version="intermediate-work-product-v1-eval",
            json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "product_ref",
                    "producer_work_unit_id",
                    "producer_boundary",
                    "product_kind",
                    "content",
                    "evidence_refs",
                    "consumed_product_refs",
                ],
                "properties": {
                    "schema_version": {"const": 1},
                    "product_ref": {"const": output["product_ref"]},
                    "producer_work_unit_id": {"const": unit["unit_id"]},
                    "producer_boundary": {"const": "INTERMEDIATE_WORK_PRODUCT_MATERIALIZER"},
                    "product_kind": {"const": output["product_kind"]},
                    "content": {"type": "string", "minLength": 1},
                    "evidence_refs": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"enum": evidence_refs},
                    },
                    "consumed_product_refs": {"const": upstream_refs},
                },
            },
        ),
    )


def _consume(
    runtime: _CandidateRuntime,
    *,
    unit: RequestedWorkUnitV1,
    evidence: Sequence[EvidenceProjectionV1],
    products: Sequence[IntermediateWorkProductV1],
    specifications: Sequence[PlannedActionSpecificationV1],
    conditions: Sequence[ConstraintProjectionV1],
) -> dict[str, object]:
    output = unit["output"]
    product_refs = [item["product_ref"] for item in products]
    specification_refs = [item["specification_ref"] for item in specifications]
    prompt_input = {
        "work_unit": unit,
        "evidence": list(evidence),
        "work_products": list(products),
        "planned_specifications": list(specifications),
        "conditions": list(conditions),
    }
    if output["kind"] == "USER_RESPONSE":
        schema = OutputSchemaDefinition(
            schema_version="work-user-response-v1-eval",
            json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "producer_work_unit_id",
                    "content",
                    "consumed_product_refs",
                ],
                "properties": {
                    "schema_version": {"const": 1},
                    "producer_work_unit_id": {"const": unit["unit_id"]},
                    "content": {"type": "string", "minLength": 1},
                    "consumed_product_refs": {"const": product_refs},
                },
            },
        )
    else:
        schema = OutputSchemaDefinition(
            schema_version="planned-action-specification-v1-eval",
            json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "specification_ref",
                    "producer_work_unit_id",
                    "resource_type",
                    "effect",
                    "status",
                    "content",
                    "consumed_product_refs",
                    "consumed_specification_refs",
                ],
                "properties": {
                    "schema_version": {"const": 1},
                    "specification_ref": {"const": output["specification_ref"]},
                    "producer_work_unit_id": {"const": unit["unit_id"]},
                    "resource_type": {"const": output["resource_type"]},
                    "effect": {"const": output["effect"]},
                    "status": {"const": "PLANNED_NOT_EXECUTED"},
                    "content": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["title", "body"],
                        "properties": {
                            "title": {"type": "string", "minLength": 1},
                            "body": {"type": "string", "minLength": 1},
                        },
                    },
                    "consumed_product_refs": {"const": product_refs},
                    "consumed_specification_refs": {"const": specification_refs},
                },
            },
        )
    return runtime.invoke(
        prompt_id="work_product.consume",
        source_name="work_product.consume.md",
        prompt_input=prompt_input,
        schema=schema,
    )


def _intent_projection(database_path: Path) -> dict[str, object]:
    if not database_path.is_file():
        raise ValueError(f"validated RequestIntent checkpoint is missing: {database_path}")
    state = _load_latest_state(database_path)
    intent = state.get("request_intent")
    if not isinstance(intent, Mapping):
        raise ValueError("validated RequestIntent is unavailable for the candidate input")
    raw_constraints = intent.get("constraints")
    responsibilities = intent.get("resource_responsibilities")
    meta = intent.get("meta")
    if not isinstance(raw_constraints, list) or not isinstance(responsibilities, Mapping):
        raise ValueError("validated RequestIntent projection is incomplete")
    artifact_id = meta.get("artifact_id") if isinstance(meta, Mapping) else None
    revision = meta.get("revision") if isinstance(meta, Mapping) else None
    if not isinstance(artifact_id, str) or not isinstance(revision, int):
        raise ValueError("validated RequestIntent identity is unavailable")
    catalog: list[ConstraintProjectionV1] = []
    for index, raw in enumerate(raw_constraints):
        if not isinstance(raw, Mapping):
            raise ValueError("validated RequestIntent contains an invalid constraint")
        kind = raw.get("kind")
        field = raw.get("field")
        value = raw.get("value")
        if (
            not isinstance(kind, str)
            or not isinstance(field, str)
            or not isinstance(value, str | list)
        ):
            raise ValueError("validated RequestIntent constraint cannot be projected")
        catalog.append(
            {
                "constraint_ref": f"request-intent:{artifact_id}:{revision}:{index}",
                "kind": kind,
                "field": field,
                "value": cast(str | list[str], value),
            }
        )
    raw_sources = responsibilities.get("source_reads")
    raw_outputs = responsibilities.get("outputs")
    if not isinstance(raw_sources, list) or not isinstance(raw_outputs, list):
        raise ValueError("validated RequestIntent responsibilities are incomplete")
    sources = [
        {"responsibility_ref": f"request-intent:{artifact_id}:{revision}:source:{index}", **item}
        for index, item in enumerate(raw_sources)
        if isinstance(item, Mapping)
    ]
    outputs = [
        {"responsibility_ref": f"request-intent:{artifact_id}:{revision}:output:{index}", **item}
        for index, item in enumerate(raw_outputs)
        if isinstance(item, Mapping)
    ]
    if len(sources) != len(raw_sources) or len(outputs) != len(raw_outputs):
        raise ValueError("validated RequestIntent responsibility cannot be projected")
    return {
        "artifact_id": artifact_id,
        "revision": revision,
        "goal": intent.get("goal"),
        "completion_conditions": intent.get("completion_conditions", []),
        "constraint_catalog": catalog,
        "source_responsibilities": sources,
        "output_responsibilities": outputs,
    }


def _fixture_evidence(
    fixtures: Mapping[str, object],
    pack_ids: Sequence[str],
) -> list[EvidenceProjectionV1]:
    result: list[EvidenceProjectionV1] = []
    for pack_id in pack_ids:
        pack = fixtures.get(pack_id)
        if not isinstance(pack, Mapping):
            continue
        resources = pack.get("resources")
        if not isinstance(resources, list):
            continue
        for index, resource in enumerate(resources):
            if not isinstance(resource, Mapping):
                continue
            raw_type = resource.get("resource_type")
            if not isinstance(raw_type, str):
                continue
            resource_type = raw_type.upper()
            compact = {
                key: value
                for key, value in resource.items()
                if key
                not in {
                    "body_sha256",
                    "description_sha256",
                    "etag",
                    "notes_sha256",
                    "version",
                }
            }
            result.append(
                {
                    "evidence_ref": f"fixture:{pack_id}:{resource_type}:{index}",
                    "resource_type": resource_type,
                    "content": json.dumps(compact, ensure_ascii=False, sort_keys=True),
                }
            )
    return result


def _allowed_external_outputs() -> list[dict[str, str]]:
    return [
        {"resource_type": resource_type, "effect": effect}
        for effect, resource_types in WRITE_EFFECT_RESOURCE_TYPES.items()
        for resource_type in sorted(resource_types)
    ]


def _record(
    *,
    case_id: str,
    result: Mapping[str, object],
    calls: Sequence[Mapping[str, object]],
    duration_ms: int,
    error: Exception | None,
) -> dict[str, object]:
    definition = result.get("work_definition")
    units = (
        cast(RequestedWorkDefinitionV1, definition)["work_units"]
        if isinstance(definition, Mapping)
        else []
    )
    products = result.get("intermediate_work_products", [])
    specifications = result.get("planned_action_specifications", [])
    responses = result.get("user_responses", [])
    return {
        "case_id": case_id,
        "outcome": "COMPLETED" if error is None else "FAILED",
        "error_type": type(error).__name__ if error else None,
        "error": str(error) if error else None,
        "work_unit_count": len(units),
        "operations": [unit["operation"] for unit in units],
        "relation_count": (
            len(cast(RequestedWorkDefinitionV1, definition)["relations"])
            if isinstance(definition, Mapping)
            else 0
        ),
        "intermediate_product_count": len(products) if isinstance(products, list) else 0,
        "planned_specification_count": (
            len(specifications) if isinstance(specifications, list) else 0
        ),
        "user_response_count": len(responses) if isinstance(responses, list) else 0,
        "consumed_product_refs": [
            ref
            for item in cast(list[dict[str, object]], specifications)
            for ref in cast(list[str], item.get("consumed_product_refs", []))
        ],
        "consumed_specification_refs": [
            ref
            for item in cast(list[dict[str, object]], specifications)
            for ref in cast(list[str], item.get("consumed_specification_refs", []))
        ],
        "external_write_count": result.get("external_write_count", 0),
        "llm_call_count": len(calls),
        "input_tokens": sum(int(item.get("input_tokens") or 0) for item in calls),
        "output_tokens": sum(int(item.get("output_tokens") or 0) for item in calls),
        "provider_latency_ms": sum(int(item.get("latency_ms") or 0) for item in calls),
        "duration_ms": duration_ms,
        "work_definition": definition,
        "constraint_catalog": result.get("constraint_catalog", []),
        "intermediate_work_products": products,
        "planned_action_specifications": specifications,
        "user_responses": responses,
    }


def _write_result(
    path: Path,
    *,
    records: list[dict[str, object]],
    case_ids: Sequence[str],
    digest: str,
    temperature: float,
    seed: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "binding": {
            "candidate_id": "ru-connected-work-v4",
            "scope": "BOUNDED_COMPILED_COMPONENT",
            "dataset_sha256": normalized_sha256(DEFAULT_DATASET_PATH),
            "fixture_sha256": hashlib.sha256(PROVIDER_FIXTURE.read_bytes()).hexdigest(),
            "model_id": MODEL_ID,
            "model_digest": digest,
            "temperature": temperature,
            "seed": seed,
            "case_ids": list(case_ids),
            "trials_per_case": 1,
            "provider_write_enabled": False,
        },
        "cases": records,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
