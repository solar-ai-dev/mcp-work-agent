"""Evaluation-only RU semantic-authority candidates.

The candidates keep the compiled Product graph and validators while comparing
request-local WorkUnit provenance and several Goal/Source/Output ownership shapes.
They never dispatch a Connector or Provider operation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, cast

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.request_understanding import (
    identify_effect_prohibitions as prohibition_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema_ops,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.runtime_selection import OLLAMA_FIXED_LOOPBACK_ENDPOINT
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import (
    StructuredInferencePort,
    StructuredInferenceResultV1,
)

_CANDIDATE_ROOT = (
    Path(__file__).parent / "prompt_candidates" / "ru-atomic-semantic-authority-v2" / "sources"
)
WORK_PROMPT_PATH = _CANDIDATE_ROOT / "request_understanding.identify_requested_work.md"
AUTHORITY_PROMPT_PATH = _CANDIDATE_ROOT / "request_understanding.identify_semantic_authority.md"
GOAL_OUTPUT_PROMPT_PATH = (
    Path(__file__).parent
    / "prompt_candidates"
    / "ru-goal-output-authority-v3"
    / "sources"
    / "request_understanding.identify_goal_output_authority.md"
)
GOAL_OUTPUT_MODALITY_PROMPT_PATH = (
    Path(__file__).parent
    / "prompt_candidates"
    / "ru-goal-output-modality-authority-v4"
    / "sources"
    / "request_understanding.identify_goal_output_authority.md"
)
_RESULT_MODE_FIRST_ROOT = (
    Path(__file__).parent / "prompt_candidates" / "ru-result-mode-first-v5" / "sources"
)
GOAL_RESULT_MODE_PROMPT_PATH = (
    _RESULT_MODE_FIRST_ROOT / "request_understanding.identify_goal_result_mode.md"
)
EXTERNAL_OUTPUT_PROMPT_PATH = (
    _RESULT_MODE_FIRST_ROOT / "request_understanding.identify_external_outputs.md"
)
_WORK_PROMPT_ID = "evaluation.request_understanding.identify_requested_work_by_ref"
_AUTHORITY_PROMPT_ID = "evaluation.request_understanding.identify_semantic_authority"
_GOAL_OUTPUT_PROMPT_ID = "evaluation.request_understanding.identify_goal_output_authority"
_GOAL_RESULT_MODE_PROMPT_ID = "evaluation.request_understanding.identify_goal_result_mode"
_EXTERNAL_OUTPUT_PROMPT_ID = "evaluation.request_understanding.identify_external_outputs"
_TOKEN_PATTERN = re.compile(r"\S+")


class AtomicSemanticAuthorityCandidate:
    """Structured-inference adapter for the bounded evaluation candidate."""

    def __init__(
        self,
        *,
        delegate: StructuredInferencePort,
        tool_catalog: Any,
        model_id: str,
        sampling_seed: int,
        client: OllamaHTTPClient | None = None,
    ) -> None:
        self._delegate = delegate
        self._client = client or OllamaHTTPClient()
        self._model_id = model_id
        self._sampling_seed = sampling_seed
        self._source_candidates = source_ops.build_source_dependency_candidates(tool_catalog)
        self._output_candidates = output_ops.build_output_responsibility_candidates(tool_catalog)
        self._effect_candidates = prohibition_ops.build_effect_prohibition_candidates(
            self._output_candidates
        )
        self._work_instruction = WORK_PROMPT_PATH.read_text(encoding="utf-8").strip()
        self._authority_instruction = AUTHORITY_PROMPT_PATH.read_text(encoding="utf-8").strip()
        self._combined_output: dict[str, object] | None = None
        self.cached_response_count = 0
        self.additional_provider_call_count = 0
        self.events: list[dict[str, object]] = []

    @property
    def binding(self) -> dict[str, object]:
        return {
            "candidate_id": "ru-atomic-semantic-authority-v2b",
            "candidate_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "work_prompt_sha256": _sha256_text(self._work_instruction),
            "authority_prompt_sha256": _sha256_text(self._authority_instruction),
            "work_schema_version": "evaluation-requested-work-ref-v1",
            "authority_schema_version": "evaluation-atomic-request-semantics-v2b",
        }

    def reset_case(self) -> None:
        self._combined_output = None
        self.cached_response_count = 0
        self.additional_provider_call_count = 0
        self.events.clear()

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        if prompt_ref.prompt_id == "request_understanding.identify_requested_work":
            self._combined_output = None
            return self._infer_requested_work(
                requested_mode=requested_mode,
                prompt_ref=prompt_ref,
                input_projection=input_projection,
            )
        if prompt_ref.prompt_id == "request_understanding.identify_goal":
            return self._infer_semantic_authority(
                requested_mode=requested_mode,
                prompt_ref=prompt_ref,
                input_projection=input_projection,
            )
        cached_field = {
            "request_understanding.identify_effect_prohibitions": "effect_prohibitions",
            "request_understanding.identify_source_dependencies": "source_dependencies",
            "request_understanding.identify_output_responsibilities": "output_responsibilities",
        }.get(prompt_ref.prompt_id)
        if cached_field is not None and self._combined_output is not None:
            self.cached_response_count += 1
            return _cached_result(
                model_id=self._model_id,
                structured_output={cached_field: deepcopy(self._combined_output[cached_field])},
            )
        return self._delegate.infer(
            requested_mode,
            prompt_ref,
            input_projection,
            output_schema_ref,
        )

    def _infer_requested_work(
        self,
        *,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
    ) -> StructuredInferenceResultV1:
        user_request = input_projection.get("user_request")
        if not isinstance(user_request, str) or not user_request:
            raise ValueError("candidate requested-work input requires user_request")
        tokens = _request_tokens(user_request)
        schema = _requested_work_ref_schema(tuple(cast(str, token["token_id"]) for token in tokens))
        candidate_input = {
            "user_request": user_request,
            "request_tokens": [
                {"token_id": token["token_id"], "text": token["text"]} for token in tokens
            ],
        }
        raw, result, provider_attempts = self._invoke_candidate(
            requested_mode=requested_mode,
            prompt_ref=replace(
                prompt_ref,
                prompt_id=_WORK_PROMPT_ID,
                prompt_version="atomic-authority-v2",
                content_hash=_sha256_text(self._work_instruction),
            ),
            prompt_input=candidate_input,
            schema=schema,
            instruction=self._work_instruction,
        )
        materialized = _materialize_requested_work(
            raw,
            user_request=user_request,
            tokens=tokens,
        )
        self.events.append(
            {
                "operation": "REQUESTED_WORK_REF",
                "attempt": _attempt(input_projection),
                "raw_output": deepcopy(raw),
                "materialized_output": deepcopy(materialized),
                "provider_attempts": provider_attempts,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
            }
        )
        return replace(result, structured_output=materialized)

    def _infer_semantic_authority(
        self,
        *,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
    ) -> StructuredInferenceResultV1:
        requested_work = input_projection.get("requested_work")
        if not isinstance(requested_work, Mapping):
            raise ValueError("candidate semantic authority requires requested_work")
        raw_units = requested_work.get("work_units")
        if not isinstance(raw_units, Sequence) or isinstance(raw_units, (str, bytes)):
            raise ValueError("candidate semantic authority requires WorkUnits")
        work_unit_ids = tuple(
            str(unit["unit_id"])
            for unit in raw_units
            if isinstance(unit, Mapping) and isinstance(unit.get("unit_id"), str)
        )
        if not work_unit_ids or len(work_unit_ids) != len(raw_units):
            raise ValueError("candidate semantic authority has invalid WorkUnits")
        schema = _atomic_semantic_schema(
            work_unit_ids=work_unit_ids,
            source_candidates=self._source_candidates,
            output_candidates=self._output_candidates,
            effect_candidates=self._effect_candidates,
        )
        candidate_input = {
            **input_projection,
            "source_candidates": deepcopy(self._source_candidates),
            "output_candidates": deepcopy(self._output_candidates),
            "effect_candidates": deepcopy(self._effect_candidates),
        }
        raw, result, provider_attempts = self._invoke_candidate(
            requested_mode=requested_mode,
            prompt_ref=replace(
                prompt_ref,
                prompt_id=_AUTHORITY_PROMPT_ID,
                prompt_version="atomic-authority-v2",
                content_hash=_sha256_text(self._authority_instruction),
            ),
            prompt_input=candidate_input,
            schema=schema,
            instruction=self._authority_instruction,
        )
        expanded = _expand_atomic_semantics(
            raw,
            work_unit_ids=work_unit_ids,
            source_candidates=self._source_candidates,
            effect_candidates=self._effect_candidates,
        )
        self._combined_output = expanded
        goal_output = {
            field: deepcopy(raw[field])
            for field in (
                "goal",
                "completion_conditions",
                "constraints",
                "analysis_requirement",
            )
        }
        self.events.append(
            {
                "operation": "ATOMIC_SEMANTIC_AUTHORITY",
                "attempt": _attempt(input_projection),
                "raw_output": deepcopy(raw),
                "expanded_owner_outputs": deepcopy(expanded),
                "projected_goal_output": deepcopy(goal_output),
                "provider_attempts": provider_attempts,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
            }
        )
        return replace(result, structured_output=goal_output)

    def _invoke_candidate(
        self,
        *,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        schema: OutputSchemaDefinition,
        instruction: str,
    ) -> tuple[dict[str, object], StructuredInferenceResultV1, list[dict[str, object]]]:
        if requested_mode not in {"AUTO", "LOCAL_GPU"}:
            raise ValueError("evaluation candidate requires local model mode")
        attempts: list[dict[str, object]] = []
        response = self._client.invoke_structured(
            endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
            model_id=self._model_id,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            output_schema=schema,
            timeout_seconds=180,
            instruction_text=instruction,
            sampling_temperature=0.0,
            sampling_seed=self._sampling_seed,
        )
        raw = json.loads(cast(str, response.content))
        errors = validate_output_schema(raw, schema.json_schema)
        attempts.append(
            {
                "attempt": "FIRST",
                "structured_output": deepcopy(raw),
                "schema_errors": list(errors),
                "input_tokens": response.input_tokens or 0,
                "output_tokens": response.output_tokens or 0,
                "latency_ms": response.latency_ms,
            }
        )
        input_tokens = response.input_tokens or 0
        output_tokens = response.output_tokens or 0
        latency_ms = response.latency_ms
        if errors:
            self.additional_provider_call_count += 1
            repair_input = {
                "base_projection": deepcopy(prompt_input),
                "candidate_output": deepcopy(raw),
                "schema_errors": list(errors),
            }
            response = self._client.invoke_structured(
                endpoint=OLLAMA_FIXED_LOOPBACK_ENDPOINT,
                model_id=self._model_id,
                prompt_ref=prompt_ref,
                prompt_input=repair_input,
                output_schema=schema,
                timeout_seconds=180,
                instruction_text=(
                    instruction + "\n\n이전 출력의 JSON Schema 오류만 수정한다. 원래 요청 의미를 "
                    "새로 해석하거나 삭제하지 말고 지정된 schema 객체 하나만 반환한다."
                ),
                sampling_temperature=0.0,
                sampling_seed=self._sampling_seed,
            )
            raw = json.loads(cast(str, response.content))
            errors = validate_output_schema(raw, schema.json_schema)
            attempts.append(
                {
                    "attempt": "SCHEMA_REPAIR",
                    "structured_output": deepcopy(raw),
                    "schema_errors": list(errors),
                    "input_tokens": response.input_tokens or 0,
                    "output_tokens": response.output_tokens or 0,
                    "latency_ms": response.latency_ms,
                }
            )
            input_tokens += response.input_tokens or 0
            output_tokens += response.output_tokens or 0
            latency_ms += response.latency_ms
        if errors:
            raise ValueError(f"candidate structured output is invalid: {'; '.join(errors)}")
        result = StructuredInferenceResultV1(
            schema_version=1,
            structured_output=cast(dict[str, object], raw),
            provider="OLLAMA",
            model=response.model,
            actual_runtime="LOCAL_GPU",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            fallback_reason=None,
        )
        return cast(dict[str, object], raw), result, attempts


class GoalOutputAuthorityCandidate(AtomicSemanticAuthorityCandidate):
    """Keep specialist Source/prohibition owners and remove Goal -> Output reinterpretation."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._goal_output_instruction = GOAL_OUTPUT_PROMPT_PATH.read_text(encoding="utf-8").strip()
        self._goal_output: dict[str, object] | None = None

    @property
    def binding(self) -> dict[str, object]:
        return {
            "candidate_id": "ru-goal-output-authority-v3",
            "candidate_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "work_prompt_sha256": _sha256_text(self._work_instruction),
            "goal_output_prompt_sha256": _sha256_text(self._goal_output_instruction),
            "work_schema_version": "evaluation-requested-work-ref-v1",
            "goal_output_schema_version": "evaluation-goal-output-authority-v3",
        }

    @property
    def _goal_output_prompt_version(self) -> str:
        return "goal-output-authority-v3"

    def reset_case(self) -> None:
        super().reset_case()
        self._goal_output = None

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        if prompt_ref.prompt_id == "request_understanding.identify_requested_work":
            self._goal_output = None
            return self._infer_requested_work(
                requested_mode=requested_mode,
                prompt_ref=prompt_ref,
                input_projection=input_projection,
            )
        if prompt_ref.prompt_id == "request_understanding.identify_goal":
            return self._infer_goal_output_authority(
                requested_mode=requested_mode,
                prompt_ref=prompt_ref,
                input_projection=input_projection,
            )
        if (
            prompt_ref.prompt_id == "request_understanding.identify_output_responsibilities"
            and self._goal_output is not None
        ):
            self.cached_response_count += 1
            return _cached_result(
                model_id=self._model_id,
                structured_output={
                    "output_responsibilities": deepcopy(self._goal_output["requested_outputs"])
                },
            )
        return self._delegate.infer(
            requested_mode,
            prompt_ref,
            input_projection,
            output_schema_ref,
        )

    def _infer_goal_output_authority(
        self,
        *,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
    ) -> StructuredInferenceResultV1:
        work_unit_ids = _work_unit_ids(input_projection)
        schema = self._build_goal_output_schema(
            work_unit_ids=work_unit_ids,
            output_candidates=self._output_candidates,
        )
        candidate_input = {
            **input_projection,
            "output_candidates": deepcopy(self._output_candidates),
        }
        raw, result, provider_attempts = self._invoke_candidate(
            requested_mode=requested_mode,
            prompt_ref=replace(
                prompt_ref,
                prompt_id=_GOAL_OUTPUT_PROMPT_ID,
                prompt_version=self._goal_output_prompt_version,
                content_hash=_sha256_text(self._goal_output_instruction),
            ),
            prompt_input=candidate_input,
            schema=schema,
            instruction=self._goal_output_instruction,
        )
        self._goal_output = raw
        goal_output = {
            field: deepcopy(raw[field])
            for field in (
                "goal",
                "completion_conditions",
                "constraints",
                "analysis_requirement",
            )
        }
        self.events.append(
            {
                "operation": "GOAL_OUTPUT_AUTHORITY",
                "attempt": _attempt(input_projection),
                "raw_output": deepcopy(raw),
                "projected_goal_output": deepcopy(goal_output),
                "cached_output_responsibilities": deepcopy(raw["requested_outputs"]),
                "provider_attempts": provider_attempts,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
            }
        )
        return replace(result, structured_output=goal_output)

    def _build_goal_output_schema(
        self,
        *,
        work_unit_ids: Sequence[str],
        output_candidates: Sequence[Mapping[str, object]],
    ) -> OutputSchemaDefinition:
        return _goal_output_semantic_schema(
            work_unit_ids=work_unit_ids,
            output_candidates=output_candidates,
        )


class GoalOutputModalityAuthorityCandidate(GoalOutputAuthorityCandidate):
    """Make answer-vs-external-change an explicit coherent model decision."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._goal_output_instruction = GOAL_OUTPUT_MODALITY_PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip()

    @property
    def binding(self) -> dict[str, object]:
        return {
            "candidate_id": "ru-goal-output-modality-authority-v4",
            "candidate_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "work_prompt_sha256": _sha256_text(self._work_instruction),
            "goal_output_prompt_sha256": _sha256_text(self._goal_output_instruction),
            "work_schema_version": "evaluation-requested-work-ref-v1",
            "goal_output_schema_version": ("evaluation-goal-output-modality-authority-v4"),
        }

    @property
    def _goal_output_prompt_version(self) -> str:
        return "goal-output-modality-authority-v4"

    def _build_goal_output_schema(
        self,
        *,
        work_unit_ids: Sequence[str],
        output_candidates: Sequence[Mapping[str, object]],
    ) -> OutputSchemaDefinition:
        return _goal_output_modality_schema(
            work_unit_ids=work_unit_ids,
            output_candidates=output_candidates,
        )


class GoalResultModeFirstCandidate(AtomicSemanticAuthorityCandidate):
    """Decide user result modality before Registry output choices are visible."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._goal_result_mode_instruction = GOAL_RESULT_MODE_PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip()
        self._external_output_instruction = EXTERNAL_OUTPUT_PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip()
        self._goal_result_mode: dict[str, object] | None = None

    @property
    def binding(self) -> dict[str, object]:
        return {
            "candidate_id": "ru-result-mode-first-v5",
            "candidate_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "work_prompt_sha256": _sha256_text(self._work_instruction),
            "goal_result_mode_prompt_sha256": _sha256_text(self._goal_result_mode_instruction),
            "external_output_prompt_sha256": _sha256_text(self._external_output_instruction),
            "work_schema_version": "evaluation-requested-work-ref-v1",
            "goal_result_mode_schema_version": "evaluation-goal-result-mode-v5",
            "output_schema_version": "product-request-output-responsibility-v2",
        }

    def reset_case(self) -> None:
        super().reset_case()
        self._goal_result_mode = None

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        if prompt_ref.prompt_id == "request_understanding.identify_requested_work":
            self._goal_result_mode = None
            return self._infer_requested_work(
                requested_mode=requested_mode,
                prompt_ref=prompt_ref,
                input_projection=input_projection,
            )
        if prompt_ref.prompt_id == "request_understanding.identify_goal":
            return self._infer_goal_result_mode(
                requested_mode=requested_mode,
                prompt_ref=prompt_ref,
                input_projection=input_projection,
            )
        if prompt_ref.prompt_id == "request_understanding.identify_output_responsibilities":
            if self._goal_result_mode is None:
                raise ValueError("goal result mode must precede output selection")
            if self._goal_result_mode["requested_result_mode"] == "ANSWER_ONLY":
                self.cached_response_count += 1
                return _cached_result(
                    model_id=self._model_id,
                    structured_output={"output_responsibilities": []},
                )
            return self._infer_external_outputs(
                requested_mode=requested_mode,
                prompt_ref=prompt_ref,
                input_projection=input_projection,
                output_schema_ref=output_schema_ref,
            )
        return self._delegate.infer(
            requested_mode,
            prompt_ref,
            input_projection,
            output_schema_ref,
        )

    def _infer_goal_result_mode(
        self,
        *,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
    ) -> StructuredInferenceResultV1:
        schema = _goal_result_mode_schema(_work_unit_ids(input_projection))
        raw, result, provider_attempts = self._invoke_candidate(
            requested_mode=requested_mode,
            prompt_ref=replace(
                prompt_ref,
                prompt_id=_GOAL_RESULT_MODE_PROMPT_ID,
                prompt_version="result-mode-first-v5",
                content_hash=_sha256_text(self._goal_result_mode_instruction),
            ),
            prompt_input=input_projection,
            schema=schema,
            instruction=self._goal_result_mode_instruction,
        )
        self._goal_result_mode = raw
        goal_output = {
            field: deepcopy(raw[field])
            for field in (
                "goal",
                "completion_conditions",
                "constraints",
                "analysis_requirement",
            )
        }
        self.events.append(
            {
                "operation": "GOAL_RESULT_MODE",
                "attempt": _attempt(input_projection),
                "raw_output": deepcopy(raw),
                "projected_goal_output": deepcopy(goal_output),
                "provider_attempts": provider_attempts,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
            }
        )
        return replace(result, structured_output=goal_output)

    def _infer_external_outputs(
        self,
        *,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        raw, result, provider_attempts = self._invoke_candidate(
            requested_mode=requested_mode,
            prompt_ref=replace(
                prompt_ref,
                prompt_id=_EXTERNAL_OUTPUT_PROMPT_ID,
                prompt_version="result-mode-first-v5",
                content_hash=_sha256_text(self._external_output_instruction),
            ),
            prompt_input=input_projection,
            schema=output_schema_ref,
            instruction=self._external_output_instruction,
        )
        self.events.append(
            {
                "operation": "EXTERNAL_OUTPUT_SELECTION",
                "attempt": _attempt(input_projection),
                "raw_output": deepcopy(raw),
                "provider_attempts": provider_attempts,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
            }
        )
        return result


def _request_tokens(user_request: str) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "token_id": f"t{index:03d}",
            "text": match.group(0),
            "start_offset": match.start(),
            "end_offset": match.end(),
        }
        for index, match in enumerate(_TOKEN_PATTERN.finditer(user_request), start=1)
    )


def _requested_work_ref_schema(token_ids: Sequence[str]) -> OutputSchemaDefinition:
    if not token_ids:
        raise ValueError("requested-work ref schema requires request tokens")
    range_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["start_token_id", "end_token_id"],
        "properties": {
            "start_token_id": {"enum": list(token_ids)},
            "end_token_id": {"enum": list(token_ids)},
        },
    }
    return OutputSchemaDefinition(
        schema_version="evaluation-requested-work-ref-v1",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["work_units"],
            "properties": {
                "work_units": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["ranges"],
                        "properties": {
                            "ranges": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": range_schema,
                            }
                        },
                    },
                }
            },
        },
    )


def _materialize_requested_work(
    value: Mapping[str, object],
    *,
    user_request: str,
    tokens: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    by_id = {str(token["token_id"]): token for token in tokens}
    raw_units = cast(Sequence[Mapping[str, object]], value["work_units"])
    occupied: list[tuple[int, int]] = []
    materialized_units: list[dict[str, object]] = []
    for unit_index, unit in enumerate(raw_units):
        spans: list[str] = []
        for range_index, raw_range in enumerate(
            cast(Sequence[Mapping[str, object]], unit["ranges"])
        ):
            start_token = by_id[str(raw_range["start_token_id"])]
            end_token = by_id[str(raw_range["end_token_id"])]
            start = cast(int, start_token["start_offset"])
            end = cast(int, end_token["end_offset"])
            if end <= start:
                raise ValueError(
                    "requested-work token range is reversed: "
                    f"work_units[{unit_index}].ranges[{range_index}]"
                )
            if any(start < used_end and used_start < end for used_start, used_end in occupied):
                raise ValueError("requested-work token ranges overlap across WorkUnits")
            occupied.append((start, end))
            spans.append(user_request[start:end])
        materialized_units.append({"request_spans": spans})
    return {"schema_version": 1, "work_units": materialized_units}


def _work_unit_ids(input_projection: Mapping[str, object]) -> tuple[str, ...]:
    requested_work = input_projection.get("requested_work")
    if not isinstance(requested_work, Mapping):
        raise ValueError("candidate authority requires requested_work")
    raw_units = requested_work.get("work_units")
    if not isinstance(raw_units, Sequence) or isinstance(raw_units, (str, bytes)):
        raise ValueError("candidate authority requires WorkUnits")
    work_unit_ids = tuple(
        str(unit["unit_id"])
        for unit in raw_units
        if isinstance(unit, Mapping) and isinstance(unit.get("unit_id"), str)
    )
    if not work_unit_ids or len(work_unit_ids) != len(raw_units):
        raise ValueError("candidate authority has invalid WorkUnits")
    return work_unit_ids


def _goal_output_semantic_schema(
    *,
    work_unit_ids: Sequence[str],
    output_candidates: Sequence[Mapping[str, object]],
) -> OutputSchemaDefinition:
    goal = deepcopy(goal_schema_ops.identify_goal_output_schema(work_unit_ids).json_schema)
    output = output_ops.build_output_responsibility_output_schema(
        cast(Any, output_candidates),
        work_unit_ids=work_unit_ids,
    ).json_schema
    goal_properties = cast(dict[str, object], goal["properties"])
    goal_required = cast(list[str], goal["required"])
    output_properties = cast(dict[str, object], output["properties"])
    goal_properties["requested_outputs"] = deepcopy(output_properties["output_responsibilities"])
    goal_required.append("requested_outputs")
    return OutputSchemaDefinition(
        schema_version="evaluation-goal-output-authority-v3",
        json_schema=goal,
    )


def _goal_result_mode_schema(
    work_unit_ids: Sequence[str],
) -> OutputSchemaDefinition:
    schema = deepcopy(goal_schema_ops.identify_goal_output_schema(work_unit_ids).json_schema)
    properties = cast(dict[str, object], schema["properties"])
    required = cast(list[str], schema["required"])
    properties["requested_result_mode"] = {"enum": ["ANSWER_ONLY", "EXTERNAL_CHANGE"]}
    required.append("requested_result_mode")
    return OutputSchemaDefinition(
        schema_version="evaluation-goal-result-mode-v5",
        json_schema=schema,
    )


def _goal_output_modality_schema(
    *,
    work_unit_ids: Sequence[str],
    output_candidates: Sequence[Mapping[str, object]],
) -> OutputSchemaDefinition:
    base = _goal_output_semantic_schema(
        work_unit_ids=work_unit_ids,
        output_candidates=output_candidates,
    )
    schema = deepcopy(base.json_schema)
    properties = cast(dict[str, object], schema["properties"])
    required = cast(list[str], schema["required"])
    properties["requested_result_mode"] = {"enum": ["ANSWER_ONLY", "EXTERNAL_CHANGE"]}
    required.append("requested_result_mode")
    schema["allOf"] = [
        {
            "if": {
                "properties": {"requested_result_mode": {"const": "ANSWER_ONLY"}},
                "required": ["requested_result_mode"],
            },
            "then": {"properties": {"requested_outputs": {"maxItems": 0}}},
        },
        {
            "if": {
                "properties": {"requested_result_mode": {"const": "EXTERNAL_CHANGE"}},
                "required": ["requested_result_mode"],
            },
            "then": {"properties": {"requested_outputs": {"minItems": 1}}},
        },
    ]
    return OutputSchemaDefinition(
        schema_version="evaluation-goal-output-modality-authority-v4",
        json_schema=schema,
    )


def _atomic_semantic_schema(
    *,
    work_unit_ids: Sequence[str],
    source_candidates: Sequence[Mapping[str, object]],
    output_candidates: Sequence[Mapping[str, object]],
    effect_candidates: Sequence[Mapping[str, object]],
) -> OutputSchemaDefinition:
    goal = deepcopy(goal_schema_ops.identify_goal_output_schema(work_unit_ids).json_schema)
    root = cast(dict[str, object], goal)
    properties = cast(dict[str, object], root["properties"])
    required = cast(list[str], root["required"])
    source_types = [str(candidate["resource_type"]) for candidate in source_candidates]
    output_types = [str(candidate["resource_type"]) for candidate in output_candidates]
    effect_values = [str(candidate["effect"]) for candidate in effect_candidates]
    binding = {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": {"enum": list(work_unit_ids)},
    }
    properties["required_sources"] = {
        "type": "array",
        "maxItems": len(source_types),
        "uniqueItems": True,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "resource_type",
                "required_information",
                "target_scope",
                "work_unit_ids",
            ],
            "properties": {
                "resource_type": {"enum": source_types},
                "required_information": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "target_scope": {"enum": ["SINGULAR", "CRITERIA"]},
                "work_unit_ids": deepcopy(binding),
            },
            "allOf": [
                {
                    "if": {
                        "properties": {"resource_type": {"const": str(candidate["resource_type"])}},
                        "required": ["resource_type"],
                    },
                    "then": {
                        "properties": {
                            "required_information": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": min(
                                    8,
                                    len(
                                        cast(
                                            Sequence[str],
                                            candidate["owned_fact_kinds"],
                                        )
                                    ),
                                ),
                                "uniqueItems": True,
                                "items": {
                                    "enum": list(
                                        cast(
                                            Sequence[str],
                                            candidate["owned_fact_kinds"],
                                        )
                                    )
                                },
                            }
                        }
                    },
                }
                for candidate in source_candidates
            ],
        },
        "allOf": [
            *[
                {
                    "contains": {
                        "type": "object",
                        "properties": {"resource_type": {"const": resource_type}},
                        "required": ["resource_type"],
                    },
                    "minContains": 0,
                    "maxContains": 1,
                }
                for resource_type in source_types
            ],
        ],
    }
    allowed_effects = {
        str(candidate["resource_type"]): list(
            cast(Sequence[str], candidate["allowed_output_effects"])
        )
        for candidate in output_candidates
    }
    properties["requested_outputs"] = {
        "type": "array",
        "maxItems": len(output_types) * len(work_unit_ids),
        "uniqueItems": True,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["resource_type", "effect", "work_unit_ids"],
            "properties": {
                "resource_type": {"enum": output_types},
                "effect": {
                    "enum": sorted({item for values in allowed_effects.values() for item in values})
                },
                "work_unit_ids": deepcopy(binding),
            },
            "allOf": [
                {
                    "if": {
                        "properties": {"resource_type": {"const": resource_type}},
                        "required": ["resource_type"],
                    },
                    "then": {"properties": {"effect": {"enum": effects}}},
                }
                for resource_type, effects in allowed_effects.items()
            ],
        },
    }
    properties["explicit_prohibitions"] = {
        "type": "array",
        "maxItems": len(effect_values),
        "uniqueItems": True,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["effect", "work_unit_ids"],
            "properties": {
                "effect": {"enum": effect_values},
                "work_unit_ids": deepcopy(binding),
            },
        },
        "allOf": [
            {
                "contains": {
                    "type": "object",
                    "properties": {"effect": {"const": effect}},
                    "required": ["effect"],
                },
                "minContains": 0,
                "maxContains": 1,
            }
            for effect in effect_values
        ],
    }
    required.extend(["required_sources", "requested_outputs", "explicit_prohibitions"])
    return OutputSchemaDefinition(
        schema_version="evaluation-atomic-request-semantics-v2b",
        json_schema=root,
    )


def _expand_atomic_semantics(
    value: Mapping[str, object],
    *,
    work_unit_ids: Sequence[str],
    source_candidates: Sequence[Mapping[str, object]],
    effect_candidates: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    selected_sources = {
        str(item["resource_type"]): item
        for item in cast(Sequence[Mapping[str, object]], value["required_sources"])
    }
    source_dependencies: list[dict[str, object]] = []
    for candidate in source_candidates:
        resource_type = str(candidate["resource_type"])
        selected = selected_sources.get(resource_type)
        source_dependencies.append(
            {"resource_type": resource_type, "dependency": "SOURCE_NOT_REQUIRED"}
            if selected is None
            else {
                "resource_type": resource_type,
                "dependency": "SOURCE_REQUIRED",
                "required_information": deepcopy(selected["required_information"]),
                "target_scope": selected["target_scope"],
                "work_unit_ids": deepcopy(selected["work_unit_ids"]),
            }
        )
    prohibited = {
        str(item["effect"]): list(cast(Sequence[str], item["work_unit_ids"]))
        for item in cast(Sequence[Mapping[str, object]], value["explicit_prohibitions"])
    }
    effect_prohibitions = [
        {
            "effect": str(candidate["effect"]),
            "prohibition": (
                "FORBIDDEN" if str(candidate["effect"]) in prohibited else "NOT_FORBIDDEN"
            ),
            "work_unit_ids": prohibited.get(str(candidate["effect"]), list(work_unit_ids)),
        }
        for candidate in effect_candidates
    ]
    return {
        "source_dependencies": source_dependencies,
        "output_responsibilities": deepcopy(value["requested_outputs"]),
        "effect_prohibitions": effect_prohibitions,
    }


def _cached_result(
    *, model_id: str, structured_output: dict[str, object]
) -> StructuredInferenceResultV1:
    return StructuredInferenceResultV1(
        schema_version=1,
        structured_output=structured_output,
        provider="EVALUATION_CACHE",
        model=model_id,
        actual_runtime="LOCAL_GPU",
        input_tokens=0,
        output_tokens=0,
        latency_ms=0,
        fallback_reason=None,
    )


def _attempt(input_projection: Mapping[str, object]) -> str:
    return "REVISION" if "failure_record" in input_projection else "FIRST"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "AUTHORITY_PROMPT_PATH",
    "AtomicSemanticAuthorityCandidate",
    "EXTERNAL_OUTPUT_PROMPT_PATH",
    "GOAL_RESULT_MODE_PROMPT_PATH",
    "GOAL_OUTPUT_MODALITY_PROMPT_PATH",
    "GOAL_OUTPUT_PROMPT_PATH",
    "GoalOutputAuthorityCandidate",
    "GoalOutputModalityAuthorityCandidate",
    "GoalResultModeFirstCandidate",
    "WORK_PROMPT_PATH",
]
