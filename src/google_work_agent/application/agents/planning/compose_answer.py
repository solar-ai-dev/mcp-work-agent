"""Compose the user-facing answer through the canonical Planning Prompt slot."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
    AnswerOutlineV1,
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.normalize_generated_answer_prose import (
    normalize_generated_answer_prose,
)
from google_work_agent.application.agents.planning.project_retrieval_collections import (
    project_retrieval_collections,
)
from google_work_agent.application.agents.planning.project_task_read_answer import (
    project_task_read_answer,
)
from google_work_agent.application.agents.planning.sanitize_user_visible_answer import (
    sanitize_user_visible_answer,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    validate_temporal_range_constraint,
)
from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

PROMPT_ID = "planning.compose_answer"
MAX_USER_VISIBLE_ANSWER_CHARS = 2_400


class _ComposeAnswerValidationError(ValueError):
    """Preserve existing failure control flow while exposing a safe validation boundary."""

    def __init__(self, message: str, *, reason_code: str, field_path: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.affected_field_paths = (field_path,)

ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="planning-answer-draft-v2",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "answer", "evidence_refs"],
        "properties": {
            "schema_version": {"const": 2},
            "answer": {
                "type": "string",
                "description": (
                    "Final user-visible prose only. Do not include JSON, XML, objects, arrays, "
                    "serialized schemas, or code blocks in this string."
                ),
                "minLength": 1,
                "maxLength": MAX_USER_VISIBLE_ANSWER_CHARS,
            },
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
)

ANSWER_SEMANTIC_REPAIR_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="planning-answer-semantic-repair-v1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "sections", "evidence_refs"],
        "properties": {
            "schema_version": {"const": 1},
            "sections": {
                "type": "array",
                "description": (
                    "Semantic sections for deterministic rendering. Do not return an answer "
                    "field or a serialized response."
                ),
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["heading", "items"],
                    "properties": {
                        "heading": {
                            "type": "string",
                            "description": (
                                "Optional short plain-text section heading; use an empty string "
                                "when no heading is needed. Do not serialize JSON, XML, a schema, "
                                "or a code block."
                            ),
                            "maxLength": 160,
                        },
                        "items": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 12,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["label", "value"],
                                "properties": {
                                    "label": {
                                        "type": "string",
                                        "description": (
                                            "Optional concise plain-text semantic label; use an "
                                            "empty string when no label is needed. Do not "
                                            "serialize JSON, XML, a schema, or a code block."
                                        ),
                                        "maxLength": 120,
                                    },
                                    "value": {
                                        "type": "string",
                                        "description": (
                                            "One atomic fact, request, conclusion, or summary "
                                            "content item. Do not serialize JSON, XML, a schema, "
                                            "or a code block."
                                        ),
                                        "minLength": 1,
                                        "maxLength": 1_200,
                                    },
                                },
                            },
                        },
                    },
                },
            },
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
)


def answer_draft_output_schema(allowed_evidence_refs: Sequence[str]) -> OutputSchemaDefinition:
    """Bind answer citations to the evidence approved by the current outline."""

    json_schema = deepcopy(ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA.json_schema)
    properties = cast(dict[str, object], json_schema["properties"])
    properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "maxItems": len(set(allowed_evidence_refs)),
        "items": {"type": "string", "enum": sorted(set(allowed_evidence_refs))},
    }
    return OutputSchemaDefinition(
        schema_version=ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA.schema_version,
        json_schema=json_schema,
    )


def answer_semantic_repair_output_schema(
    allowed_evidence_refs: Sequence[str],
) -> OutputSchemaDefinition:
    """Bind structured-repair citations to the current answer outline."""

    json_schema = deepcopy(ANSWER_SEMANTIC_REPAIR_OUTPUT_SCHEMA.json_schema)
    properties = cast(dict[str, object], json_schema["properties"])
    properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "maxItems": len(set(allowed_evidence_refs)),
        "items": {"type": "string", "enum": sorted(set(allowed_evidence_refs))},
    }
    return OutputSchemaDefinition(
        schema_version=ANSWER_SEMANTIC_REPAIR_OUTPUT_SCHEMA.schema_version,
        json_schema=json_schema,
    )


def compose_answer(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    answer_outline: AnswerOutlineV1,
    work_analysis: Mapping[str, object] | None,
    evidence: Sequence[Mapping[str, object]],
    invoke: PlanningSemanticInvoker,
    confirmation_response: Mapping[str, object] | None = None,
    retrieval_result: Mapping[str, object] | None = None,
) -> AnswerDraftCandidateV2:
    if not user_request.strip():
        raise ValueError("user_request is required")
    selected_people = cast(
        dict[str, str], (retrieval_result or {}).get("selected_person_identities", {})
    )
    if selected_people:
        candidates = cast(
            list[dict[str, object]], (retrieval_result or {}).get("person_candidates", [])
        )
        accepted: set[str] = set()
        rejected: set[str] = set()
        for person in candidates:
            chosen = selected_people.get(str(person["mention"]))
            if chosen is None:
                continue
            target = accepted if chosen == person["identity"] else rejected
            target.update(cast(list[str], person["source_segment_ids"]))
        evidence = [item for item in evidence if item.get("segment_id") not in rejected - accepted]
        visible_refs = {_evidence_ref(item) for item in evidence}
        answer_outline = {
            **answer_outline,
            "evidence_refs": [
                ref for ref in answer_outline["evidence_refs"] if ref in visible_refs
            ],
        }
    approved_refs = set(answer_outline["evidence_refs"])
    approved_evidence = [dict(item) for item in evidence if _evidence_ref(item) in approved_refs]
    prompt_input: dict[str, object] = {
        "user_request": user_request,
        "request_intent": {
            key: value for key, value in request_intent.items() if key != "repository_default"
        },
        "answer_outline": dict(answer_outline),
        "evidence": approved_evidence,
        "temporal_constraints": [
            validate_temporal_range_constraint(item)
            for item in cast(
                list[Mapping[str, object]], (retrieval_result or {}).get("temporal_constraints", [])
            )
        ],
    }
    if selected_people:
        prompt_input["selected_person_identities"] = selected_people
    if retrieval_result is not None:
        for key in ("coverage", "unresolved_event_dates", "missing_information", "source_statuses"):
            if key in retrieval_result:
                prompt_input[key] = deepcopy(retrieval_result[key])
        if "collection_results" in retrieval_result:
            prompt_input["collection_results"] = project_retrieval_collections(retrieval_result)
    if work_analysis is not None:
        prompt_input["work_analysis"] = dict(work_analysis)
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    task_projection = project_task_read_answer(
        user_request=user_request,
        request_intent=request_intent,
        evidence=evidence,
    )
    if task_projection is not None:
        if not set(task_projection.draft["evidence_refs"]).issubset(approved_refs):
            raise _ComposeAnswerValidationError(
                "task read answer references evidence outside its approved outline",
                reason_code="COMPOSE_ANSWER_EVIDENCE_SCOPE_INVALID",
                field_path="$.evidence_refs",
            )
        return _with_partial_scope(task_projection.draft, retrieval_result)
    candidate = invoke(PROMPT_ID, prompt_input)
    try:
        return _validate_answer_candidate(
            candidate,
            prompt_input=prompt_input,
            answer_outline=answer_outline,
            approved_evidence=approved_evidence,
            user_request=user_request,
            retrieval_result=retrieval_result,
        )
    except _ComposeAnswerValidationError as error:
        if error.reason_code != "COMPOSE_ANSWER_PROSE_INVALID":
            raise
        repair_candidate = invoke(
            PROMPT_ID,
            {
                "base_projection": prompt_input,
                "candidate_output": None,
                "failure_record": build_failure_record_v1(
                    failure_reason_code=error.reason_code,
                    failure_origin="LLM_OUTPUT",
                    detected_by="RUNTIME_DOMAIN_VALIDATOR",
                    runtime_disposition="RETRYABLE",
                    experiment_disposition="RUN_REVISION",
                    affected_field_paths=error.affected_field_paths,
                    evidence_refs=answer_outline["evidence_refs"],
                ),
            },
        )
        rendered_candidate = _render_semantic_repair_candidate(repair_candidate)
        return _validate_answer_candidate(
            rendered_candidate,
            prompt_input=prompt_input,
            answer_outline=answer_outline,
            approved_evidence=approved_evidence,
            user_request=user_request,
            retrieval_result=retrieval_result,
        )


def _render_semantic_repair_candidate(
    candidate: Mapping[str, object],
) -> AnswerDraftCandidateV2:
    if candidate.get("schema_version") != 1:
        raise _invalid_semantic_repair()
    sections = candidate.get("sections")
    refs = candidate.get("evidence_refs")
    if not isinstance(sections, list) or not sections:
        raise _invalid_semantic_repair()
    rendered_sections: list[str] = []
    for section_index, section in enumerate(sections):
        if not isinstance(section, Mapping) or set(section) != {"heading", "items"}:
            raise _invalid_semantic_repair()
        heading = _semantic_repair_fragment(
            section.get("heading"),
            allow_empty=True,
            field_path=f"$.sections[{section_index}].heading",
        )
        items = section.get("items")
        if not isinstance(items, list) or not items:
            raise _invalid_semantic_repair()
        lines: list[str] = []
        for item_index, item in enumerate(items):
            if not isinstance(item, Mapping) or set(item) != {"label", "value"}:
                raise _invalid_semantic_repair()
            label = _semantic_repair_fragment(
                item.get("label"),
                allow_empty=True,
                field_path=f"$.sections[{section_index}].items[{item_index}].label",
            )
            value = _semantic_repair_fragment(
                item.get("value"),
                allow_empty=False,
                field_path=f"$.sections[{section_index}].items[{item_index}].value",
            )
            lines.append(f"- {label}: {value}" if label else f"- {value}")
        rendered_sections.append("\n".join([*([] if not heading else [f"## {heading}"]), *lines]))
    return {
        "schema_version": 2,
        "answer": "\n\n".join(rendered_sections),
        "evidence_refs": cast(list[str], refs),
    }


def _semantic_repair_fragment(
    value: object,
    *,
    allow_empty: bool,
    field_path: str,
) -> str:
    if not isinstance(value, str):
        raise _invalid_semantic_repair(field_path)
    stripped = value.strip()
    if not stripped:
        if allow_empty:
            return ""
        raise _invalid_semantic_repair(field_path)
    if (
        stripped.startswith(("{", "["))
        or "```" in stripped
        or (stripped.startswith("<") and stripped.endswith(">"))
    ):
        if allow_empty:
            return ""
        if stripped.startswith(("{", "[")):
            rendered = _render_serialized_semantic_value(stripped)
            if rendered:
                return rendered
        raise _invalid_semantic_repair(field_path)
    return stripped


def _render_serialized_semantic_value(value: str) -> str:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return ""

    def render(item: object, *, depth: int) -> list[str]:
        if depth > 3 or isinstance(item, bool) or item is None:
            return []
        if isinstance(item, str):
            text = item.strip()
            if not text or text.startswith(("{", "[", "<")) or "```" in text:
                return []
            return [text]
        if isinstance(item, (int, float)):
            return [str(item)]
        if isinstance(item, list):
            if not item or len(item) > 12:
                return []
            rendered: list[str] = []
            for child in item:
                parts = render(child, depth=depth + 1)
                if not parts:
                    return []
                rendered.extend(parts)
            return rendered
        if not isinstance(item, Mapping) or not item or len(item) > 12:
            return []
        if any(
            not isinstance(key, str)
            or key.strip().casefold() in {"internal", "schema_version", "evidence_refs", "answer"}
            for key in item
        ):
            return []
        rendered: list[str] = []
        for key, child in item.items():
            parts = render(child, depth=depth + 1)
            if not parts:
                return []
            label = key.strip()
            rendered.append(f"{label}: {'; '.join(parts)}")
        return rendered

    parts = render(parsed, depth=0)
    return "; ".join(parts)


def _invalid_semantic_repair(field_path: str = "$.sections") -> _ComposeAnswerValidationError:
    return _ComposeAnswerValidationError(
        "compose_answer answer must be user-visible prose",
        reason_code="COMPOSE_ANSWER_PROSE_INVALID",
        field_path=field_path,
    )


def _validate_answer_candidate(
    candidate: Mapping[str, object],
    *,
    prompt_input: Mapping[str, object],
    answer_outline: AnswerOutlineV1,
    approved_evidence: Sequence[Mapping[str, object]],
    user_request: str,
    retrieval_result: Mapping[str, object] | None,
) -> AnswerDraftCandidateV2:
    schema_version = candidate.get("schema_version")
    answer = candidate.get("answer")
    refs = candidate.get("evidence_refs")
    if schema_version != 2:
        raise _ComposeAnswerValidationError(
            "compose_answer output requires schema_version 2",
            reason_code="COMPOSE_ANSWER_SCHEMA_VERSION_INVALID",
            field_path="$.schema_version",
        )
    if not isinstance(answer, str) or not answer.strip():
        raise _ComposeAnswerValidationError(
            "compose_answer output requires answer",
            reason_code="COMPOSE_ANSWER_TEXT_MISSING",
            field_path="$.answer",
        )
    try:
        normalized_answer = normalize_generated_answer_prose(answer)
    except ValueError as error:
        raise _ComposeAnswerValidationError(
            str(error),
            reason_code="COMPOSE_ANSWER_PROSE_INVALID",
            field_path="$.answer",
        ) from error
    _validate_unresolved_date_claims(normalized_answer, retrieval_result)
    if any(
        item["axis"] == "MESSAGE_TIME"
        for item in cast(
            list[dict[str, object]],
            prompt_input["temporal_constraints"],
        )
    ):
        # The provider projection contains received_at, not a proved sent-at timestamp.
        normalized_answer = normalized_answer.replace("보낸 날짜:", "수신 시각:")
    if len(normalized_answer) > MAX_USER_VISIBLE_ANSWER_CHARS:
        raise _ComposeAnswerValidationError(
            "compose_answer output exceeds the user-visible answer limit",
            reason_code="COMPOSE_ANSWER_TEXT_LIMIT_EXCEEDED",
            field_path="$.answer",
        )
    if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
        raise _ComposeAnswerValidationError(
            "compose_answer output requires evidence_refs",
            reason_code="COMPOSE_ANSWER_EVIDENCE_REFS_INVALID",
            field_path="$.evidence_refs",
        )
    allowed = set(answer_outline["evidence_refs"])
    if not set(refs).issubset(allowed):
        raise _ComposeAnswerValidationError(
            "compose_answer referenced evidence outside its projection",
            reason_code="COMPOSE_ANSWER_EVIDENCE_SCOPE_INVALID",
            field_path="$.evidence_refs",
        )
    if len(refs) != len(set(refs)):
        raise _ComposeAnswerValidationError(
            "compose_answer output contains duplicate evidence_refs",
            reason_code="COMPOSE_ANSWER_EVIDENCE_REFS_DUPLICATED",
            field_path="$.evidence_refs",
        )
    visible_answer = sanitize_user_visible_answer(
        normalized_answer,
        internal_refs=[*allowed, *refs],
        user_request=user_request,
        source_texts=[
            excerpt
            for item in approved_evidence
            if isinstance((excerpt := item.get("excerpt")), str)
        ],
        internal_resource_ids=[
            handle.partition(":")[2]
            for item in approved_evidence
            if isinstance((handle := item.get("resource_handle")), str)
        ],
    )
    return _with_partial_scope(
        {"schema_version": 2, "answer": visible_answer, "evidence_refs": list(refs)},
        retrieval_result,
    )


def _with_partial_scope(
    draft: AnswerDraftCandidateV2,
    retrieval_result: Mapping[str, object] | None,
) -> AnswerDraftCandidateV2:
    if retrieval_result is None:
        return draft
    notices: list[str] = []
    if retrieval_result.get("unresolved_event_dates"):
        notices.append("행사 연도가 확정되지 않아 요청 기간에 해당하는지 추가 확인이 필요합니다.")
    if any(
        isinstance(item, Mapping) and item.get("code") == "person_identity"
        for item in cast(list[object], retrieval_result.get("missing_information", []))
    ):
        notices.append(
            "요청하신 인물의 신원이 확정되지 않았습니다. 이름이나 이메일 확인이 필요합니다."
        )
    if any(
        isinstance(item, Mapping) and item.get("failure_kind") is not None
        for item in cast(list[object], retrieval_result.get("source_statuses", []))
    ):
        notices.append("일부 자료를 읽지 못했습니다. 검색 결과가 없다는 뜻은 아닙니다.")
    if notices or retrieval_result.get("coverage") == "PARTIAL":
        notices.insert(0, "확인한 범위의 부분 결과입니다. 요청한 전체 범위를 확인한 것은 아닙니다.")
    answer = "\n\n".join([*notices, draft["answer"]])
    if len(answer) > MAX_USER_VISIBLE_ANSWER_CHARS:
        raise _ComposeAnswerValidationError(
            "compose_answer output exceeds the user-visible answer limit",
            reason_code="COMPOSE_ANSWER_TEXT_LIMIT_EXCEEDED",
            field_path="$.answer",
        )
    return {**draft, "answer": answer}


def _validate_unresolved_date_claims(
    answer: str,
    retrieval_result: Mapping[str, object] | None,
) -> None:
    """Reject explicit year/weekday promotion of a known yearless source date."""
    for item in cast(
        list[Mapping[str, object]],
        (retrieval_result or {}).get(
            "unresolved_event_dates",
            [],
        ),
    ):
        source = str(item.get("source_text", ""))
        date = re.search(r"(\d{1,2})\s*(?:월|[-/.])\s*(\d{1,2})", source)
        if date is None:
            continue
        month, day = (int(value) for value in date.groups())
        day_pattern = rf"0?{month}\s*(?:월|[-/.])\s*0?{day}(?!\d)(?:\s*일)?"
        explicit_year = rf"(?<!\d)\d{{4}}\s*(?:년|[-/.])\s*{day_pattern}"
        weekday = (
            rf"{day_pattern}(?:\s+\**\s*[월화수목금토일]요일"
            rf"|\s*\**\s*\([월화수목금토일]\))"
        )
        if re.search(explicit_year, answer) or re.search(weekday, answer):
            raise _ComposeAnswerValidationError(
                "compose_answer promoted an unresolved event date into a dated fact",
                reason_code="COMPOSE_ANSWER_UNRESOLVED_DATE_PROMOTED",
                field_path="$.answer",
            )


def _evidence_ref(item: Mapping[str, object]) -> str | None:
    value = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
    return value if isinstance(value, str) and value else None


__all__ = [
    "ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA",
    "ANSWER_SEMANTIC_REPAIR_OUTPUT_SCHEMA",
    "MAX_USER_VISIBLE_ANSWER_CHARS",
    "answer_draft_output_schema",
    "answer_semantic_repair_output_schema",
    "compose_answer",
]
