"""Inactive v25: equivalent Source-scope schema language with explicit variants.

This is a decoder/repair-schema representation experiment, not another semantic
policy. The v24 Prompt, input, normalization, exact provenance, and handoff remain
unchanged. Ordinary and scope constraints retain their existing output shapes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from scripts.ru_observation import object_hash
from scripts.ru_source_scope_candidate import SOURCE_CATEGORIES, SOURCE_SCOPE_FIELDS
from scripts.ru_source_scope_handoff_candidate import (
    SourceScopeHandoff,
    SourceScopeHandoffCandidate,
    source_scope_handoff_candidate,
)

from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

SCHEMA_VERSION = "evaluation-source-scope-discriminated-v25"


def discriminate_scope_items(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Rewrite only the understood v24 conditional; preserve its valid language.

    Called after the existing builders finish assigning closed WorkUnit IDs.
    Unknown conditional changes fail instead of being silently discarded.
    """
    result = deepcopy(dict(schema))
    additional = result["properties"]["constraints"]["properties"]["additional_constraints"]
    item = additional["items"]
    fields = item["properties"]["field"]["enum"]
    scope_value: dict[str, Any] = {
        "oneOf": [
            {"enum": list(SOURCE_CATEGORIES)},
            {
                "type": "array",
                "minItems": 1,
                "items": {"enum": list(SOURCE_CATEGORIES)},
            },
        ]
    }
    unique_scope_value = deepcopy(scope_value)
    unique_scope_value["oneOf"][1]["uniqueItems"] = True
    expected_conditions = [
        {
            "if": {
                "properties": {"field": {"enum": list(SOURCE_SCOPE_FIELDS)}},
                "required": ["field"],
            },
            "then": {"properties": {"value": scope_value}},
        },
        {
            "if": {"properties": {"field": {"enum": list(SOURCE_SCOPE_FIELDS)}}},
            "then": {
                "required": ["provenance"],
                "properties": {"value": unique_scope_value},
            },
            "else": {"properties": {"provenance": {"enum": []}}},
        },
    ]
    if (
        item.get("allOf") != expected_conditions
        or set(item) != {"type", "required", "additionalProperties", "properties", "allOf"}
        or item["type"] != "object"
        or item["additionalProperties"] is not False
        or item["required"] != ["field", "value", "work_unit_ids"]
        or set(item["properties"]) != {"field", "value", "work_unit_ids", "provenance"}
        or not set(SOURCE_SCOPE_FIELDS) < set(fields)
    ):
        raise ValueError("v25 requires the unchanged v24 conditional Source-scope item contract")

    ordinary = {key: deepcopy(value) for key, value in item.items() if key != "allOf"}
    ordinary["properties"].pop("provenance")
    ordinary["properties"]["field"]["enum"] = [
        name for name in fields if name not in SOURCE_SCOPE_FIELDS
    ]
    variants = [ordinary]
    for scope_field in SOURCE_SCOPE_FIELDS:
        scoped = {key: deepcopy(value) for key, value in item.items() if key != "allOf"}
        scoped["required"] = [*item["required"], "provenance"]
        scoped["properties"]["field"] = {
            key: deepcopy(value)
            for key, value in item["properties"]["field"].items()
            if key != "enum"
        }
        scoped["properties"]["field"]["const"] = scope_field
        scoped["properties"]["value"] = deepcopy(unique_scope_value)
        variants.append(scoped)
    additional["items"] = {"oneOf": variants}
    return result


@contextmanager
def source_scope_discriminated_candidate(**kwargs: Any) -> Iterator[SourceScopeHandoff]:
    """Reuse v24's complete validation/handoff context; no global schema rewrite."""
    with source_scope_handoff_candidate(**kwargs) as session:
        yield session


class SourceScopeDiscriminatedCandidate(SourceScopeHandoffCandidate):
    """Build normal closed-ID v24 schema first, then change only its representation."""

    @property
    def binding(self) -> dict[str, object]:
        parent = super().binding
        representation = {
            "parent_goal_declared_contract_sha256": parent["goal_declared_contract_sha256"],
            "schema_version": SCHEMA_VERSION,
            "changed_path": "$.properties.constraints.properties.additional_constraints.items",
            "representation": "oneOf ordinary / required_sources / forbidden_sources",
            "valid_output_language": "unchanged v24",
        }
        return {
            **parent,
            "candidate_id": "ru-source-scope-discriminated-v25",
            "source_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "goal_output_schema_version": SCHEMA_VERSION,
            "goal_declared_contract_sha256": object_hash(representation),
            "schema_representation": representation,
        }

    def _build_goal_output_schema(self, **kwargs: Any) -> OutputSchemaDefinition:
        base = cast(OutputSchemaDefinition, super()._build_goal_output_schema(**kwargs))
        return replace(
            base,
            schema_version=SCHEMA_VERSION,
            json_schema=discriminate_scope_items(cast(Mapping[str, Any], base.json_schema)),
        )
