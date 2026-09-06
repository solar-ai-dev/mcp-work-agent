"""Compose the user-facing answer through the canonical Planning Prompt slot."""

from __future__ import annotations

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
from google_work_agent.application.agents.planning.project_empty_read_answer import (
    project_empty_read_answer,
)
from google_work_agent.application.agents.planning.project_gmail_decision_read_answer import (
    project_gmail_decision_read_answer,
)
from google_work_agent.application.agents.planning.project_gmail_read_planning import (
    project_gmail_read_planning,
)
from google_work_agent.application.agents.planning.project_gmail_security_read_answer import (
    project_gmail_security_read_answer,
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
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

PROMPT_ID = "planning.compose_answer"
MAX_USER_VISIBLE_ANSWER_CHARS = 2_400

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
    gmail_projection = project_gmail_read_planning(
        user_request=user_request,
        request_intent=request_intent,
        evidence=evidence,
    )
    if work_analysis is not None and gmail_projection is None:
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
            raise ValueError("task read answer references evidence outside its approved outline")
        return _with_partial_scope(task_projection.draft, retrieval_result)
    decision_projection = project_gmail_decision_read_answer(
        user_request=user_request,
        request_intent=request_intent,
        evidence=evidence,
    )
    if decision_projection is not None:
        if not set(decision_projection.draft["evidence_refs"]).issubset(approved_refs):
            raise ValueError("Gmail decision answer references evidence outside its outline")
        return _with_partial_scope(decision_projection.draft, retrieval_result)
    security_projection = project_gmail_security_read_answer(
        user_request=user_request,
        request_intent=request_intent,
        evidence=evidence,
    )
    if security_projection is not None:
        if not set(security_projection.draft["evidence_refs"]).issubset(approved_refs):
            raise ValueError("Gmail security answer references evidence outside its outline")
        return _with_partial_scope(security_projection.draft, retrieval_result)
    empty_projection = project_empty_read_answer(
        user_request=user_request,
        request_intent=request_intent,
        retrieval_result=retrieval_result,
        evidence=evidence,
    )
    if empty_projection is not None:
        return empty_projection.draft
    candidate = invoke(PROMPT_ID, prompt_input)
    schema_version = candidate.get("schema_version")
    answer = candidate.get("answer")
    refs = candidate.get("evidence_refs")
    if schema_version != 2:
        raise ValueError("compose_answer output requires schema_version 2")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("compose_answer output requires answer")
    normalized_answer = normalize_generated_answer_prose(answer)
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
        raise ValueError("compose_answer output exceeds the user-visible answer limit")
    if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
        raise ValueError("compose_answer output requires evidence_refs")
    allowed = set(answer_outline["evidence_refs"])
    if not set(refs).issubset(allowed):
        raise ValueError("compose_answer referenced evidence outside its projection")
    if len(refs) != len(set(refs)):
        raise ValueError("compose_answer output contains duplicate evidence_refs")
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
        raise ValueError("compose_answer output exceeds the user-visible answer limit")
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
        weekday = rf"{day_pattern}\s*\**\s*\(?[월화수목금토일](?:요일|\))"
        if re.search(explicit_year, answer) or re.search(weekday, answer):
            raise ValueError("compose_answer promoted an unresolved event date into a dated fact")


def _evidence_ref(item: Mapping[str, object]) -> str | None:
    value = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
    return value if isinstance(value, str) and value else None


__all__ = [
    "ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA",
    "MAX_USER_VISIBLE_ANSWER_CHARS",
    "answer_draft_output_schema",
    "compose_answer",
]
