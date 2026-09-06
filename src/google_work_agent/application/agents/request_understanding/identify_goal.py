from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.resolve_request_scope import (
    resolve_request_scope,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

from .contracts.request_goal_candidate_schema import (
    IDENTIFY_GOAL_OUTPUT_SCHEMA,
    REQUEST_GOAL_SLOT_KINDS,
    validate_request_goal_candidate,
)
from .preserve_vague_read_semantics import preserve_vague_read_semantics


def identify_goal(
    *,
    llm_runtime: StructuredInferencePort,
    request: WorkflowStartRequest,
    prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> RequestGoalCandidateV1:
    """Identify only the current Run's goal semantics."""
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "request_understanding.identify_goal", manifest_path or default_prompt_manifest_path()
    )
    prompt_input: dict[str, object] = {
        "user_request": request.request_text,
        "selected_resource_refs": [
            {
                "resource_ref_id": ref.resource_ref_id,
                "connector_id": ref.connector_id,
                "resource_type": ref.resource_type,
                "resource_id": ref.resource_id,
                "parent_resource_id": ref.parent_resource_id,
            }
            for ref in request.selected_resources
        ],
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    output_schema = _output_schema_for_request(request)
    result = llm_runtime.infer(
        request.requested_mode,
        resolved_prompt_ref,
        prompt_input,
        output_schema,
    )
    candidate = _apply_quoted_literal_authority(
        validate_request_goal_candidate(result.structured_output, schema=output_schema),
        request_text=request.request_text,
    )
    candidate = _apply_explicit_read_authority(candidate, request_text=request.request_text)
    candidate = preserve_vague_read_semantics(
        candidate,
        request_text=request.request_text,
        entry_mode=request.entry_mode,
    )
    candidate = _apply_general_answer_only_authority(candidate, request=request)
    candidate = _apply_selected_resource_authority(candidate, request=request)
    return validate_request_goal_candidate(candidate)


_EXPLICIT_READ_RESOURCE_PATTERNS = (
    (re.compile(r"(?i)(?<![a-z])google\s+tasks?(?![a-z])"), "TASK"),
    (re.compile(r"(?i)(?<![a-z])gmail(?![a-z])"), "GMAIL_THREAD"),
    (re.compile(r"(?i)(?<![a-z])e-?mail(?![a-z])|메일"), "GMAIL_THREAD"),
    (re.compile(r"(?i)(?<![a-z])google\s+calendar(?![a-z])"), "CALENDAR_EVENT"),
)
_EXPLICIT_READ_MARKERS = (
    "알려",
    "보여",
    "목록",
    "찾아",
    "읽어",
    "요약",
    "분석",
    "list",
    "find",
    "read",
    "show",
    "summarize",
    "analyse",
    "analyze",
)
_EXPLICIT_ANALYSIS_MARKERS = (
    "분석",
    "비교",
    "결정",
    "결론",
    "영향",
    "원인",
    "리스크",
    "관계",
    "analy",
    "compare",
    "decision",
    "conclusion",
    "impact",
    "risk",
)
_EXPLICIT_DATE_SIGNAL = re.compile(
    r"(?i)(?:"
    r"\d{1,4}\s*(?:년|[-./])\s*\d{1,2}"
    r"|\d{1,2}\s*월\s*\d{1,2}\s*일"
    r"|오늘|내일|모레|이번\s*주|다음\s*주|다음\s*달|주말"
    r"|월요일|화요일|수요일|목요일|금요일|토요일|일요일"
    r"|까지|마감|기한|날짜|due|deadline|today|tomorrow|next\s+(?:week|month)"
    r")"
)


def _apply_quoted_literal_authority(
    candidate: RequestGoalCandidateV1,
    *,
    request_text: str,
) -> RequestGoalCandidateV1:
    """Do not reinterpret a quoted resource literal as an unstated date."""

    scope = resolve_request_scope(request_text)
    outside_literals = scope.outside_quoted_literals
    quoted_literals = scope.quoted_literals
    if not quoted_literals:
        return candidate
    literal_values: dict[str, set[str]] = {}
    for literal in quoted_literals:
        original = literal[1:-1]
        literal_values.setdefault(re.sub(r"\s+", "", original), set()).add(original)
    constraints = []
    for constraint in candidate["constraints"]:
        value = constraint["value"]
        if isinstance(value, str):
            matches = literal_values.get(re.sub(r"\s+", "", value), set())
            if len(matches) == 1:
                constraint = {**constraint, "value": next(iter(matches))}
        constraints.append(constraint)
    outside_has_date_signal = _EXPLICIT_DATE_SIGNAL.search(outside_literals) is not None
    quoted_text = " ".join(quoted_literals)
    constraints = [
        constraint
        for constraint in constraints
        if constraint["kind"] != "DATE"
        or (
            outside_has_date_signal
            and (
                not _date_value_appears_in_text(constraint["value"], quoted_text)
                or _date_value_appears_in_text(constraint["value"], outside_literals)
            )
        )
    ]
    return {**candidate, "constraints": constraints}


def _date_value_appears_in_text(value: object, text: str) -> bool:
    values = value if isinstance(value, list) else [value]
    for item in values:
        if not isinstance(item, str):
            continue
        match = re.search(r"(?:\d{4}[-./])?(\d{1,2})[-./](\d{1,2})", item)
        if match is None:
            continue
        month, day = (int(match.group(1)), int(match.group(2)))
        token = re.compile(rf"(?<!\d)0?{month}\s*(?:[-./]|월\s*)0?{day}(?:\s*일)?(?!\d)")
        if token.search(text):
            return True
    return False


def _output_schema_for_request(request: WorkflowStartRequest) -> OutputSchemaDefinition:
    """Constrain explicit effects without granting execution authority."""

    has_explicit_read = _has_explicit_read_authority(request.request_text)
    gmail_search = (
        request.entry_mode == "AGENT_SEARCH"
        and _explicit_read_resource_hints(request.request_text) == ["GMAIL_THREAD"]
        and not resolve_request_scope(request.request_text).has_explicit_write_marker
    )
    outside_literals = resolve_request_scope(request.request_text).outside_quoted_literals
    has_explicit_create = (
        re.search(
            r"(?is)(?:Google\s+Tasks|태스크|Google\s+Calendar|캘린더)"
            r"[^.!?]{0,300}(?:등록|생성|추가|만들어)\s*해?\s*(?:줘|주세요)[.!?\s]*$",
            outside_literals,
        )
        is not None
    )
    if not (
        has_explicit_read or has_explicit_create or gmail_search
        or _selected_resource_hints(request)
    ):
        return IDENTIFY_GOAL_OUTPUT_SCHEMA
    schema = cast(dict[str, object], deepcopy(IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema))
    if has_explicit_read or _selected_resource_hints(request):
        schema.pop("allOf", None)
    if has_explicit_create:
        effects = cast(dict[str, object], schema["properties"])["requested_effect_hints"]
        cast(dict[str, object], effects)["contains"] = {"const": "CREATE"}
    if request.entry_mode == "AGENT_SEARCH" and (has_explicit_read or gmail_search):
        constraints = cast(dict[str, object], schema["properties"])["constraints"]
        cast(dict[str, object], constraints)["minItems"] = 1
        if gmail_search:
            preserved = preserve_vague_read_semantics(
                {"goal": "", "completion_conditions": [], "constraints": [],
                 "requested_effect_hints": ["READ"], "requested_resource_hints": ["GMAIL_THREAD"],
                 "analysis_requirement": "NONE"},
                request_text=request.request_text, entry_mode=request.entry_mode,
            )
            explicit = {item["field"]: item["value"] for item in preserved["constraints"]}
            slot_properties: dict[str, object] = {
                field: {"type": "array", "items": {
                            "type": "string", "minLength": 1, "pattern": r".*[^\s\[\]{}].*",
                        },
                        "maxItems": 8}
                for field in REQUEST_GOAL_SLOT_KINDS
            }
            slot_properties["temporal_axis"] = {
                "type": "array", "maxItems": 1,
                "minItems": int("period" in explicit),
                "items": {"enum": ["MESSAGE_TIME", "EVENT_TIME"]},
                "description": (
                    "기간이 메일 수신/발송을 제한할 때만 MESSAGE_TIME. "
                    "메일에서 찾는 행사/일정의 기간이면 EVENT_TIME. 자료원이 메일인 것과 구별한다."
                ),
            }
            slot_properties["search_terms"] = {
                "type": "array", "maxItems": 8, "items": {
                    "type": "string", "minLength": 1, "pattern": r".*[^\s\[\]{}].*",
                },
                "description": (
                    "사용자 원문에 있는 프로젝트 고유명만 그대로 복사한다. "
                    "일반 명사·업무 개념·인물·기간·답변 지시는 제외한다. "
                    "고유명에 단어를 붙여 확장하지 않는다."
                ),
            }
            cast(dict[str, object], slot_properties["business_concepts"])["description"] = (
                "사용자가 찾는 원래 업무 개념만 짧게 보존한다. "
                "동의어나 하위 업무를 생성하지 않는다. "
                "날짜·담당·최종 여부는 required_information이다. "
                "메일 조회·검색·확인·요약은 수행할 동작이지 업무 개념이 아니다."
            )
            for field, description in {
                "person": "원문에 명시된 사람 이름·직급·별칭만. 프로젝트명을 붙이지 않는다.",
                "sender": "누가 보냈는지 명시된 경우 그 사람 표현만. 프로젝트와 업무 수식어 제외.",
                "recipient": "누가 받았는지 명시된 경우만. 본문에 등장하는 사람과 구분한다.",
                "period": "날짜가 제한하는 대상의 기간 표현을 그대로 보존한다.",
                "required_information": (
                    "답변에서 확인할 사실. 검색 원문에 있어야 할 문구가 아니다."
                ),
                "status": "명시된 메일 상태만. 다른 자료원의 OPEN/INCOMPLETE 등을 만들지 않는다.",
            }.items():
                cast(dict[str, object], slot_properties[field])["description"] = description
            for field in ("person", "period"):
                if field in explicit:
                    cast(dict[str, object], slot_properties[field])["minItems"] = 1
            if (
                "subject" not in explicit
                and re.search(r"제목|subject", request.request_text, re.I) is None
            ):
                cast(dict[str, object], slot_properties["subject"])["maxItems"] = 0
            cast(dict[str, object], schema["properties"])["constraints"] = {
                "type": "object", "additionalProperties": False,
                "required": list(slot_properties), "properties": slot_properties,
                "description": (
                    "모든 의미 슬롯을 각각 확인한다. 미언급은 []이며 값을 추측하지 않는다."
                ),
            }
            properties = cast(dict[str, object], schema["properties"])
            schema["properties"] = {
                "constraints": properties["constraints"],
                **{key: value for key, value in properties.items() if key != "constraints"},
            }
            schema["required"] = list(cast(dict[str, object], schema["properties"]))
    return OutputSchemaDefinition(
        schema_version=IDENTIFY_GOAL_OUTPUT_SCHEMA.schema_version,
        json_schema=schema,
    )


def _has_explicit_read_authority(request_text: str) -> bool:
    normalized = request_text.casefold()
    return (
        bool(_explicit_read_resource_hints(request_text))
        and any(marker in normalized for marker in _EXPLICIT_READ_MARKERS)
        and not resolve_request_scope(request_text).has_explicit_write_marker
    )


def _explicit_read_resource_hints(request_text: str) -> list[str]:
    # Payload literals and email domains are values, not resource requests.
    request_text = resolve_request_scope(request_text).outside_quoted_literals
    request_text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", " ", request_text)
    return list(
        dict.fromkeys(
            resource_type
            for pattern, resource_type in _EXPLICIT_READ_RESOURCE_PATTERNS
            if pattern.search(request_text)
        )
    )


def _apply_general_answer_only_authority(
    candidate: RequestGoalCandidateV1,
    *,
    request: WorkflowStartRequest,
) -> RequestGoalCandidateV1:
    """Remove model-invented Workspace reads from explicit advice requests."""

    if (
        request.selected_resources
        or not resolve_request_scope(request.request_text).is_general_answer_only
        or any(effect != "READ" for effect in candidate["requested_effect_hints"])
    ):
        return candidate
    return {
        **candidate,
        "requested_effect_hints": [],
        "requested_resource_hints": [],
        "analysis_requirement": "NONE",
    }


def _apply_explicit_read_authority(
    candidate: RequestGoalCandidateV1,
    *,
    request_text: str,
) -> RequestGoalCandidateV1:
    """Preserve explicit reads and reject model-invented Workspace effects."""
    explicit_resources = _explicit_read_resource_hints(request_text)
    if _has_explicit_read_authority(request_text):
        return {
            **candidate,
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": explicit_resources,
            "analysis_requirement": (
                "REQUIRED"
                if _has_explicit_analysis_request(request_text)
                else candidate["analysis_requirement"]
            ),
        }
    resources = list(candidate["requested_resource_hints"])
    for resource_type in explicit_resources:
        if resource_type not in resources:
            resources.append(resource_type)
    return {
        **candidate,
        "requested_resource_hints": resources,
    }


def _has_explicit_analysis_request(request_text: str) -> bool:
    normalized = request_text.casefold()
    return any(marker in normalized for marker in _EXPLICIT_ANALYSIS_MARKERS)


def _apply_selected_resource_authority(
    candidate: RequestGoalCandidateV1,
    *,
    request: WorkflowStartRequest,
) -> RequestGoalCandidateV1:
    """Preserve trusted UI selection facts outside model-owned semantics."""
    if request.entry_mode != "RESOURCE_SELECTED" or not request.selected_resources:
        return candidate

    resource_ids = list(dict.fromkeys(ref.resource_id for ref in request.selected_resources))
    constraints = list(candidate["constraints"])
    constrained_resource_ids = {
        str(item)
        for constraint in constraints
        if constraint["kind"] == "RESOURCE"
        for item in (
            constraint["value"] if isinstance(constraint["value"], list) else [constraint["value"]]
        )
    }
    missing_resource_ids = [
        resource_id for resource_id in resource_ids if resource_id not in constrained_resource_ids
    ]
    if missing_resource_ids:
        constraints.append(
            {
                "kind": "RESOURCE",
                "field": "selected_resource_id",
                "value": missing_resource_ids,
            }
        )

    effects = list(candidate["requested_effect_hints"])
    if "READ" not in effects:
        effects.insert(0, "READ")
    resource_hints = list(candidate["requested_resource_hints"])
    for hint in _selected_resource_hints(request):
        if hint not in resource_hints:
            resource_hints.append(hint)
    return {
        **candidate,
        "constraints": constraints,
        "requested_effect_hints": effects,
        "requested_resource_hints": resource_hints,
    }


_SELECTED_RESOURCE_HINTS = {
    ("google_workspace", resource_type): resource_type
    for resource_type in (
        "GMAIL_THREAD",
        "GMAIL_MESSAGE",
        "GMAIL_DRAFT",
        "GMAIL_ATTACHMENT",
        "TASK_LIST",
        "TASK",
        "CALENDAR",
        "CALENDAR_EVENT",
        "CALENDAR_FREEBUSY",
    )
} | {("github", "GITHUB_ISSUE"): "GITHUB_ISSUE"}


def _selected_resource_hints(request: WorkflowStartRequest) -> list[str]:
    return list(
        dict.fromkeys(
            hint
            for ref in request.selected_resources
            for hint in (
                _SELECTED_RESOURCE_HINTS.get((ref.connector_id, ref.resource_type.upper())),
            )
            if hint is not None
        )
    )
