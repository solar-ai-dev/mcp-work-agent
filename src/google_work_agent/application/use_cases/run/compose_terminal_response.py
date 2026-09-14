"""Compose one user-visible verified WRITE result through the Product LLM runtime."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from google_work_agent.application.agents.planning.sanitize_user_visible_answer import (
    sanitize_user_visible_answer,
)
from google_work_agent.application.use_cases.run.build_terminal_message import (
    TerminalAssistantMessageInputV1,
    validate_terminal_assistant_message_input,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort

PROMPT_ID = "run.compose_terminal_response"
MAX_TERMINAL_RESPONSE_CHARS = 2_400

type TerminalWriteResultKindV1 = Literal["SUCCESS", "PARTIAL"]
type TerminalWriteEffectV1 = Literal["CREATE", "UPDATE", "SEND", "DELETE"]
type TerminalWriteStatusV1 = Literal[
    "VERIFIED",
    "REJECTED",
    "FAILED",
    "BLOCKED",
    "DEPENDENCY_BLOCKED",
    "CANCELLED",
]

_WRITE_EFFECTS = frozenset({"CREATE", "UPDATE", "SEND", "DELETE"})
_CLOSED_WRITE_STATUSES = frozenset(
    {"VERIFIED", "REJECTED", "FAILED", "BLOCKED", "DEPENDENCY_BLOCKED", "CANCELLED"}
)
_VERIFIED_FIELDS_BY_RESOURCE_TYPE: dict[str, tuple[str, ...]] = {
    "calendar_event": (
        "title",
        "start",
        "end",
        "timezone",
        "location",
        "description",
        "attendees",
    ),
    "task": ("title", "due", "status", "notes"),
    "gmail_draft": ("subject", "body", "to", "cc"),
    "gmail_message": ("subject", "to", "cc"),
    "github_issue": ("title", "state"),
}
_EXCERPT_FIELDS = frozenset({"body", "description", "notes"})
_TARGET_FIELDS = ("subject", "title")

TERMINAL_RESPONSE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="run-terminal-response-v1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {
            "answer": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_TERMINAL_RESPONSE_CHARS,
                "description": (
                    "사용자에게 보여줄 최종 설명문. 입력으로 제공된 실행·검증 결과만 "
                    "설명하며 JSON, 내부 코드, Tool 호출을 포함하지 않는다."
                ),
            }
        },
    },
)


class TerminalResponseOutputError(ValueError):
    """Raised for a detectable, bounded response-output violation."""


@dataclass(frozen=True, slots=True)
class TerminalVerifiedFieldV1:
    field: str
    value: str

    def to_projection(self) -> dict[str, object]:
        return {"field": self.field, "value": self.value}


@dataclass(frozen=True, slots=True)
class TerminalActionResultProjectionV1:
    connector_id: str
    resource_type: str
    target_label: str
    effect_type: TerminalWriteEffectV1
    status: TerminalWriteStatusV1
    verified_fields: tuple[TerminalVerifiedFieldV1, ...]

    def to_projection(self) -> dict[str, object]:
        return {
            "connector_id": self.connector_id,
            "resource_type": self.resource_type,
            "target_label": self.target_label,
            "effect_type": self.effect_type,
            "status": self.status,
            "verified_fields": [item.to_projection() for item in self.verified_fields],
        }


@dataclass(frozen=True, slots=True)
class TerminalEffectObservationV1:
    effect_type: TerminalWriteEffectV1
    scope: Literal["CURRENT_RUN"]
    dispatched: bool

    def to_projection(self) -> dict[str, object]:
        return {
            "effect_type": self.effect_type,
            "scope": self.scope,
            "dispatched": self.dispatched,
        }


@dataclass(frozen=True, slots=True)
class TerminalResponseInputV1:
    schema_version: Literal[1]
    user_request: str
    result_kind: TerminalWriteResultKindV1
    action_results: tuple[TerminalActionResultProjectionV1, ...]
    effect_observations: tuple[TerminalEffectObservationV1, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("terminal response input schema_version must be 1")
        if not self.user_request.strip() or len(self.user_request.encode("utf-8")) > 16_384:
            raise ValueError("terminal response user_request is invalid")
        if self.result_kind not in {"SUCCESS", "PARTIAL"}:
            raise ValueError("terminal response result_kind is invalid")
        if not self.action_results or len(self.action_results) > 50:
            raise ValueError("terminal response requires 1..50 action results")
        if len(self.effect_observations) > 8 or len(self.limitations) > 20:
            raise ValueError("terminal response bounded collections are invalid")
        if any(not item.strip() or len(item) > 500 for item in self.limitations):
            raise ValueError("terminal response limitations are invalid")

    def to_projection(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "user_request": self.user_request,
            "result_kind": self.result_kind,
            "action_results": [item.to_projection() for item in self.action_results],
            "effect_observations": [item.to_projection() for item in self.effect_observations],
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class ComposeTerminalResponseCommandV1:
    schema_version: Literal[1]
    run_id: str
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    response_input: TerminalResponseInputV1
    fallback_message: TerminalAssistantMessageInputV1


@dataclass(frozen=True, slots=True)
class ComposeTerminalResponseResultV1:
    terminal_message: TerminalAssistantMessageInputV1
    generation_mode: Literal["LLM", "FALLBACK"]
    fallback_reason: str | None
    provider: str | None
    model: str | None
    actual_runtime: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int | None


class ComposeTerminalResponseHandler:
    """Use only the structured inference capability and preserve deterministic fallback."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredInferencePort,
        prompt_ref: PromptReference,
        logger: logging.Logger | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._prompt_ref = prompt_ref
        self._logger = logger or logging.getLogger(__name__)

    def __call__(
        self, command: ComposeTerminalResponseCommandV1
    ) -> ComposeTerminalResponseResultV1:
        if command.schema_version != 1 or not command.run_id.strip():
            raise ValueError("invalid terminal response command")
        if command.fallback_message.result_kind != command.response_input.result_kind:
            raise ValueError("terminal response fallback result_kind mismatch")
        validate_terminal_assistant_message_input(command.fallback_message)
        prompt_input = command.response_input.to_projection()
        try:
            result = self._llm_runtime.infer(
                command.requested_mode,
                self._prompt_ref,
                prompt_input,
                TERMINAL_RESPONSE_OUTPUT_SCHEMA,
            )
            answer = _validated_visible_answer(
                result.structured_output,
                response_input=command.response_input,
            )
        except LLMInvocationError as error:
            return self._fallback(command, error.code.value)
        except TerminalResponseOutputError:
            return self._fallback(command, "TERMINAL_RESPONSE_OUTPUT_INVALID")

        message = validate_terminal_assistant_message_input(
            TerminalAssistantMessageInputV1(
                schema_version=1,
                result_kind=command.fallback_message.result_kind,
                content=answer,
                reason_codes=list(command.fallback_message.reason_codes),
            )
        )
        self._logger.info(
            "terminal response composed",
            extra={
                "run_id": command.run_id,
                "generation_mode": "LLM",
                "provider": result.provider,
                "model": result.model,
                "actual_runtime": result.actual_runtime,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
            },
        )
        return ComposeTerminalResponseResultV1(
            terminal_message=message,
            generation_mode="LLM",
            fallback_reason=None,
            provider=result.provider,
            model=result.model,
            actual_runtime=result.actual_runtime,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
        )

    def _fallback(
        self,
        command: ComposeTerminalResponseCommandV1,
        reason: str,
    ) -> ComposeTerminalResponseResultV1:
        self._logger.warning(
            "terminal response used deterministic fallback",
            extra={
                "run_id": command.run_id,
                "generation_mode": "FALLBACK",
                "fallback_reason": reason,
            },
        )
        return ComposeTerminalResponseResultV1(
            terminal_message=command.fallback_message,
            generation_mode="FALLBACK",
            fallback_reason=reason,
            provider=None,
            model=None,
            actual_runtime=None,
            input_tokens=0,
            output_tokens=0,
            latency_ms=None,
        )


def build_terminal_response_input(
    *,
    user_request: str,
    result_kind: str,
    actions: object,
    send_not_dispatched_current_run: bool,
) -> TerminalResponseInputV1:
    """Project only durable, display-safe WRITE facts into the LLM input contract."""

    if not isinstance(actions, (list, tuple)):
        raise ValueError("terminal response actions must be a collection")
    projected_actions: list[TerminalActionResultProjectionV1] = []
    limitations: list[str] = []
    for raw_action in actions:
        if not isinstance(raw_action, Mapping):
            raise ValueError("terminal response actions must contain objects")
        effect = raw_action.get("effect_type")
        status = raw_action.get("status")
        if effect not in _WRITE_EFFECTS or status not in _CLOSED_WRITE_STATUSES:
            continue
        connector_id = _required_bounded_text(
            raw_action.get("connector_id"), "action.connector_id", 128
        )
        resource_type = _required_bounded_text(
            raw_action.get("resource_type"), "action.resource_type", 128
        )
        target_display = raw_action.get("target_display", {})
        if not isinstance(target_display, Mapping):
            raise ValueError("action.target_display must be an object")
        actual = raw_action.get("verification_actual")
        if actual is not None and not isinstance(actual, Mapping):
            raise ValueError("action.verification_actual must be an object or null")
        verified_fields = (
            _project_verified_fields(resource_type, cast(Mapping[str, object], actual))
            if status == "VERIFIED" and isinstance(actual, Mapping)
            else ()
        )
        projected_actions.append(
            TerminalActionResultProjectionV1(
                connector_id=connector_id,
                resource_type=resource_type,
                target_label=_target_label(
                    resource_type=resource_type,
                    target_display=target_display,
                    verified_fields=verified_fields,
                ),
                effect_type=cast(TerminalWriteEffectV1, effect),
                status=cast(TerminalWriteStatusV1, status),
                verified_fields=verified_fields,
            )
        )
        if effect == "SEND" and status == "VERIFIED":
            limitations.append(
                "전송 결과는 확인했지만 수신자의 실제 수신 또는 열람 여부는 확인하지 않았다."
            )

    observations: tuple[TerminalEffectObservationV1, ...] = ()
    if send_not_dispatched_current_run:
        observations = (
            TerminalEffectObservationV1(
                effect_type="SEND",
                scope="CURRENT_RUN",
                dispatched=False,
            ),
        )
    return TerminalResponseInputV1(
        schema_version=1,
        user_request=user_request,
        result_kind=cast(TerminalWriteResultKindV1, result_kind),
        action_results=tuple(projected_actions),
        effect_observations=observations,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _project_verified_fields(
    resource_type: str,
    actual: Mapping[str, object],
) -> tuple[TerminalVerifiedFieldV1, ...]:
    nested = actual.get("payload")
    source = cast(Mapping[str, object], nested) if isinstance(nested, Mapping) else actual
    result: list[TerminalVerifiedFieldV1] = []
    for field in _VERIFIED_FIELDS_BY_RESOURCE_TYPE.get(resource_type, ()):
        value = source.get(field)
        text = _display_value(value, maximum=500)
        if text is None:
            continue
        result.append(
            TerminalVerifiedFieldV1(
                field=f"{field}_excerpt" if field in _EXCERPT_FIELDS else field,
                value=text,
            )
        )
    return tuple(result)


def _target_label(
    *,
    resource_type: str,
    target_display: Mapping[object, object],
    verified_fields: Sequence[TerminalVerifiedFieldV1],
) -> str:
    verified_by_field = {item.field: item.value for item in verified_fields}
    for field in _TARGET_FIELDS:
        if value := verified_by_field.get(field):
            return value
    for field in _TARGET_FIELDS:
        raw_value = target_display.get(field)
        if text := _display_value(raw_value, maximum=500):
            return text
    return {
        "calendar_event": "일정",
        "task": "태스크",
        "gmail_draft": "메일 초안",
        "gmail_message": "메일",
        "github_issue": "GitHub Issue",
    }.get(resource_type, "외부 작업")


def _validated_visible_answer(
    output: Mapping[str, object],
    *,
    response_input: TerminalResponseInputV1,
) -> str:
    errors = validate_output_schema(output, TERMINAL_RESPONSE_OUTPUT_SCHEMA.json_schema)
    if errors:
        raise TerminalResponseOutputError("terminal response output schema is invalid")
    if set(output) != {"answer"}:
        raise TerminalResponseOutputError("terminal response output fields are invalid")
    raw_answer = output.get("answer")
    if not isinstance(raw_answer, str) or not raw_answer.strip():
        raise TerminalResponseOutputError("terminal response answer is blank")
    if "```" in raw_answer or raw_answer.lstrip().startswith(("{", "[")):
        raise TerminalResponseOutputError("terminal response answer contains serialization")
    internal_refs = (
        {item.connector_id for item in response_input.action_results}
        | {item.resource_type for item in response_input.action_results}
        | {item.status for item in response_input.action_results}
        | {item.effect_type for item in response_input.action_results}
    )
    source_texts = [
        field.value for action in response_input.action_results for field in action.verified_fields
    ]
    answer = sanitize_user_visible_answer(
        raw_answer,
        internal_refs=internal_refs,
        user_request=response_input.user_request,
        source_texts=source_texts,
    )
    if not answer or len(answer) > MAX_TERMINAL_RESPONSE_CHARS:
        raise TerminalResponseOutputError("terminal response answer length is invalid")
    return answer


def _display_value(value: object, *, maximum: int) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        text = ", ".join(str(item) for item in value)
    elif isinstance(value, (str, int, float, bool)):
        text = str(value)
    else:
        return None
    normalized = " ".join(text.split())
    if not normalized:
        return None
    return normalized if len(normalized) <= maximum else f"{normalized[: maximum - 3]}..."


def _required_bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} is invalid")
    return value


__all__ = [
    "ComposeTerminalResponseCommandV1",
    "ComposeTerminalResponseHandler",
    "ComposeTerminalResponseResultV1",
    "MAX_TERMINAL_RESPONSE_CHARS",
    "PROMPT_ID",
    "TERMINAL_RESPONSE_OUTPUT_SCHEMA",
    "TerminalActionResultProjectionV1",
    "TerminalEffectObservationV1",
    "TerminalResponseInputV1",
    "TerminalResponseOutputError",
    "TerminalVerifiedFieldV1",
    "build_terminal_response_input",
]
