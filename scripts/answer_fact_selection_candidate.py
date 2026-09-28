"""Inactive fact-selection output for the frozen 067/068 single-Task lookup inputs.

This is not a general ANSWER classifier or a Product formatter extension. The
evaluation caller fixes the lookup-only population and supplies snapshots from
the same recorded Run. A bare mapping cannot establish that Run authority.
Catalog values stay local to the renderer; only closed Evidence/field pairs
belong in the model's output schema. No new Evidence or semantic artifact is
created, and an empty selection is not a claim that a search found nothing.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.planning.compose_answer import (
    MAX_USER_VISIBLE_ANSWER_CHARS,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
)
from google_work_agent.application.agents.planning.project_task_read_answer import (
    _scheduled_date,
    _task_status,
)
from google_work_agent.application.agents.retrieval.resolve_task_calendar_snapshot import (
    resolve_unique_task_calendar_snapshots,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

_FIELDS = ("title", "status", "due", "notes")


def _ref(item: Mapping[str, object]) -> str | None:
    value = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
    return value if isinstance(value, str) and value else None


def _literal(value: str) -> str:
    """Escape visible source data, not instructions or executable Markdown."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>~=])", r"\\\1", html.escape(value, quote=False))


def build_fact_catalog(
    prompt_input: Mapping[str, object],
    *,
    source_snapshots: Mapping[str, Mapping[str, object]] | None,
) -> list[dict[str, str]]:
    """Return renderer-local facts from one approved, exact-version Task only.

    Missing, stale, conflicting or foreign snapshots exclude the whole Resource.
    An unknown status or invalid date excludes that field without inventing a
    value. Empty text remains distinct from absent/null text. The result must not
    be copied wholesale into a model input: ``rendered_value`` is renderer-only.
    """
    outline, evidence = prompt_input.get("answer_outline"), prompt_input.get("evidence")
    refs = outline.get("evidence_refs") if isinstance(outline, Mapping) else None
    if (
        not isinstance(refs, list)
        or not refs
        or not all(isinstance(ref, str) and ref for ref in refs)
        or not isinstance(evidence, Sequence)
        or isinstance(evidence, (str, bytes))
    ):
        return []
    approved = [item for item in evidence if isinstance(item, Mapping) and _ref(item) in refs]
    if {_ref(item) for item in approved} != set(refs):
        return []
    observations = resolve_unique_task_calendar_snapshots(approved, source_snapshots)
    if observations is None or len(observations) != 1:
        return []
    handle, fields = observations[0]
    if not handle.startswith("task:"):
        return []
    request = prompt_input.get("user_request")
    korean = isinstance(request, str) and any("\uac00" <= char <= "\ud7a3" for char in request)
    rendered: dict[str, str] = {}
    for field in _FIELDS:
        value = fields.get(field)
        if field == "status":
            value = _task_status(value, korean=korean)
        elif field == "due":
            value = _scheduled_date(value)
        elif isinstance(value, str):
            value = _literal(value)
        if isinstance(value, str):
            rendered[field] = value
    facts: list[dict[str, str]] = []
    seen_refs: set[str] = set()
    for item in approved:
        ref = cast(str, _ref(item))
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        locator = cast(Mapping[str, object], item["locator"])
        version = cast(str, locator["source_version_ref"])
        for field, value in rendered.items():
            facts.append(
                {
                    "evidence_ref": ref,
                    "resource_handle": handle,
                    "source_version_ref": version,
                    "field": field,
                    "rendered_value": value,
                }
            )
    return facts


def _selection_schema(facts: list[dict[str, str]]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "minItems": 0,
                "maxItems": len(facts),
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["evidence_ref", "field"],
                    "properties": {
                        "evidence_ref": {"type": "string"},
                        "field": {"type": "string"},
                    },
                    "enum": [
                        {"evidence_ref": fact["evidence_ref"], "field": fact["field"]}
                        for fact in facts
                    ],
                },
            },
        },
    }


def bind_fact_selection_schema(
    prompt_input: Mapping[str, object],
    *,
    source_snapshots: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, object] | None:
    """Expose only valid ref/field choices; no source values or hidden metadata."""
    facts = build_fact_catalog(prompt_input, source_snapshots=source_snapshots)
    return _selection_schema(facts) if facts else None


def materialize_fact_selection(
    value: object,
    *,
    prompt_input: Mapping[str, object],
    source_snapshots: Mapping[str, Mapping[str, object]] | None,
) -> AnswerDraftCandidateV2 | None:
    """Validate closed choices afresh and render selected facts without prose repair."""
    facts = build_fact_catalog(prompt_input, source_snapshots=source_snapshots)
    errors = validate_output_schema(value, _selection_schema(facts))
    if errors:
        raise ValueError("invalid fact selection: " + "; ".join(errors))
    items = cast(dict[str, list[dict[str, str]]], value)["items"]
    if not items:
        return None
    by_pair = {(fact["evidence_ref"], fact["field"]): fact for fact in facts}
    request = prompt_input.get("user_request")
    korean = isinstance(request, str) and any("\uac00" <= char <= "\ud7a3" for char in request)
    labels = (
        {"title": "제목", "status": "상태", "due": "예정일", "notes": "메모(원문)"}
        if korean
        else {
            "title": "Title",
            "status": "Status",
            "due": "Scheduled date",
            "notes": "Notes (verbatim)",
        }
    )
    sections: list[str] = []
    refs: list[str] = []
    for item in items:
        ref, field = item["evidence_ref"], item["field"]
        rendered = by_pair[ref, field]["rendered_value"]
        if field in {"title", "notes"}:
            quoted = "\n".join(f"> {line}" for line in rendered.split("\n"))
            sections.append(f"{labels[field]}:\n{quoted}")
        else:
            sections.append(f"{labels[field]}: {rendered}")
        if ref not in refs:
            refs.append(ref)
    answer = "\n\n".join(sections)
    if len(answer) > MAX_USER_VISIBLE_ANSWER_CHARS:
        raise ValueError("fact selection exceeds the existing answer length limit")
    return {"schema_version": 2, "answer": answer, "evidence_refs": refs}


__all__ = ["build_fact_catalog", "bind_fact_selection_schema", "materialize_fact_selection"]
