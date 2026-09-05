"""Current-run output schema and resource coverage for evidence selection."""

from collections.abc import Collection, Mapping
from copy import deepcopy
from typing import cast

from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

EVIDENCE_SELECTION_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="evidence-selection-v2",
    json_schema={
        "type": "object",
        "required": [
            "schema_version",
            "evidence_drafts",
            "selected_segment_ids",
            "excluded_segment_ids",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [2]},
            "evidence_drafts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["segment_id", "role", "relevance_reason"],
                    "additionalProperties": False,
                    "properties": {
                        "segment_id": {"type": "string"},
                        "role": {
                            "type": "string",
                            "enum": ["SUPPORTS", "CONTRADICTS", "CONTEXT"],
                        },
                        "relevance_reason": {"type": "string"},
                    },
                },
            },
            "selected_segment_ids": {"type": "array", "items": {"type": "string"}},
            "excluded_segment_ids": {"type": "array", "items": {"type": "string"}},
        },
    },
)


_RESOURCE_HINT_PREFIXES: dict[str, tuple[str, ...]] = {
    "GMAIL_THREAD": ("gmail_thread:",),
    "GMAIL_MESSAGE": ("gmail_message:",),
    "GMAIL_DRAFT": ("gmail_draft:",),
    "GMAIL_ATTACHMENT": ("gmail_attachment:",),
    "TASK_LIST": ("task_list:",),
    "TASK": ("task:",),
    "CALENDAR": ("calendar:",),
    "CALENDAR_EVENT": ("calendar_event:",),
    "CALENDAR_FREEBUSY": ("calendar_freebusy:",),
}



def required_resource_segments(
    candidate_resource_refs: Mapping[str, str], requested_resource_hints: Collection[str],
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for hint in requested_resource_hints:
        prefixes = _RESOURCE_HINT_PREFIXES.get(hint, ())
        matches = sorted(key for key, ref in candidate_resource_refs.items()
                         if prefixes and ref.startswith(prefixes))
        if matches:
            groups[hint] = matches
    return groups


def bind_evidence_selection_schema(
    *, candidate_resource_refs: Mapping[str, str],
    requested_resource_hints: Collection[str], max_evidence: int,
) -> OutputSchemaDefinition:
    schema = deepcopy(dict(EVIDENCE_SELECTION_OUTPUT_SCHEMA.json_schema))
    properties = cast(dict[str, dict[str, object]], schema["properties"])
    ids = sorted(candidate_resource_refs)
    id_schema = {"type": "string", "enum": ids}
    for name in ("selected_segment_ids", "excluded_segment_ids"):
        properties[name].update(items=id_schema, uniqueItems=True, maxItems=len(ids))
    properties["selected_segment_ids"]["maxItems"] = min(len(ids), max_evidence)
    drafts = properties["evidence_drafts"]
    drafts["maxItems"] = max_evidence
    item_properties = cast(
        dict[str, object], cast(dict[str, object], drafts["items"])["properties"]
    )
    item_properties["segment_id"] = id_schema
    groups = required_resource_segments(candidate_resource_refs, requested_resource_hints)
    consistency_rules: list[dict[str, object]] = [
        {
            "if": {"properties": {
                "selected_segment_ids": {"contains": {"const": segment_id}},
            }},
            "then": {"properties": {
                "evidence_drafts": {
                    "contains": {"properties": {"segment_id": {"const": segment_id}}},
                    "minContains": 1,
                    "maxContains": 1,
                },
                "excluded_segment_ids": {
                    "contains": {"const": segment_id}, "minContains": 0, "maxContains": 0,
                },
            }},
            "else": {"properties": {
                "evidence_drafts": {
                    "contains": {"properties": {"segment_id": {"const": segment_id}}},
                    "minContains": 0, "maxContains": 0,
                },
            }},
        }
        for segment_id in ids
    ]
    if groups:
        # Candidates are not facts: explicitly excluding every candidate of a
        # source is valid. Silently ignoring that source is not.
        consistency_rules.extend([
            {
                "if": {"properties": {
                    "selected_segment_ids": {"contains": {"enum": segment_ids}},
                }},
                "else": {"properties": {
                    "excluded_segment_ids": {"allOf": [
                        {"contains": {"const": segment_id}} for segment_id in segment_ids
                    ]},
                }},
            }
            for segment_ids in groups.values()
        ])
    if consistency_rules:
        schema["allOf"] = consistency_rules
    return OutputSchemaDefinition(
        schema_version=EVIDENCE_SELECTION_OUTPUT_SCHEMA.schema_version, json_schema=schema,
    )
