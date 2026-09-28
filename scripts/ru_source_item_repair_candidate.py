"""Inactive v23: repair only structurally invalid Source identity groups."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, cast
from unittest.mock import patch

from scripts.ru_observation import object_hash

from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
    SchemaRepairer,
    StructuredLLMProvider,
)

SOURCE_PROMPT_ID = "request_understanding.identify_source_dependencies"


@dataclass(frozen=True)
class _Partition:
    frozen: dict[str, dict[str, Any]]
    mutable_ids: tuple[str, ...]
    subset_input: dict[str, Any]
    subset_failed: dict[str, Any]
    subset_schema: OutputSchemaDefinition


def _partition(
    projection: Mapping[str, object],
    failed: object,
    schema: OutputSchemaDefinition,
) -> tuple[_Partition | None, str]:
    if not isinstance(failed, dict) or set(failed) != {"source_dependencies"}:
        return None, "UNPARTITIONABLE_ROOT_OR_PARSE_FAILURE"
    items = failed["source_dependencies"]
    if not isinstance(items, list):
        return None, "UNPARTITIONABLE_ROOT_OR_PARSE_FAILURE"
    base = projection.get("base_projection", projection)
    if not isinstance(base, Mapping):
        return None, "UNRECOGNIZED_SOURCE_INPUT"
    candidates = base.get("source_candidates")
    requested_work = base.get("requested_work")
    if not isinstance(candidates, list) or not isinstance(requested_work, Mapping):
        return None, "UNRECOGNIZED_SOURCE_INPUT"
    try:
        candidate_ids = [item["resource_type"] for item in candidates]
        work_ids = [item["unit_id"] for item in requested_work["work_units"]]
        original = None
        requires_source = False
        # Only this exact Product schema is understood; no other owner's repair changes.
        for require_source in (False, True):
            possible = source_ops.build_source_dependency_output_schema(
                cast(Any, candidates),
                require_at_least_one_source=require_source,
                work_unit_ids=work_ids,
            )
            if possible.json_schema == schema.json_schema:
                original, requires_source = possible, require_source
                break
    except (KeyError, TypeError, ValueError):
        return None, "UNRECOGNIZED_SOURCE_INPUT"
    if original is None:
        return None, "UNRECOGNIZED_SOURCE_SCHEMA"
    groups: dict[str, list[dict[str, Any]]] = {key: [] for key in candidate_ids}
    for item in items:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("resource_type"), str)
            or item["resource_type"] not in groups
        ):
            # Never invent/drop an unknown ID or guess which candidate it means.
            return None, "UNKNOWN_RESOURCE_OR_UNIDENTIFIABLE_ITEM"
        groups[item["resource_type"]].append(item)
    item_schema = cast(Any, original.json_schema)["properties"]["source_dependencies"]["items"]
    frozen = {
        key: deepcopy(group[0])
        for key, group in groups.items()
        if len(group) == 1 and not validate_output_schema(group[0], item_schema)
    }
    mutable_ids = tuple(key for key in candidate_ids if key not in frozen)
    if not frozen or not mutable_ids:
        return None, "NO_PARTIAL_STRUCTURAL_REPAIR"
    subset_candidates = [
        deepcopy(item) for item in candidates if item["resource_type"] in mutable_ids
    ]
    subset_schema = source_ops.build_source_dependency_output_schema(
        cast(Any, subset_candidates),
        require_at_least_one_source=requires_source
        and not any(item["dependency"] == "SOURCE_REQUIRED" for item in frozen.values()),
        work_unit_ids=work_ids,
    )
    return _Partition(
        frozen=frozen,
        mutable_ids=mutable_ids,
        subset_input={**deepcopy(dict(base)), "source_candidates": subset_candidates},
        subset_failed={
            "source_dependencies": [
                deepcopy(item) for item in items if item["resource_type"] in mutable_ids
            ],
        },
        subset_schema=subset_schema,
    ), "PARTIAL_STRUCTURAL_REPAIR"


@dataclass
class SourceItemSchemaRepairer:
    """Wrap the existing repairer/provider; do not replace the Product repair guard.

    Unknown Resource/root/parse failures retain existing full repair. An unknown
    WorkUnit makes its identifiable Source item invalid and therefore repairable;
    it is never rebound in code. Contradictory duplicates are all mutable. A
    structurally valid but semantically wrong item is deliberately frozen.
    """

    delegate: SchemaRepairer
    events: list[dict[str, Any]] = field(default_factory=list)

    def repair(
        self,
        *,
        provider: StructuredLLMProvider,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        failed_output: object,
        output_schema: OutputSchemaDefinition,
        runtime_policy: RuntimePolicy,
        api_key: str | None,
        attempt_no: int,
        max_attempts: int,
        failure_reason_code: str,
        validator_errors: tuple[str, ...],
    ) -> ProviderResponsePayload:
        kwargs = dict(
            provider=provider,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            failed_output=failed_output,
            output_schema=output_schema,
            runtime_policy=runtime_policy,
            api_key=api_key,
            attempt_no=attempt_no,
            max_attempts=max_attempts,
            failure_reason_code=failure_reason_code,
            validator_errors=validator_errors,
        )
        if prompt_ref.prompt_id != SOURCE_PROMPT_ID:
            return self.delegate.repair(**cast(Any, kwargs))
        if attempt_no != 1 or max_attempts < 1:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID, "v23 repair budget exhausted"
            )
        partition, reason = _partition(prompt_input, failed_output, output_schema)
        event: dict[str, Any] = {
            "operation": "SOURCE_ITEM_SCHEMA_REPAIR",
            "mode": "FULL_REPAIR_UNCHANGED" if partition is None else "LOCALIZED_REPAIR",
            "reason": reason,
            "original_input": deepcopy(prompt_input),
            "first_output": deepcopy(failed_output),
            "first_output_sha256": object_hash(failed_output),
            "sampling": {
                "temperature": runtime_policy.sampling_temperature,
                "seed": runtime_policy.sampling_seed,
                "timeout_seconds": runtime_policy.local_timeout_seconds,
            },
            "additional_repair_budget": 0,
        }
        self.events.append(event)
        if partition is None:
            return self.delegate.repair(**cast(Any, kwargs))
        event.update(
            frozen_items=deepcopy(partition.frozen),
            mutable_resource_ids=list(partition.mutable_ids),
            subset_input=deepcopy(partition.subset_input),
            subset_schema_sha256=object_hash(partition.subset_schema.json_schema),
        )
        try:
            payload = self.delegate.repair(
                **cast(
                    Any,
                    {
                        **kwargs,
                        "prompt_input": partition.subset_input,
                        "failed_output": partition.subset_failed,
                        "output_schema": partition.subset_schema,
                        "max_attempts": 1,
                        "validator_errors": tuple(
                            validate_output_schema(
                                partition.subset_failed,
                                partition.subset_schema.json_schema,
                            )
                        ),
                    },
                )
            )
            repaired = (
                json.loads(payload.content) if isinstance(payload.content, str) else payload.content
            )
            event["repair_output"] = deepcopy(repaired)
            errors = validate_output_schema(repaired, partition.subset_schema.json_schema)
            if errors:
                raise LLMInvocationError(
                    LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                    "localized Source repair remains invalid",
                    affected_field_paths=("$.source_dependencies",),
                )
            by_id = {
                item["resource_type"]: item for item in cast(Any, repaired)["source_dependencies"]
            }
            by_id.update(partition.frozen)
            # Preserve original unique-item order for the unchanged outer repair guard.
            ordered_ids = list(
                dict.fromkeys(
                    item["resource_type"]
                    for item in cast(Any, failed_output)["source_dependencies"]
                )
            )
            ordered_ids.extend(key for key in partition.mutable_ids if key not in ordered_ids)
            merged = {"source_dependencies": [deepcopy(by_id[key]) for key in ordered_ids]}
            errors = validate_output_schema(merged, output_schema.json_schema)
            merged_by_id = {item["resource_type"]: item for item in merged["source_dependencies"]}
            frozen_preserved = all(
                merged_by_id.get(key) == item for key, item in partition.frozen.items()
            )
            event.update(
                merged_output=deepcopy(merged),
                full_schema_errors=list(errors),
                frozen_items_preserved=frozen_preserved,
            )
            if errors or not frozen_preserved:
                raise LLMInvocationError(
                    LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                    "Source repair merge violated original contract",
                    affected_field_paths=("$.source_dependencies",),
                )
            return replace(payload, content=merged)
        except Exception as error:
            event["error_type"] = type(error).__name__
            raise


@contextmanager
def source_item_repair_candidate(runtime: Any, events: list[dict[str, Any]]) -> Iterator[None]:
    """Install around the existing Product router without replacing its validation."""
    if runtime.schema_repairer is None:
        raise ValueError("Source item repair requires the existing Product schema repairer")
    with patch.object(
        runtime,
        "schema_repairer",
        SourceItemSchemaRepairer(runtime.schema_repairer, events),
    ):
        yield
