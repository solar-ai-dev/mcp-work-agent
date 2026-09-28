"""Inactive v21: retain v11 decisions, copying only Goal from the current request.

Completion conditions remain model-owned. Source already uses an extractive
request projection in Product; this candidate does not introduce that behavior.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, cast

from evaluation.request_semantic_authority_candidate import (
    _GOAL_OUTPUT_PROMPT_ID,
    _attempt,
    _work_unit_ids,
)
from scripts.ru_ordered_authority_candidate import (
    OrderedGoalOutputAuthorityCandidate,
    ordered_authority_schema,
)

from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1

SCHEMA_VERSION = "evaluation-request-grounded-goal-v21"
_PROMPT_REPLACEMENTS = (
    (
        "사용자 요청과 이미 확정된 WorkUnit을 바탕으로 목표와 사용자가 원하는 결과를 "
        "한 번에 판단한다.",
        "사용자 요청과 이미 확정된 WorkUnit을 바탕으로 완료 조건과 사용자가 원하는 결과를 "
        "한 번에 판단한다. goal은 실행기가 현재 user_request 원문을 그대로 전달하므로 "
        "생성하지 않는다.",
    ),
    (
        "- goal, completion_conditions, constraints, analysis_requirement, "
        "requested_result_mode와 requested_outputs는 같은 해석을 표현해야 한다.",
        "- completion_conditions, constraints, analysis_requirement, requested_result_mode와 "
        "requested_outputs는 같은 해석을 표현해야 한다.",
    ),
)


def request_grounded_goal_instruction(original: str) -> str:
    """Change only the two existing Goal-generation responsibilities."""
    for before, after in _PROMPT_REPLACEMENTS:
        if original.count(before) != 1:
            raise ValueError("v21 requires the unchanged v11 Goal-generation instruction")
        original = original.replace(before, after, 1)
    return original


def request_grounded_goal_schema(
    *,
    work_unit_ids: Sequence[str],
    output_candidates: Sequence[Mapping[str, object]],
) -> OutputSchemaDefinition:
    """Remove only Goal from the v11 generation schema, preserving field order."""
    base = ordered_authority_schema(
        work_unit_ids=work_unit_ids, output_candidates=output_candidates
    )
    schema = deepcopy(dict(base.json_schema))
    del cast(dict[str, object], schema["properties"])["goal"]
    cast(list[str], schema["required"]).remove("goal")
    return OutputSchemaDefinition(schema_version=SCHEMA_VERSION, json_schema=schema)


class RequestGroundedGoalCandidate(OrderedGoalOutputAuthorityCandidate):
    """Reuse v11 inference/cache without labeling deterministic Goal as raw output."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._baseline_goal_output_instruction = self._goal_output_instruction
        self._goal_output_instruction = request_grounded_goal_instruction(
            self._goal_output_instruction
        )

    @property
    def binding(self) -> dict[str, object]:
        return {
            **super().binding,
            "candidate_id": "ru-request-grounded-goal-v21",
            "goal_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "baseline_goal_output_prompt_sha256": hashlib.sha256(
                self._baseline_goal_output_instruction.encode("utf-8")
            ).hexdigest(),
            "goal_output_schema_version": SCHEMA_VERSION,
            "goal_authority": "EXACT_CURRENT_USER_REQUEST",
            "completion_conditions_authority": "UNCHANGED_MODEL_OWNER",
        }

    @property
    def _goal_output_prompt_version(self) -> str:
        return "request-grounded-goal-v21"

    def _build_goal_output_schema(
        self,
        *,
        work_unit_ids: Sequence[str],
        output_candidates: Sequence[Mapping[str, object]],
    ) -> OutputSchemaDefinition:
        return request_grounded_goal_schema(
            work_unit_ids=work_unit_ids, output_candidates=output_candidates
        )

    def _infer_goal_output_authority(
        self,
        *,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
    ) -> StructuredInferenceResultV1:
        request_text = input_projection.get("user_request")
        if not isinstance(request_text, str):
            raise ValueError("v21 requires the current user_request string")
        schema = self._build_goal_output_schema(
            work_unit_ids=_work_unit_ids(input_projection),
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
                content_hash=hashlib.sha256(
                    self._goal_output_instruction.encode("utf-8")
                ).hexdigest(),
            ),
            prompt_input=candidate_input,
            schema=schema,
            instruction=self._goal_output_instruction,
        )
        self._goal_output = deepcopy(raw)
        goal_output = {
            "goal": request_text,
            **{
                field: deepcopy(raw[field])
                for field in ("completion_conditions", "constraints", "analysis_requirement")
            },
        }
        self.events.append(
            {
                "operation": "GOAL_OUTPUT_AUTHORITY",
                "attempt": _attempt(input_projection),
                "raw_output": deepcopy(raw),
                "deterministic_projected_goal": request_text,
                "goal_projection_source": "user_request",
                "projected_goal_output": deepcopy(goal_output),
                "cached_output_responsibilities": deepcopy(raw["requested_outputs"]),
                "provider_attempts": provider_attempts,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
            }
        )
        return replace(result, structured_output=goal_output)
