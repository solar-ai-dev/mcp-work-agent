from __future__ import annotations

import re
from pathlib import Path

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

from .contracts.request_goal_candidate_schema import (
    IDENTIFY_GOAL_OUTPUT_SCHEMA,
    validate_normalized_request_goal_candidate,
    validate_request_goal_candidate,
)
from .preserve_explicit_search_anchors import preserve_explicit_search_anchors


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
    result = llm_runtime.infer(
        request.requested_mode,
        resolved_prompt_ref,
        prompt_input,
        IDENTIFY_GOAL_OUTPUT_SCHEMA,
    )
    candidate = _apply_quoted_literal_authority(
        validate_request_goal_candidate(result.structured_output),
        request_text=request.request_text,
    )
    candidate = preserve_explicit_search_anchors(
        candidate,
        request_text=request.request_text,
        entry_mode=request.entry_mode,
    )
    candidate = _apply_selected_resource_authority(candidate, request=request)
    candidate = _normalize_new_gmail_send_scope(candidate, request=request)
    return validate_normalized_request_goal_candidate(candidate)


_QUOTED_LITERAL_PATTERNS = (
    re.compile(r"'[^']*'"),
    re.compile(r'"[^"]*"'),
    re.compile(r"‘[^’]*’"),
    re.compile(r"“[^”]*”"),
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

    outside_literals = request_text
    quoted_literals: list[str] = []
    for pattern in _QUOTED_LITERAL_PATTERNS:
        quoted_literals.extend(pattern.findall(request_text))
        outside_literals = pattern.sub(" ", outside_literals)
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


def _normalize_new_gmail_send_scope(
    candidate: RequestGoalCandidateV1,
    *,
    request: WorkflowStartRequest,
) -> RequestGoalCandidateV1:
    """Do not turn new-send result Verification into a business READ."""
    if request.entry_mode != "AGENT_SEARCH" or request.selected_resources:
        return candidate
    if set(candidate["requested_effect_hints"]) != {"READ", "SEND"}:
        return candidate
    if set(candidate["requested_resource_hints"]) != {"GMAIL_MESSAGE"}:
        return candidate
    named_values = {
        constraint["field"]
        for constraint in candidate["constraints"]
        if constraint["value"]
    }
    if not {"recipient", "subject"} <= named_values:
        return candidate
    return {
        **candidate,
        "requested_effect_hints": ["SEND"],
        "requested_resource_hints": ["GMAIL_MESSAGE"],
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
