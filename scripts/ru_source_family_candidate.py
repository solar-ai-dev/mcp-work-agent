"""Inactive two-stage Source-family selection with the existing Source owner."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from evaluation.request_semantic_authority_candidate import (
    GoalOutputModalityAuthorityCandidate,
    _work_unit_ids,
)
from scripts.ru_observation import observe_local_calls

from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

FAMILY_PROMPT_PATH = Path(__file__).resolve().parents[1] / (
    "evaluation/prompt_candidates/ru-source-family-v15/family.md"
)
SOURCE_PROMPT_ID = "request_understanding.identify_source_dependencies"


def family_catalog(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    families: dict[str, list[str]] = {}
    for item in candidates:
        resource = str(item["resource_type"])
        families.setdefault(coarse_resource_category(resource), []).append(resource)
    return [{"family": key, "resource_types": value} for key, value in families.items()]


def family_schema(families: Sequence[str]) -> OutputSchemaDefinition:
    if not families or len(set(families)) != len(families):
        raise ValueError("Source-family candidates must be nonempty and unique")
    return OutputSchemaDefinition(
        schema_version="evaluation-source-family-v15",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["source_families"],
            "properties": {
                "source_families": {
                    "type": "array",
                    "maxItems": len(families),
                    "uniqueItems": True,
                    "items": {"enum": list(families)},
                }
            },
        },
    )


def expand_source_subset(
    raw: Mapping[str, Any],
    *,
    subset: Sequence[Mapping[str, Any]],
    all_candidates: Sequence[Mapping[str, Any]],
    work_unit_ids: Sequence[str],
    full_schema: OutputSchemaDefinition,
) -> dict[str, Any]:
    if subset:
        source_ops.validate_source_dependency_candidate(
            raw, source_candidates=cast(Any, subset), work_unit_ids=work_unit_ids
        )
    elif raw != {"source_dependencies": []}:
        raise ValueError("empty family selection cannot introduce Source decisions")
    selected = {item["resource_type"]: item for item in raw["source_dependencies"]}
    expanded = {
        "source_dependencies": [
            deepcopy(selected[item["resource_type"]])
            if item["resource_type"] in selected
            else {"resource_type": item["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
            for item in all_candidates
        ]
    }
    errors = validate_output_schema(expanded, full_schema.json_schema)
    if errors:
        raise ValueError(f"expanded Source decisions fail caller schema: {'; '.join(errors)}")
    source_ops.validate_source_dependency_candidate(
        expanded, source_candidates=cast(Any, all_candidates), work_unit_ids=work_unit_ids
    )
    return expanded


class SourceFamilyCandidate(GoalOutputModalityAuthorityCandidate):
    """V4 Goal/Output authority; family selection narrows one existing Source call."""

    @property
    def binding(self) -> dict[str, object]:
        return {
            **super().binding,
            "candidate_id": "ru-source-family-v15",
            "source_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "family_prompt_sha256": hashlib.sha256(FAMILY_PROMPT_PATH.read_bytes()).hexdigest(),
            "family_schema_version": "evaluation-source-family-v15",
        }

    def infer(
        self, requested_mode: Any, prompt_ref: Any, input_projection: Any, output_schema_ref: Any
    ) -> Any:
        if prompt_ref.prompt_id != SOURCE_PROMPT_ID:
            return super().infer(requested_mode, prompt_ref, input_projection, output_schema_ref)
        base = input_projection.get("base_projection", input_projection)
        candidates = base["source_candidates"]
        work_ids = _work_unit_ids(base)
        catalog = family_catalog(candidates)
        first_input = {
            key: deepcopy(base[key])
            for key in (
                "user_request",
                "selected_resource_refs",
                "requested_work",
                "confirmation_response",
            )
            if key in base
        }
        first_input["available_source_families"] = catalog
        instruction = FAMILY_PROMPT_PATH.read_text(encoding="utf-8").strip()
        first_event: dict[str, Any] = {
            "operation": "SOURCE_FAMILY_SELECTION",
            "attempt": "REVISION" if "failure_record" in input_projection else "FIRST",
            "input": deepcopy(first_input),
            "transport_attempts": [],
        }
        self.events.append(first_event)
        try:
            with observe_local_calls(first_event["transport_attempts"]):
                raw, first, attempts = self._invoke_candidate(
                    requested_mode=requested_mode,
                    prompt_ref=replace(
                        prompt_ref,
                        prompt_id="evaluation.select_source_families",
                        prompt_version="v15",
                        content_hash=hashlib.sha256(instruction.encode()).hexdigest(),
                    ),
                    prompt_input=first_input,
                    schema=family_schema([item["family"] for item in catalog]),
                    instruction=instruction,
                )
            first_event.update(raw_output=deepcopy(raw), provider_attempts=attempts)
            errors = validate_output_schema(
                raw, family_schema([item["family"] for item in catalog]).json_schema
            )
            if errors:
                raise ValueError(f"invalid Source-family selection: {'; '.join(errors)}")
        except Exception as error:
            first_event["error_type"] = type(error).__name__
            raise
        families = set(cast(Sequence[str], raw["source_families"]))
        subset = [
            deepcopy(item)
            for item in candidates
            if coarse_resource_category(item["resource_type"]) in families
        ]
        if not subset:
            expanded = expand_source_subset(
                {"source_dependencies": []},
                subset=[],
                all_candidates=candidates,
                work_unit_ids=work_ids,
                full_schema=output_schema_ref,
            )
            first_event.update(materialized_output=deepcopy(expanded), source_owner_skipped=True)
            return replace(first, structured_output=expanded)
        second_base = {**deepcopy(base), "source_candidates": subset}
        second_input = second_base
        if "base_projection" in input_projection:
            second_input = {**deepcopy(input_projection), "base_projection": second_base}
            previous = second_input.get("candidate_output")
            if isinstance(previous, dict) and isinstance(previous.get("source_dependencies"), list):
                allowed = {item["resource_type"] for item in subset}
                previous["source_dependencies"] = [
                    item
                    for item in previous["source_dependencies"]
                    if item.get("resource_type") in allowed
                ]
        second_schema = source_ops.build_source_dependency_output_schema(
            subset, work_unit_ids=work_ids
        )
        second_event: dict[str, Any] = {
            "operation": "SOURCE_OWNER_SUBSET",
            "input": deepcopy(second_input),
            "transport_attempts": [],
        }
        self.events.append(second_event)
        self.additional_provider_call_count += 1
        try:
            with observe_local_calls(second_event["transport_attempts"]):
                second = self._delegate.infer(
                    requested_mode, prompt_ref, second_input, second_schema
                )
            second_event["raw_output"] = deepcopy(second.structured_output)
            expanded = expand_source_subset(
                second.structured_output,
                subset=subset,
                all_candidates=candidates,
                work_unit_ids=work_ids,
                full_schema=output_schema_ref,
            )
            second_event["materialized_output"] = deepcopy(expanded)
        except Exception as error:
            second_event["error_type"] = type(error).__name__
            raise
        finally:
            self.additional_provider_call_count += max(
                0, len(second_event["transport_attempts"]) - 1
            )
        return replace(
            second,
            structured_output=expanded,
            input_tokens=first.input_tokens + second.input_tokens,
            output_tokens=first.output_tokens + second.output_tokens,
            latency_ms=first.latency_ms + second.latency_ms,
        )
