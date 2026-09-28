"""Inactive evaluation candidate: v4 semantics with modality-first schema order."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import cast

from evaluation.request_semantic_authority_candidate import (
    GoalOutputModalityAuthorityCandidate,
    _goal_output_modality_schema,
)

from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

SCHEMA_VERSION = "evaluation-goal-output-ordered-authority-v11"
_LEADING_FIELDS = ("requested_result_mode", "requested_outputs")


def ordered_authority_schema(
    *,
    work_unit_ids: Sequence[str],
    output_candidates: Sequence[Mapping[str, object]],
) -> OutputSchemaDefinition:
    """Preserve every v4 validation rule; change only root generation field order."""
    base = _goal_output_modality_schema(
        work_unit_ids=work_unit_ids,
        output_candidates=output_candidates,
    )
    schema = cast(dict[str, object], deepcopy(base.json_schema))
    properties = cast(dict[str, object], schema["properties"])
    required = cast(list[str], schema["required"])
    schema["properties"] = {
        field: properties[field]
        for field in (*_LEADING_FIELDS, *(key for key in properties if key not in _LEADING_FIELDS))
    }
    schema["required"] = [
        *_LEADING_FIELDS,
        *(field for field in required if field not in _LEADING_FIELDS),
    ]
    return OutputSchemaDefinition(schema_version=SCHEMA_VERSION, json_schema=schema)


class OrderedGoalOutputAuthorityCandidate(GoalOutputModalityAuthorityCandidate):
    """Reuse v4 input, Prompt, inference, projection, and downstream Output cache."""

    @property
    def binding(self) -> dict[str, object]:
        return {
            **super().binding,
            "candidate_id": "ru-goal-output-ordered-authority-v11",
            "ordering_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "goal_output_schema_version": SCHEMA_VERSION,
        }

    def _build_goal_output_schema(
        self,
        *,
        work_unit_ids: Sequence[str],
        output_candidates: Sequence[Mapping[str, object]],
    ) -> OutputSchemaDefinition:
        return ordered_authority_schema(
            work_unit_ids=work_unit_ids,
            output_candidates=output_candidates,
        )
