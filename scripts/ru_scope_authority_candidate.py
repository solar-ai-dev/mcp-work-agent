"""Inactive v16: align existing Goal/Source-scope vocabulary, not semantic decisions."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from evaluation.request_semantic_authority_candidate import GoalOutputModalityAuthorityCandidate
from scripts.ru_source_scope_candidate import source_scope_candidate

from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

_ORIGINAL_SOURCE_BOUNDARY = "- Source, Tool, Query, 승인, 실행 순서는 판단하지 않는다."
_SCOPE_OWNER_BOUNDARY = (
    "- Source responsibility와 capability 선택, Tool, Query, 승인, 실행 순서는 판단하지 않는다."
)
SCOPE_FIELD_DESCRIPTION = (
    "제품이 지원하는 명시적 업무값 또는 Source 범위 제약을 보존한다. "
    "required_sources는 사용자가 명시한 배타적 Source category 허용 범위이며, "
    "단순히 필요한 Source 목록이 아니다. forbidden_sources는 Source category 전체의 "
    "조회 제외다. 선택 identity나 같은 category 안의 다른 객체·검색 범위 제한은 "
    "category 전체 제한으로 확대하지 않는다."
)
_ORIGINAL_ADDITIONAL_DESCRIPTION = "그 밖의 명시적 실행 값은 additional_constraints"
_SCOPE_ADDITIONAL_DESCRIPTION = "그 밖의 명시적 업무값과 Source 범위 제약은 additional_constraints"


def scope_authority_instruction(original: str) -> str:
    """Change the existing responsibility boundary once; fail on upstream drift."""
    if original.count(_ORIGINAL_SOURCE_BOUNDARY) != 1:
        raise ValueError("v16 requires exactly one unchanged v4 Source responsibility boundary")
    return original.replace(_ORIGINAL_SOURCE_BOUNDARY, _SCOPE_OWNER_BOUNDARY, 1)


def scope_constraints_description(original: str) -> str:
    """Align the existing Goal constraint description without adding a new rule."""
    if original.count(_ORIGINAL_ADDITIONAL_DESCRIPTION) != 1:
        raise ValueError(
            "v16 requires exactly one unchanged Goal additional-constraint description"
        )
    return original.replace(_ORIGINAL_ADDITIONAL_DESCRIPTION, _SCOPE_ADDITIONAL_DESCRIPTION, 1)


@contextmanager
def scope_authority_candidate() -> Iterator[None]:
    """Keep v14's complete shape and normalization, changing only a description.

    The caller keeps this context around inference and subsequent Goal validation,
    as for v14. No request, selected identity, or model output is interpreted here.
    """
    with source_scope_candidate():
        item = cast(dict[str, Any], goal_schema._ADDITIONAL_CONSTRAINT_LIST_SCHEMA["items"])
        field_schema = item["properties"]["field"]
        with patch.dict(field_schema, {"description": SCOPE_FIELD_DESCRIPTION}):
            yield


class ScopeAuthorityCandidate(GoalOutputModalityAuthorityCandidate):
    """Reuse v4 inference/handoff with one clarified Source ownership sentence."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._baseline_goal_output_instruction = self._goal_output_instruction
        self._goal_output_instruction = scope_authority_instruction(self._goal_output_instruction)
        original_constraints = cast(
            dict[str, Any], goal_schema.IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema
        )["properties"]["constraints"]["description"]
        self._scope_constraints_description = scope_constraints_description(original_constraints)

    @property
    def binding(self) -> dict[str, object]:
        return {
            **super().binding,
            "candidate_id": "ru-scope-authority-v16",
            "source_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "baseline_goal_output_prompt_sha256": hashlib.sha256(
                self._baseline_goal_output_instruction.encode("utf-8")
            ).hexdigest(),
            "scope_field_description_sha256": hashlib.sha256(
                SCOPE_FIELD_DESCRIPTION.encode("utf-8")
            ).hexdigest(),
            "scope_constraints_description_sha256": hashlib.sha256(
                self._scope_constraints_description.encode("utf-8")
            ).hexdigest(),
        }

    @property
    def _goal_output_prompt_version(self) -> str:
        return "scope-authority-v16"

    def _build_goal_output_schema(
        self,
        *,
        work_unit_ids: Sequence[str],
        output_candidates: Sequence[Mapping[str, object]],
    ) -> OutputSchemaDefinition:
        base = super()._build_goal_output_schema(
            work_unit_ids=work_unit_ids, output_candidates=output_candidates
        )
        candidate = deepcopy(dict(base.json_schema))
        constraints = cast(dict[str, Any], candidate["properties"])["constraints"]
        constraints["description"] = scope_constraints_description(constraints["description"])
        return replace(base, json_schema=candidate)
