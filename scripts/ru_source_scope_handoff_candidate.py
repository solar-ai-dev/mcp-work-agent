"""Inactive connected Source-scope contract candidate; no semantic inference here.

The existing Goal owner supplies category values and their exact request evidence.
This adapter validates and carries that decision; it neither selects Sources nor
turns ordinary Source mentions or selected identities into category restrictions.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from scripts.ru_observation import object_hash, observe_local_calls
from scripts.ru_output_source_handoff_candidate import _base, _SourcePolicyClient
from scripts.ru_scope_authority_candidate import SCOPE_FIELD_DESCRIPTION, ScopeAuthorityCandidate
from scripts.ru_source_scope_candidate import (
    SOURCE_CATEGORIES,
    SOURCE_SCOPE_FIELDS,
    source_scope_candidate,
)

from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    _runtime_policy_for_prompt,
)
from google_work_agent.application.agents.request_understanding import (
    finalize_intent as finalize_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_goal as goal_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.request_understanding import (
    preserve_explicit_search_anchors as projection_ops,
)
from google_work_agent.application.agents.request_understanding import (
    validate_intent as intent_ops,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import RuntimePolicy

SCOPE_PROVENANCE_DESCRIPTION = (
    "이 normalized 범주 제약의 근거인 현재 입력 source와 정확한 원문 source_text. "
    "범주 값과 원문 표현은 같을 필요가 없다."
)
SOURCE_PROMPT_ID = "request_understanding.identify_source_dependencies"
_ACTIVE_SCOPE_SESSION: ContextVar[SourceScopeHandoff | None] = ContextVar(
    "evaluation_source_scope_handoff", default=None
)
SOURCE_SCOPE_CONTRACT = (
    "goal_candidate.constraints.additional_constraints의 SCOPE 항목은 앞선 Goal owner가 "
    "현재 원문 provenance와 WorkUnit에 결속한 범주 제약이다. 해당 값과 귀속은 "
    "다시 생성하지 않고 소비한다. required_sources는 배타적 허용 범위이지 모든 범주의 "
    "필수 조회 지시가 아니다. 실제 필요한 Resource subtype과 정보는 이 owner가 판단한다. "
    "선택 Resource identity, Provider 권한, WRITE 승인 authority는 이 제약과 별개다."
)


def _is_scope(value: Mapping[str, Any]) -> bool:
    return value.get("field") in SOURCE_SCOPE_FIELDS


def _scope_item_schema(unit_ids: Sequence[str], *, normalized: bool) -> dict[str, Any]:
    provenance = {
        "type": "object",
        "additionalProperties": False,
        "required": ["source", "source_text"],
        "description": SCOPE_PROVENANCE_DESCRIPTION,
        "properties": {
            "source": {"enum": ["USER_REQUEST", "CONFIRMATION_RESPONSE"]},
            "source_text": {"type": "string", "minLength": 1},
        },
    }
    properties: dict[str, Any] = {
        "field": {"enum": list(SOURCE_SCOPE_FIELDS)},
        "value": {
            "oneOf": [
                {"enum": list(SOURCE_CATEGORIES)},
                {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"enum": list(SOURCE_CATEGORIES)},
                },
            ]
        },
        "work_unit_ids": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"enum": list(unit_ids)},
        },
        "provenance": provenance,
    }
    if normalized:
        properties["kind"] = {"const": "SCOPE"}
        cast(list[str], provenance["required"]).extend(["start_offset", "end_offset"])
        cast(dict[str, Any], provenance["properties"]).update(
            start_offset={"type": "integer", "minimum": 0},
            end_offset={"type": "integer", "minimum": 1},
        )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


@dataclass
class SourceScopeHandoff:
    """One isolated evaluation Run's immutable request/provenance authority."""

    user_request: str
    confirmation_response_text: str | None = None
    work_unit_ids: tuple[str, ...] = ()
    events: list[dict[str, Any]] = field(default_factory=list)
    source_projection_hashes: set[str] = field(default_factory=set)

    @property
    def sources(self) -> dict[str, str]:
        sources = {"USER_REQUEST": self.user_request}
        if self.confirmation_response_text is not None:
            sources["CONFIRMATION_RESPONSE"] = self.confirmation_response_text
        return sources

    def bind_work_units(self, unit_ids: Sequence[str]) -> None:
        unit_ids = tuple(unit_ids)
        if not unit_ids or len(set(unit_ids)) != len(unit_ids) or any(not x for x in unit_ids):
            raise ValueError("Source scope requires current closed WorkUnit IDs")
        if self.work_unit_ids and self.work_unit_ids != unit_ids:
            raise ValueError("Source scope WorkUnit authority changed in one candidate context")
        self.work_unit_ids = unit_ids

    def validate_scope(self, item: Mapping[str, Any], *, normalized: bool) -> dict[str, Any]:
        if not self.work_unit_ids:
            raise ValueError("Source scope current WorkUnit authority is unavailable")
        errors = validate_output_schema(
            item, _scope_item_schema(self.work_unit_ids, normalized=normalized)
        )
        if errors:
            raise ValueError(f"Source scope contract invalid: {'; '.join(errors)}")
        proof = item["provenance"]
        text = self.sources.get(proof["source"])
        span = proof["source_text"]
        if not span.strip() or text is None or span not in text:
            raise ValueError("Source scope provenance has no exact current-Run source span")
        if normalized:
            start, end = proof["start_offset"], proof["end_offset"]
            if end <= start or end > len(text) or text[start:end] != span:
                raise ValueError("Source scope provenance offsets do not match source")
            return deepcopy(dict(item))
        start = text.index(span)
        return {
            "kind": "SCOPE",
            **deepcopy(dict(item)),
            "provenance": {
                "source": proof["source"],
                "source_text": span,
                "start_offset": start,
                "end_offset": start + len(span),
            },
        }

    def raw_scopes(self, value: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [
            self.validate_scope(item, normalized=False)
            for item in value["constraints"]["additional_constraints"]
            if _is_scope(item)
        ]


@contextmanager
def source_scope_handoff_candidate(
    *,
    user_request: str,
    confirmation_response_text: str | None = None,
    work_unit_ids: Sequence[str] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> Iterator[SourceScopeHandoff]:
    """Close existing Goal→Source→Intent→Route scope handoff for a bounded candidate.

    No Product caller imports this adapter. Goal retains v16's instruction and
    adds only the required normalized-provenance representation to its schema.
    Source consumes the declared evaluation input contract, not an active Prompt.
    Existing runtime/sampling/repair and final Route policy checks remain the caller's.
    """
    session = SourceScopeHandoff(
        user_request=user_request,
        confirmation_response_text=confirmation_response_text,
        events=[] if events is None else events,
    )
    if work_unit_ids is not None:
        session.bind_work_units(work_unit_ids)
    original_input = goal_ops._prompt_input
    original_projection = projection_ops.project_extractive_source_goal
    original_normalize = goal_schema.validate_request_goal_candidate
    original_materialize = intent_ops.materialize_validated_constraint_provenance
    original_provenance_check = intent_ops._validate_provenance_binding

    def prompt_input(**kwargs: Any) -> dict[str, object]:
        result = original_input(**kwargs)
        if result["user_request"] != session.user_request:
            raise ValueError("Source scope request authority differs from current Run")
        if goal_ops._confirmation_response_text(kwargs["confirmation_response"]) != (
            session.confirmation_response_text
        ):
            raise ValueError("Source scope confirmation authority differs from current Run")
        session.bind_work_units(
            [item["unit_id"] for item in kwargs["requested_work"]["work_units"]]
        )
        return result

    def project(value: Any, *, request_text: str) -> dict[str, object]:
        if request_text != session.user_request:
            raise ValueError("Source scope projection request differs from current Run")
        scopes = session.raw_scopes(value)
        result = original_projection(value, request_text=request_text)
        cast(dict[str, Any], result["constraints"])["additional_constraints"] = deepcopy(scopes)
        session.source_projection_hashes.add(object_hash(result))
        session.events.append(
            {
                "stage": "SOURCE_SCOPE_PROJECTION",
                "goal_input_hash": object_hash(value),
                "source_projection_hash": object_hash(result),
                "scope_hash": object_hash(scopes),
                "scope_count": len(scopes),
            }
        )
        return result

    def normalize(value: Any, **kwargs: Any) -> Any:
        session.bind_work_units(kwargs["work_unit_ids"])
        sources = kwargs.get("provenance_sources")
        if sources is not None and dict(sources) != session.sources:
            raise ValueError("Source scope normalizer source authority differs from current Run")
        scoped = session.raw_scopes(value)
        result = original_normalize(value, **kwargs)
        scope_iter = iter(scoped)
        result["constraints"] = cast(
            Any, [next(scope_iter) if _is_scope(item) else item for item in result["constraints"]]
        )
        if next(scope_iter, None) is not None:
            raise ValueError("Source scope normalizer lost a model-owned constraint")
        session.events.append(
            {"stage": "SOURCE_SCOPE_NORMALIZED", "scope_hash": object_hash(scoped)}
        )
        return result

    def materialize(constraints: Any, **kwargs: Any) -> Any:
        if (
            kwargs["user_request"] != session.user_request
            or kwargs["confirmation_response_text"] != session.confirmation_response_text
        ):
            raise ValueError("Source scope finalizer source authority differs from current Run")
        result: list[Any] = []
        for item in constraints:
            if _is_scope(item):
                result.append(session.validate_scope(item, normalized=True))
            else:
                result.extend(original_materialize([item], **kwargs))
        return result

    def validate_provenance(constraint: Any, path: str, **kwargs: Any) -> None:
        if _is_scope(constraint):
            if dict(kwargs["provenance_sources"]) != session.sources:
                raise ValueError("Source scope validator source authority differs from current Run")
            session.validate_scope(constraint, normalized=True)
        else:
            original_provenance_check(constraint, path, **kwargs)

    with source_scope_candidate():
        item = cast(dict[str, Any], goal_schema._ADDITIONAL_CONSTRAINT_LIST_SCHEMA["items"])
        candidate = deepcopy(item)
        candidate["properties"]["field"]["description"] = SCOPE_FIELD_DESCRIPTION
        candidate["properties"]["provenance"] = _scope_item_schema(
            ("unused-shape-only",), normalized=False
        )["properties"]["provenance"]
        candidate["allOf"].append(
            {
                "if": {"properties": {"field": {"enum": list(SOURCE_SCOPE_FIELDS)}}},
                "then": {
                    "required": ["provenance"],
                    "properties": {
                        "value": _scope_item_schema((), normalized=False)["properties"]["value"]
                    },
                },
                "else": {"properties": {"provenance": {"enum": []}}},
            }
        )
        with (
            patch.dict(item, candidate, clear=True),
            patch.object(goal_ops, "_prompt_input", prompt_input),
            patch.object(goal_ops, "project_extractive_source_goal", project),
            patch.object(projection_ops, "project_extractive_source_goal", project),
            patch.object(goal_schema, "validate_request_goal_candidate", normalize),
            patch.object(goal_ops, "validate_request_goal_candidate", normalize),
            patch.object(intent_ops, "materialize_validated_constraint_provenance", materialize),
            patch.object(finalize_ops, "materialize_validated_constraint_provenance", materialize),
            patch.object(intent_ops, "_validate_provenance_binding", validate_provenance),
        ):
            token = _ACTIVE_SCOPE_SESSION.set(session)
            try:
                yield session
            finally:
                _ACTIVE_SCOPE_SESSION.reset(token)


class SourceScopeHandoffCandidate(ScopeAuthorityCandidate):
    """V16 Goal instruction plus exact-proof schema and connected Source handoff."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._registry = PromptRegistry()
        self._source_runtime_policy = _runtime_policy_for_prompt(
            RuntimePolicy(sampling_temperature=0.0, sampling_seed=self._sampling_seed),
            self._registry.lookup_for_evaluation(SOURCE_PROMPT_ID),
        )

    @property
    def source_sampling(self) -> dict[str, Any]:
        return {
            "authority": "existing Product _runtime_policy_for_prompt",
            "temperature": self._source_runtime_policy.sampling_temperature,
            "seed": self._sampling_seed,
            "timeout_seconds": 180,
        }

    @property
    def binding(self) -> dict[str, object]:
        contract = {
            "base_goal_instruction_sha256": super().binding["goal_output_prompt_sha256"],
            "scope_field_description": SCOPE_FIELD_DESCRIPTION,
            "scope_item_schema": _scope_item_schema(
                ("CLOSED_CURRENT_WORK_UNIT",), normalized=False
            ),
        }
        return {
            **super().binding,
            "candidate_id": "ru-source-scope-handoff-v24",
            "source_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "goal_output_schema_version": "evaluation-source-scope-handoff-v24",
            "goal_declared_contract_sha256": object_hash(contract),
            "source_handoff_contract_sha256": hashlib.sha256(
                SOURCE_SCOPE_CONTRACT.encode()
            ).hexdigest(),
            "source_sampling": self.source_sampling,
            "source_repair_limit": 1,
            "source_repair_contract": "existing evaluation candidate helper; not Product router",
        }

    def _build_goal_output_schema(self, **kwargs: Any) -> Any:
        schema = super()._build_goal_output_schema(**kwargs)
        item = cast(dict[str, Any], schema.json_schema)["properties"]["constraints"]["properties"][
            "additional_constraints"
        ]["items"]
        if "provenance" not in item["properties"]:
            raise ValueError("v24 requires source_scope_handoff_candidate context")
        return replace(schema, schema_version="evaluation-source-scope-handoff-v24")

    def infer(self, mode: Any, prompt: Any, projection: Any, schema: Any) -> Any:
        if prompt.prompt_id not in {"request_understanding.identify_goal", SOURCE_PROMPT_ID}:
            return super().infer(mode, prompt, projection, schema)
        session = _ACTIVE_SCOPE_SESSION.get()
        if session is None:
            raise ValueError("v24 requires one current-Run Source-scope handoff context")
        base = _base(projection)
        if base["user_request"] != session.user_request:
            raise ValueError("v24 inference request differs from current Run")
        session.bind_work_units([item["unit_id"] for item in base["requested_work"]["work_units"]])
        if prompt.prompt_id == "request_understanding.identify_goal":
            result = super().infer(mode, prompt, projection, schema)
            scopes = session.raw_scopes(result.structured_output)
            self.events.append(
                {
                    "operation": "GOAL_SCOPE_PROVENANCE",
                    "scope_count": len(scopes),
                    "scope_hash": object_hash(scopes),
                    "normalized_scopes": deepcopy(scopes),
                }
            )
            return result
        for item in base["goal_candidate"]["constraints"]["additional_constraints"]:
            session.validate_scope(item, normalized=True)
        if object_hash(base["goal_candidate"]) not in session.source_projection_hashes:
            raise ValueError("v24 Source requires the current validated Goal projection handoff")
        baseline_instruction = assemble_prompt(
            prompt, projection, registry=self._registry, execution_scope=EVALUATION
        )
        instruction = baseline_instruction + "\n" + SOURCE_SCOPE_CONTRACT
        evaluation_prompt = replace(
            prompt,
            prompt_id="evaluation.request_understanding.source_scope_handoff",
            prompt_version="v24",
            input_schema_version="evaluation-source-scope-handoff-v24",
            content_hash=hashlib.sha256(instruction.encode()).hexdigest(),
        )
        event: dict[str, Any] = {
            "operation": "SOURCE_SCOPE_HANDOFF",
            "input": deepcopy(projection),
            "input_sha256": object_hash(projection),
            "source_sampling": self.source_sampling,
            "baseline_assembled_instruction_sha256": hashlib.sha256(
                baseline_instruction.encode()
            ).hexdigest(),
            "instruction_sha256": evaluation_prompt.content_hash,
            "source_schema_sha256": object_hash(schema.json_schema),
            "transport_attempts": [],
        }
        self.events.append(event)
        try:
            with (
                patch.object(
                    self,
                    "_client",
                    _SourcePolicyClient(
                        self._client,
                        self._source_runtime_policy.sampling_temperature,
                    ),
                ),
                observe_local_calls(event["transport_attempts"]),
            ):
                raw, result, attempts = self._invoke_candidate(
                    requested_mode=mode,
                    prompt_ref=evaluation_prompt,
                    prompt_input=projection,
                    schema=schema,
                    instruction=instruction,
                )
            event.update(raw_output=deepcopy(raw), provider_attempts=deepcopy(attempts))
            source_ops.validate_source_dependency_candidate(
                raw,
                source_candidates=base["source_candidates"],
                work_unit_ids=session.work_unit_ids,
            )
            return result
        except Exception as error:
            event.update(error_type=type(error).__name__, error=str(error)[:500])
            raise
        finally:
            for index, attempt in enumerate(event["transport_attempts"]):
                attempt["attempt"] = "FIRST" if index == 0 else "SCHEMA_REPAIR"
