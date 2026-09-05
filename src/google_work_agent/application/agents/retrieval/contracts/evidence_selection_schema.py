"""Current-run output schema and resource coverage for evidence selection."""

from collections.abc import Collection, Mapping

from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

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
    max_evidence: int,
) -> OutputSchemaDefinition:
    """Require one assessment per visible candidate, without parallel ID lists.

    This is an inference-only V3 boundary. The application projects it to the
    existing EvidenceSelectionResultV2 consumed by checkpoints and materialization.
    """
    ids = sorted(candidate_resource_refs)
    if len(ids) > max_evidence:
        raise ValueError("visible evidence candidates exceed the evidence budget")
    assessment = {
        "type": "object",
        "required": ["relevance_reason", "role"],
        "additionalProperties": False,
        "properties": {
            "relevance_reason": {"type": "string", "minLength": 1},
            "role": {"type": "string", "enum": [
                "SUPPORTS", "CONTRADICTS", "CONTEXT", "EXCLUDED",
            ]},
        },
    }
    return OutputSchemaDefinition(
        schema_version="evidence-selection-v3",
        json_schema={
            "type": "object",
            "required": ["schema_version", "segment_assessments"],
            "additionalProperties": False,
            "properties": {
                "schema_version": {"type": "integer", "enum": [3]},
                "segment_assessments": {
                    "type": "object", "required": ids, "additionalProperties": False,
                    "properties": {segment_id: assessment for segment_id in ids},
                },
            },
        },
    )
