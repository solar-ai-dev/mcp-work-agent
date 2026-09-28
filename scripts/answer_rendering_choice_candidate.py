"""Inactive compose output choice; no automatic eligibility or semantic repair.

The caller owns same-Run snapshot authorization and the existing Product answer
validator. This helper only closes the response shape and renders selected
facts or unwraps prose. A valid shape is not a correct answer to the request.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import cast

from scripts.answer_fact_selection_candidate import (
    bind_fact_selection_schema,
    materialize_fact_selection,
)

from google_work_agent.application.agents.planning.compose_answer import (
    answer_draft_output_schema,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def _with_mode(schema: Mapping[str, object], mode: str) -> dict[str, object]:
    branch = deepcopy(dict(schema))
    cast(dict[str, object], branch["properties"])["mode"] = {"const": mode}
    branch["required"] = ["mode", *cast(list[str], branch["required"])]
    return branch


def bind_answer_rendering_choice_schema(
    prompt_input: Mapping[str, object],
    *,
    source_snapshots: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, object]:
    """Always allow existing prose; expose refs only when the 081 catalog exists."""
    outline = prompt_input.get("answer_outline")
    refs = outline.get("evidence_refs") if isinstance(outline, Mapping) else None
    if not isinstance(refs, list) or not all(isinstance(ref, str) and ref for ref in refs):
        raise ValueError("answer_outline.evidence_refs must be a string list")
    prose = _with_mode(answer_draft_output_schema(refs).json_schema, "PROSE")
    facts = bind_fact_selection_schema(prompt_input, source_snapshots=source_snapshots)
    if facts is None:
        return prose
    return {"oneOf": [_with_mode(facts, "FACT_REFERENCES"), prose]}


def materialize_answer_rendering_choice(
    value: object,
    *,
    prompt_input: Mapping[str, object],
    source_snapshots: Mapping[str, Mapping[str, object]] | None,
) -> AnswerDraftCandidateV2 | None:
    """Preserve branch choice; no retry, field completion or automatic fallback."""
    schema = bind_answer_rendering_choice_schema(prompt_input, source_snapshots=source_snapshots)
    errors = validate_output_schema(value, schema)
    if errors:
        raise ValueError("invalid answer rendering choice: " + "; ".join(errors))
    response = deepcopy(cast(dict[str, object], value))
    mode = response.pop("mode")
    if mode == "FACT_REFERENCES":
        return materialize_fact_selection(
            response, prompt_input=prompt_input, source_snapshots=source_snapshots
        )
    return cast(AnswerDraftCandidateV2, response)


__all__ = [
    "bind_answer_rendering_choice_schema",
    "materialize_answer_rendering_choice",
]
