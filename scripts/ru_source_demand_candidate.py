"""Inactive Source demand-first prototype; never imported by Product."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from evaluation.request_semantic_authority_candidate import (
    GoalOutputModalityAuthorityCandidate,
    _work_unit_ids,
)

from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

PROMPT_PATH = Path(__file__).resolve().parents[1] / (
    "evaluation/prompt_candidates/ru-source-demand-binding-v6/source.md"
)


def source_catalog(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "ref": f"s{index + 1:02}",
            "resource_type": candidate["resource_type"],
            "available_information": list(candidate["owned_fact_kinds"]),
        }
        for index, candidate in enumerate(candidates)
    ]


def demand_schema(refs: Sequence[str], work_ids: Sequence[str]) -> OutputSchemaDefinition:
    return OutputSchemaDefinition(
        schema_version="evaluation-source-demand-binding-v6",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["source_demands"],
            "properties": {
                "source_demands": {
                    "type": "array",
                    "maxItems": len(refs),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "information_needed",
                            "source_ref",
                            "target_scope",
                            "work_unit_ids",
                        ],
                        "properties": {
                            "information_needed": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 8,
                                "items": {"type": "string", "minLength": 1},
                            },
                            "source_ref": {"enum": list(refs)},
                            "target_scope": {"enum": ["SINGULAR", "CRITERIA"]},
                            "work_unit_ids": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"enum": list(work_ids)},
                            },
                        },
                    },
                }
            },
        },
    )


def expand_demands(raw: Mapping[str, Any], catalog: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_ref: dict[str, Any] = {}
    valid = {entry["ref"] for entry in catalog}
    for item in raw["source_demands"]:
        ref = item["source_ref"]
        if ref not in valid or ref in by_ref:
            raise ValueError("source refs must be closed and unique")
        by_ref[ref] = item
    decisions = []
    for entry in catalog:
        item = by_ref.get(entry["ref"])
        decision = {"resource_type": entry["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
        if item is not None:
            decision.update(
                dependency="SOURCE_REQUIRED",
                required_information=deepcopy(item["information_needed"]),
                target_scope=item["target_scope"],
                work_unit_ids=deepcopy(item["work_unit_ids"]),
            )
        decisions.append(decision)
    return {"source_dependencies": decisions}


class SourceDemandBindingCandidate(GoalOutputModalityAuthorityCandidate):
    @property
    def binding(self) -> dict[str, object]:
        return {
            **super().binding,
            "candidate_id": "ru-source-demand-binding-v6",
            "source_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_prompt_sha256": hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest(),
        }

    def infer(
        self, requested_mode: Any, prompt_ref: Any, input_projection: Any, output_schema_ref: Any
    ) -> Any:
        if prompt_ref.prompt_id != "request_understanding.identify_source_dependencies":
            return super().infer(requested_mode, prompt_ref, input_projection, output_schema_ref)
        base = input_projection.get("base_projection", input_projection)
        catalog = source_catalog(base["source_candidates"])
        # Do not substitute generated Goal for the original request. Confirmed
        # constraints/selection stay available, exactly as in the production input.
        candidate_input = {
            key: deepcopy(value) for key, value in base.items() if key != "source_candidates"
        }
        candidate_input["source_catalog"] = catalog
        if "failure_record" in input_projection:
            candidate_input["revision"] = {
                key: deepcopy(input_projection[key])
                for key in ("candidate_output", "failure_record")
            }
        instruction = PROMPT_PATH.read_text(encoding="utf-8").strip()
        raw, result, attempts = self._invoke_candidate(
            requested_mode=requested_mode,
            prompt_ref=replace(
                prompt_ref,
                prompt_id="evaluation.source_demand_binding",
                prompt_version="v6",
                content_hash=hashlib.sha256(instruction.encode()).hexdigest(),
            ),
            prompt_input=candidate_input,
            schema=demand_schema([item["ref"] for item in catalog], _work_unit_ids(base)),
            instruction=instruction,
        )
        expanded = expand_demands(raw, catalog)
        self.events.append(
            {
                "operation": "SOURCE_DEMAND_BINDING",
                "input": candidate_input,
                "raw_output": raw,
                "materialized_output": expanded,
                "provider_attempts": attempts,
            }
        )
        return replace(result, structured_output=expanded)


class SourceNeedsThenBindingCandidate(SourceDemandBindingCandidate):
    @property
    def binding(self) -> dict[str, object]:
        root = PROMPT_PATH.parent.parent / "ru-source-demand-binding-v7"
        return {
            **super().binding,
            "candidate_id": "ru-source-needs-then-binding-v7",
            "needs_prompt_sha256": hashlib.sha256((root / "needs.md").read_bytes()).hexdigest(),
            "bind_prompt_sha256": hashlib.sha256((root / "bind.md").read_bytes()).hexdigest(),
        }

    def infer(
        self, requested_mode: Any, prompt_ref: Any, input_projection: Any, output_schema_ref: Any
    ) -> Any:
        if prompt_ref.prompt_id != "request_understanding.identify_source_dependencies":
            return super().infer(requested_mode, prompt_ref, input_projection, output_schema_ref)
        base = input_projection.get("base_projection", input_projection)
        root = PROMPT_PATH.parent.parent / "ru-source-demand-binding-v7"
        common = {
            key: deepcopy(base[key])
            for key in (
                "user_request",
                "selected_resource_refs",
                "requested_work",
                "confirmation_response",
                "request_reconsideration",
            )
            if key in base
        }
        instruction = (root / "needs.md").read_text(encoding="utf-8").strip()
        schema = needs_schema(_work_unit_ids(base))
        needs, first, attempts = self._invoke_candidate(
            requested_mode=requested_mode,
            prompt_ref=replace(
                prompt_ref,
                prompt_id="evaluation.identify_information_needs",
                prompt_version="v7",
                content_hash=hashlib.sha256(instruction.encode()).hexdigest(),
            ),
            prompt_input=common,
            schema=schema,
            instruction=instruction,
        )
        identified = [
            {"demand_id": f"d{i + 1:02}", **item}
            for i, item in enumerate(needs["information_needs"])
        ]
        self.events.append(
            {
                "operation": "INFORMATION_NEEDS",
                "input": common,
                "raw_output": needs,
                "provider_attempts": attempts,
            }
        )
        catalog = source_catalog(base["source_candidates"])
        if not identified:
            return replace(first, structured_output=expand_demands({"source_demands": []}, catalog))
        instruction = (root / "bind.md").read_text(encoding="utf-8").strip()
        raw, second, attempts = self._invoke_candidate(
            requested_mode=requested_mode,
            prompt_ref=replace(
                prompt_ref,
                prompt_id="evaluation.bind_information_sources",
                prompt_version="v7",
                content_hash=hashlib.sha256(instruction.encode()).hexdigest(),
            ),
            prompt_input={"information_needs": identified, "source_catalog": catalog},
            schema=binding_schema(
                [item["demand_id"] for item in identified], [item["ref"] for item in catalog]
            ),
            instruction=instruction,
        )
        expanded = bind_needs(identified, raw, catalog)
        self.events.append(
            {
                "operation": "BIND_INFORMATION_SOURCES",
                "raw_output": raw,
                "materialized_output": expanded,
                "provider_attempts": attempts,
            }
        )
        return replace(
            second,
            structured_output=expanded,
            input_tokens=first.input_tokens + second.input_tokens,
            output_tokens=first.output_tokens + second.output_tokens,
            latency_ms=first.latency_ms + second.latency_ms,
        )


def needs_schema(work_ids: Sequence[str]) -> OutputSchemaDefinition:
    item = deepcopy(
        demand_schema(["unused"], work_ids).json_schema["properties"]["source_demands"]["items"]
    )
    item["required"].remove("source_ref")
    del item["properties"]["source_ref"]
    item["required"].insert(0, "target_description")
    item["properties"] = {
        "target_description": {"type": "string", "minLength": 1},
        **item["properties"],
    }
    return OutputSchemaDefinition(
        schema_version="evaluation-information-needs-v7",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["information_needs"],
            "properties": {"information_needs": {"type": "array", "maxItems": 12, "items": item}},
        },
    )


def binding_schema(demand_ids: Sequence[str], refs: Sequence[str]) -> OutputSchemaDefinition:
    return OutputSchemaDefinition(
        schema_version="evaluation-source-ref-binding-v7",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["bindings"],
            "properties": {
                "bindings": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(demand_ids),
                    "properties": {key: {"enum": [*refs, None]} for key in demand_ids},
                }
            },
        },
    )


def bind_needs(
    needs: Sequence[Mapping[str, Any]], raw: Mapping[str, Any], catalog: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    for item in needs:
        ref = raw["bindings"][item["demand_id"]]
        if ref is None:
            raise ValueError("information need has no available source binding")
        if ref not in groups:
            groups[ref] = {
                "source_ref": ref,
                "target_scope": item["target_scope"],
                "information_needed": [],
                "work_unit_ids": [],
            }
        target = groups[ref]
        if target["target_scope"] != item["target_scope"]:
            raise ValueError("existing source contract cannot merge different target scopes")
        for field in ("information_needed", "work_unit_ids"):
            source = "information_needed" if field == "information_needed" else "work_unit_ids"
            for value in item[source]:
                if value not in target[field]:
                    target[field].append(value)
    return expand_demands({"source_demands": list(groups.values())}, catalog)


class JointRoleAuthorityCandidate(GoalOutputModalityAuthorityCandidate):
    """V4 modality guard plus Source/Output roles in one interpretation; no prohibitions fusion."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._goal_output_instruction = (
            (PROMPT_PATH.parent.parent / "ru-joint-roles-v8" / "interpret.md")
            .read_text(encoding="utf-8")
            .strip()
        )

    @property
    def binding(self) -> dict[str, object]:
        return {
            **super().binding,
            "candidate_id": "ru-joint-roles-v8",
            "goal_output_schema_version": "evaluation-joint-roles-v8",
            "source_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "goal_source_output_sha256": hashlib.sha256(
                self._goal_output_instruction.encode()
            ).hexdigest(),
        }

    @property
    def _goal_output_prompt_version(self) -> str:
        return "joint-roles-v8"

    def _build_goal_output_schema(self, *, work_unit_ids: Any, output_candidates: Any) -> Any:
        schema = super()._build_goal_output_schema(
            work_unit_ids=work_unit_ids, output_candidates=output_candidates
        )
        value = deepcopy(schema.json_schema)
        catalog = source_catalog(self._source_candidates)
        value["properties"]["source_demands"] = demand_schema(
            [item["ref"] for item in catalog], work_unit_ids
        ).json_schema["properties"]["source_demands"]
        value["required"].append("source_demands")
        return replace(schema, schema_version="evaluation-joint-roles-v8", json_schema=value)

    def _infer_goal_output_authority(self, **kwargs: Any) -> Any:
        kwargs["input_projection"] = {
            **kwargs["input_projection"],
            "source_catalog": source_catalog(self._source_candidates),
        }
        return super()._infer_goal_output_authority(**kwargs)

    def infer(
        self, requested_mode: Any, prompt_ref: Any, input_projection: Any, output_schema_ref: Any
    ) -> Any:
        if (
            prompt_ref.prompt_id == "request_understanding.identify_source_dependencies"
            and self._goal_output is not None
        ):
            from evaluation.request_semantic_authority_candidate import _cached_result

            self.cached_response_count += 1
            return _cached_result(
                model_id=self._model_id,
                structured_output=expand_demands(
                    self._goal_output, source_catalog(self._source_candidates)
                ),
            )
        return super().infer(requested_mode, prompt_ref, input_projection, output_schema_ref)


def keyed_source_schema(
    resource_types: Sequence[str], work_ids: Sequence[str]
) -> OutputSchemaDefinition:
    common = deepcopy(
        demand_schema(["unused"], work_ids).json_schema["properties"]["source_demands"]["items"]
    )
    common["required"].remove("source_ref")
    del common["properties"]["source_ref"]
    return OutputSchemaDefinition(
        schema_version="evaluation-keyed-source-v9",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["source_reads"],
            "properties": {
                "source_reads": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {key: deepcopy(common) for key in resource_types},
                }
            },
        },
    )


class KeyedSourceCandidate(GoalOutputModalityAuthorityCandidate):
    @property
    def binding(self) -> dict[str, object]:
        path = PROMPT_PATH.parent.parent / "ru-keyed-source-v9" / "source.md"
        return {
            **super().binding,
            "candidate_id": "ru-keyed-source-v9",
            "source_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_prompt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def infer(
        self, requested_mode: Any, prompt_ref: Any, input_projection: Any, output_schema_ref: Any
    ) -> Any:
        if prompt_ref.prompt_id != "request_understanding.identify_source_dependencies":
            return super().infer(requested_mode, prompt_ref, input_projection, output_schema_ref)
        base = input_projection.get("base_projection", input_projection)
        catalog = source_catalog(base["source_candidates"])
        instruction = (
            (PROMPT_PATH.parent.parent / "ru-keyed-source-v9" / "source.md")
            .read_text(encoding="utf-8")
            .strip()
        )
        raw, result, attempts = self._invoke_candidate(
            requested_mode=requested_mode,
            prompt_ref=replace(
                prompt_ref,
                prompt_id="evaluation.keyed_source",
                prompt_version="v9",
                content_hash=hashlib.sha256(instruction.encode()).hexdigest(),
            ),
            prompt_input=input_projection,
            schema=keyed_source_schema(
                [item["resource_type"] for item in catalog], _work_unit_ids(base)
            ),
            instruction=instruction,
        )
        by_resource = {item["resource_type"]: item["ref"] for item in catalog}
        expanded = expand_demands(
            {
                "source_demands": [
                    {**value, "source_ref": by_resource[key]}
                    for key, value in raw["source_reads"].items()
                ]
            },
            catalog,
        )
        self.events.append(
            {
                "operation": "KEYED_SOURCE",
                "raw_output": raw,
                "materialized_output": expanded,
                "provider_attempts": attempts,
            }
        )
        return replace(result, structured_output=expanded)
