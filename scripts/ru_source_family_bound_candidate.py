"""Inactive Source refinement with a frozen, model-owned family decision."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from evaluation.request_semantic_authority_candidate import _cached_result, _work_unit_ids
from scripts.ru_observation import observe_local_calls
from scripts.ru_source_family_candidate import (
    SOURCE_PROMPT_ID,
    SourceFamilyCandidate,
    expand_source_subset,
    family_catalog,
    family_schema,
)

from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

_HANDOFF_INSTRUCTION = (
    "selected_source_families는 앞선 Source family owner가 확정한 조회 필요 family다. "
    "이번 책임은 각 family 안에서 필요한 구체 Resource와 조회 정보를 선택하는 것이다. "
    "선택된 각 family에 하나 이상의 SOURCE_REQUIRED를 결속하고, "
    "family 필요 여부나 사용자 업무 의미는 다시 생성하지 않는다."
)


def _input_hash(value: object) -> str:
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()


def bound_family_source_schema(
    subset: Sequence[Mapping[str, Any]],
    *,
    selected_families: Sequence[str],
    work_unit_ids: Sequence[str],
) -> OutputSchemaDefinition:
    """Preserve the upstream positive decision without choosing a subtype or fact."""
    catalog = family_catalog(subset)
    resources = {entry["family"]: entry["resource_types"] for entry in catalog}
    if not selected_families or len(set(selected_families)) != len(selected_families):
        raise ValueError("bound Source families must be nonempty and unique")
    if set(resources) != set(selected_families):
        raise ValueError("Source subset must exactly match selected families")
    base = source_ops.build_source_dependency_output_schema(
        cast(Any, subset), work_unit_ids=work_unit_ids
    )
    schema = deepcopy(base.json_schema)
    decisions = schema["properties"]["source_dependencies"]
    decisions["allOf"].extend(
        [
            {
                "contains": {
                    "type": "object",
                    "required": ["resource_type", "dependency"],
                    "properties": {
                        "resource_type": {"enum": resources[family]},
                        "dependency": {"const": "SOURCE_REQUIRED"},
                    },
                },
                "minContains": 1,
            }
            for family in selected_families
        ]
    )
    return OutputSchemaDefinition(
        schema_version="evaluation-bound-source-family-v18", json_schema=schema
    )


class BoundSourceFamilyCandidate(SourceFamilyCandidate):
    """Replay only the exact v15 family input; run one bounded Source refinement."""

    def __init__(self, *, family_replay_path: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        payload = family_replay_path.read_bytes()
        self._family_replay_sha256 = hashlib.sha256(payload).hexdigest()
        replay = json.loads(payload)
        self._frozen_families: dict[str, dict[str, Any]] = {}
        for case in replay["cases"]:
            for event in case.get("semantic_candidate_events", []):
                if event["operation"] != "SOURCE_FAMILY_SELECTION" or "raw_output" not in event:
                    continue
                key = _input_hash(event["input"])
                record = {
                    "input": deepcopy(event["input"]),
                    "raw_output": deepcopy(event["raw_output"]),
                    "case_id": case["case_id"],
                }
                if key in self._frozen_families and self._frozen_families[key] != record:
                    raise ValueError("ambiguous frozen family decision for identical input")
                self._frozen_families[key] = record
        if not self._frozen_families:
            raise ValueError("frozen family replay contains no model decisions")
        self._source_instruction = (
            PromptRegistry().source_text(SOURCE_PROMPT_ID).strip() + "\n\n" + _HANDOFF_INSTRUCTION
        )

    @property
    def binding(self) -> dict[str, object]:
        return {
            **super().binding,
            "candidate_id": "ru-bound-source-family-v18",
            "source_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "family_replay_sha256": self._family_replay_sha256,
            "family_calls_reused_not_reexecuted": True,
            "source_instruction_sha256": hashlib.sha256(
                self._source_instruction.encode()
            ).hexdigest(),
            "source_schema_version": "evaluation-bound-source-family-v18",
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
        frozen_input = {
            key: deepcopy(base[key])
            for key in (
                "user_request",
                "selected_resource_refs",
                "requested_work",
                "confirmation_response",
            )
            if key in base
        }
        frozen_input["available_source_families"] = catalog
        input_hash = _input_hash(frozen_input)
        frozen = self._frozen_families.get(input_hash)
        if frozen is None:
            raise ValueError("Source family replay requires an identical frozen first-stage input")
        raw_family = frozen["raw_output"]
        errors = validate_output_schema(
            raw_family, family_schema([entry["family"] for entry in catalog]).json_schema
        )
        if errors:
            raise ValueError(f"invalid frozen Source family decision: {'; '.join(errors)}")
        families = raw_family["source_families"]
        self.events.append(
            {
                "operation": "SOURCE_FAMILY_FROZEN_REPLAY",
                "input": deepcopy(frozen_input),
                "input_sha256": input_hash,
                "replay_sha256": self._family_replay_sha256,
                "origin_case_id": frozen["case_id"],
                "raw_output": deepcopy(raw_family),
                "new_provider_calls": 0,
            }
        )
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
            self.cached_response_count += 1
            return _cached_result(model_id=self._model_id, structured_output=expanded)
        second_base = {
            **deepcopy(base),
            "source_candidates": subset,
            "selected_source_families": list(families),
        }
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
        schema = bound_family_source_schema(
            subset, selected_families=families, work_unit_ids=work_ids
        )
        event: dict[str, Any] = {
            "operation": "SOURCE_OWNER_BOUND_FAMILY",
            "input": deepcopy(second_input),
            "transport_attempts": [],
        }
        self.events.append(event)
        try:
            with observe_local_calls(event["transport_attempts"]):
                raw, result, attempts = self._invoke_candidate(
                    requested_mode=requested_mode,
                    prompt_ref=replace(
                        prompt_ref,
                        prompt_id="evaluation.refine_selected_source_families",
                        prompt_version="v18",
                        content_hash=hashlib.sha256(self._source_instruction.encode()).hexdigest(),
                    ),
                    prompt_input=second_input,
                    schema=schema,
                    instruction=self._source_instruction,
                )
            event.update(raw_output=deepcopy(raw), provider_attempts=attempts)
            expanded = expand_source_subset(
                raw,
                subset=subset,
                all_candidates=candidates,
                work_unit_ids=work_ids,
                full_schema=output_schema_ref,
            )
            event["materialized_output"] = deepcopy(expanded)
        except Exception as error:
            event["error_type"] = type(error).__name__
            raise
        return replace(result, structured_output=expanded)
