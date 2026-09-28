"""Inactive Source membership -> frozen-member details representation candidate.

No runtime or model is invoked here. A diagnostic caller owns call budgets and
raw observations; this module only builds payloads and validates/materializes the
two explicit outputs into the unchanged Product Source decision contract.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.source_dependency_decision import (  # noqa: E501
    SourceDependencyCandidateV1,
    SourceDependencyDecisionCandidateV1,
)
from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_output_schema,
    validate_source_dependency_candidate,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

ROOT = Path(__file__).resolve().parents[1]
PROMPT_ID = "request_understanding.identify_source_dependencies"
PROMPT_PATHS = {
    stage: ROOT / f"evaluation/prompt_candidates/ru-source-membership-v43/{stage}.md"
    for stage in ("membership", "details")
}


def _resource_types(candidates: Sequence[SourceDependencyCandidateV1]) -> list[str]:
    resource_types = [candidate["resource_type"] for candidate in candidates]
    if (
        not resource_types
        or any(not isinstance(item, str) or not item for item in resource_types)
        or len(resource_types) != len(set(resource_types))
    ):
        raise ValueError("Source candidates must be non-empty and unique")
    for candidate in candidates:
        facts = candidate["owned_fact_kinds"]
        if not facts or len(facts) != len(set(facts)):
            raise ValueError("Source candidates require unique owned fact kinds")
    return resource_types


def _closed_object(properties: Mapping[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": deepcopy(dict(properties)),
    }


def build_membership_schema(
    candidates: Sequence[SourceDependencyCandidateV1],
) -> OutputSchemaDefinition:
    """Require an explicit positive/negative decision for every current Resource."""
    decisions = _closed_object(
        {
            resource: {"enum": ["SOURCE_REQUIRED", "SOURCE_NOT_REQUIRED"]}
            for resource in _resource_types(candidates)
        }
    )
    return OutputSchemaDefinition(
        schema_version="evaluation-source-membership-v43",
        json_schema=_closed_object({"resource_decisions": decisions}),
    )


def validate_membership(
    value: object, candidates: Sequence[SourceDependencyCandidateV1]
) -> dict[str, dict[str, str]]:
    errors = validate_output_schema(value, build_membership_schema(candidates).json_schema)
    if errors:
        raise ValueError(f"invalid Source membership: {'; '.join(errors)}")
    return cast(dict[str, dict[str, str]], deepcopy(value))


def build_details_schema(
    selected_candidates: Sequence[SourceDependencyCandidateV1], work_ids: Sequence[str]
) -> OutputSchemaDefinition:
    """Derive existing positive fields, without allowing dependency reselection."""
    resources = _resource_types(selected_candidates)
    current = build_source_dependency_output_schema(
        selected_candidates, work_unit_ids=work_ids
    ).json_schema
    variants = cast(Any, current)["properties"]["source_dependencies"]["items"]["oneOf"]
    positive = next(
        item
        for item in variants
        if item["properties"]["dependency"].get("const") == "SOURCE_REQUIRED"
    )
    fields = {
        name: deepcopy(positive["properties"][name])
        for name in positive["required"]
        if name not in {"resource_type", "dependency"}
    }
    details = _closed_object({resource: _closed_object(fields) for resource in resources})
    return OutputSchemaDefinition(
        schema_version="evaluation-source-details-v43",
        json_schema=_closed_object({"source_details": details}),
    )


def materialize_decisions(
    membership: object,
    details: object | None,
    all_candidates: Sequence[SourceDependencyCandidateV1],
    work_ids: Sequence[str],
) -> SourceDependencyDecisionCandidateV1:
    """Carry explicit membership and validated details, never infer missing values."""
    decisions = validate_membership(membership, all_candidates)["resource_decisions"]
    selected = [
        candidate
        for candidate in all_candidates
        if decisions[candidate["resource_type"]] == "SOURCE_REQUIRED"
    ]
    detail_values: Mapping[str, Any] = {}
    if selected:
        errors = validate_output_schema(
            details, build_details_schema(selected, work_ids).json_schema
        )
        if errors:
            raise ValueError(f"invalid Source details: {'; '.join(errors)}")
        detail_values = cast(Mapping[str, Any], details)["source_details"]
    elif details is not None:
        raise ValueError("all-negative membership requires no details response or call")
    expanded: dict[str, Any] = {"source_dependencies": []}
    for candidate in all_candidates:
        resource = candidate["resource_type"]
        item: dict[str, Any] = {"resource_type": resource, "dependency": decisions[resource]}
        if decisions[resource] == "SOURCE_REQUIRED":
            item.update(deepcopy(detail_values[resource]))
        expanded["source_dependencies"].append(item)
    return validate_source_dependency_candidate(
        expanded, source_candidates=all_candidates, work_unit_ids=work_ids
    )


def build_stage_payload(
    original_payload: Mapping[str, Any],
    *,
    stage: Literal["membership", "details"],
    membership: object | None = None,
) -> dict[str, Any] | None:
    """Replace only declared stage instruction/schema over a verified Product wire.

    Stage two additionally receives the validated, frozen Resource decisions.
    Its schema closes the details to those positive keys. All original input and
    transport options are retained. A zero-member result returns None so callers
    cannot mistake an empty second-stage response for a generated decision.
    """
    if stage not in PROMPT_PATHS:
        raise ValueError("unknown Source candidate stage")
    body = json.loads(original_payload["prompt"])
    projection = body["input"]
    if any(key in projection for key in ("base_projection", "failure_record", "candidate_output")):
        raise ValueError("membership diagnostic accepts only original FIRST input")
    if "resource_decisions" in projection:
        raise ValueError("original Source input must not contain candidate membership")
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    expected_ref = {
        "prompt_id": ref.prompt_id,
        "prompt_version": ref.prompt_version,
        "content_hash": ref.content_hash,
    }
    if body["prompt_ref"] != expected_ref:
        raise ValueError("original Source PromptRef differs from current Product")
    candidates = projection["source_candidates"]
    work_ids = [unit["unit_id"] for unit in projection["requested_work"]["work_units"]]
    original_schema = build_source_dependency_output_schema(
        candidates, work_unit_ids=work_ids
    ).json_schema
    if body["output_schema"] != original_schema or original_payload["format"] != original_schema:
        raise ValueError("original Source schema/format differs from Product")
    instruction = assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION)
    if original_payload["system"] != instruction:
        raise ValueError("original Source assembly differs from current Product")
    stage_input = deepcopy(projection)
    if stage == "membership":
        if membership is not None:
            raise ValueError("membership stage must not consume a prior decision")
        schema = build_membership_schema(candidates)
    else:
        validated = validate_membership(membership, candidates)
        selected = [
            item
            for item in candidates
            if validated["resource_decisions"][item["resource_type"]] == "SOURCE_REQUIRED"
        ]
        if not selected:
            return None
        stage_input["resource_decisions"] = validated["resource_decisions"]
        schema = build_details_schema(selected, work_ids)

    source_bytes = PROMPT_PATHS[stage].read_bytes()
    source = source_bytes.decode("utf-8")
    candidate_ref = {
        **expected_ref,
        "prompt_version": f"evaluation-v43-{stage}",
        "content_hash": hashlib.sha256(source_bytes).hexdigest(),
    }
    prefix = registry.source_text(PROMPT_ID).rstrip()
    original_json = json.dumps(
        projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    tail = original_json + "\n"
    if not instruction.startswith(prefix + "\n\n") or not instruction.endswith(tail):
        raise ValueError("original Source assembly is not the supported FIRST envelope")
    context = instruction[len(prefix) : -len(tail)]
    payload = deepcopy(dict(original_payload))
    payload["system"] = (
        source.rstrip()
        + context
        + json.dumps(stage_input, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    payload["prompt"] = json.dumps(
        {"prompt_ref": candidate_ref, "input": stage_input, "output_schema": schema.json_schema},
        sort_keys=True,
        ensure_ascii=False,
    )
    payload["format"] = deepcopy(dict(schema.json_schema))
    return payload
