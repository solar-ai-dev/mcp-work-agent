"""Inactive Review request-semantics contract; not a Product routing authority.

The extra finding and schema-2 projection are evaluation-only. Production Review
aggregation, WorkflowSignalV1, RU revision ownership, and Approval are unchanged.
The caller supplies current Plan/ID authority and an explicit pre-publication
gate; this module neither loads Domain state nor grants execution permission.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
    work_unit_id_schema,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewDimensionIdV1,
    review_inspector_output_schema,
    validate_review_inspector_result,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

DIMENSION: ReviewDimensionIdV1 = "review.inspect_goal_and_evidence"
REQUEST_SEMANTICS_ISSUE = "REQUEST_SEMANTICS_ISSUE"
SEMANTIC_FIELD_PATHS = (
    "$.goal",
    "$.completion_conditions",
    "$.constraints",
    "$.resource_responsibilities.source_reads",
    "$.resource_responsibilities.outputs",
    "$.effect_prohibitions",
)


@dataclass(frozen=True)
class ValidatedFinding:
    """Invocation-local validation receipt, never persisted Product State.

    Canonical JSON snapshots prevent later mutation through caller-owned mappings.
    Construct receipts with ``validate_review_candidate``, not from LLM output.
    """

    _finding_json: str
    _intent_json: str
    _original_request: str
    _plan_ref_json: str

    @property
    def finding(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self._finding_json))


def build_review_output_schema(work_unit_ids: Sequence[str]) -> OutputSchemaDefinition:
    """Add one disjoint variant without altering any ordinary finding variant."""
    schema = deepcopy(review_inspector_output_schema(DIMENSION).json_schema)
    findings = cast(dict[str, Any], schema["properties"])["findings"]
    ordinary = deepcopy(findings["items"])
    request_issue = deepcopy(ordinary)
    request_issue["required"].extend(["work_unit_ids", "semantic_field_paths"])
    request_issue["properties"].update(
        {
            "finding_kind": {"const": REQUEST_SEMANTICS_ISSUE},
            "work_unit_ids": work_unit_id_schema(work_unit_ids),
            "semantic_field_paths": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"enum": list(SEMANTIC_FIELD_PATHS)},
            },
        }
    )
    findings["items"] = {"oneOf": [ordinary, request_issue]}
    return OutputSchemaDefinition(
        schema_version="evaluation-review-request-semantics-result-v2",
        json_schema=schema,
    )


def validate_review_candidate(
    value: object,
    *,
    current_intent: Mapping[str, Any],
    user_request: str,
    current_plan_ref: Mapping[str, Any],
    known_action_ids: Sequence[str] = (),
    known_route_ids: Sequence[str] = (),
    known_evidence_ids: Sequence[str] = (),
    pre_publication: bool,
) -> tuple[ValidatedFinding, ...]:
    """Check shape, current references and provenance, not business correctness.

    Neither free-form code/description nor an Evidence ID can reclassify a finding.
    Schema-valid REQUEST_SEMANTICS_ISSUE remains a model allegation, not a corrected
    RequestIntent or an authorization to invoke a Product back-edge.
    """
    _require_pre_publication(pre_publication)
    work = _validate_context(current_intent, user_request, current_plan_ref)
    unit_ids = [unit["unit_id"] for unit in work["work_units"]]
    errors = validate_output_schema(value, build_review_output_schema(unit_ids).json_schema)
    if errors:
        raise ValueError("Review candidate schema is invalid: " + "; ".join(errors))
    root = cast(dict[str, Any], value)
    known_refs = {
        "affected_action_ids": _closed_ids(known_action_ids, "action"),
        "affected_route_ids": _closed_ids(known_route_ids, "route"),
        "evidence_refs": _closed_ids(known_evidence_ids, "evidence"),
    }
    validated: list[ValidatedFinding] = []
    for finding in root["findings"]:
        for field, known in known_refs.items():
            if not set(finding[field]).issubset(known):
                raise ValueError(f"Review candidate {field} contains unknown current IDs")
        if finding["finding_kind"] == REQUEST_SEMANTICS_ISSUE:
            for path in finding["semantic_field_paths"]:
                _semantic_value(current_intent, path)
        else:
            validate_review_inspector_result(
                {"schema_version": 1, "dimension": DIMENSION, "findings": [finding]},
                expected_dimension=DIMENSION,
            )
        validated.append(
            ValidatedFinding(
                _finding_json=_snapshot(finding),
                _intent_json=_snapshot(current_intent),
                _original_request=user_request,
                _plan_ref_json=_snapshot(current_plan_ref),
            )
        )
    return tuple(validated)


def build_request_reconsideration_projection(
    validated_finding: ValidatedFinding,
    current_intent: Mapping[str, Any],
    original_request: str,
    current_plan_ref: Mapping[str, Any],
    *,
    pre_publication: bool,
) -> dict[str, Any] | None:
    """Copy current source-bound observations; ordinary findings return ``None``.

    The schema-2 observation distinguishes user provenance from Provider Evidence.
    Selected semantic paths retain their exact current values (including item Work
    bindings); they are not rewritten into a proposed interpretation or local output.
    This signal alone must not be passed to Production WorkflowSignalV1 aggregation.
    """
    _require_pre_publication(pre_publication)
    if not isinstance(validated_finding, ValidatedFinding):
        raise ValueError("Review projection requires a validated finding receipt")
    work = _validate_context(current_intent, original_request, current_plan_ref)
    if (
        validated_finding._intent_json != _snapshot(current_intent)
        or validated_finding._original_request != original_request
        or validated_finding._plan_ref_json != _snapshot(current_plan_ref)
    ):
        raise ValueError("Review finding is stale for current Intent, request or Plan")
    finding = validated_finding.finding
    if finding["finding_kind"] != REQUEST_SEMANTICS_ISSUE:
        return None
    applicable = set(finding["work_unit_ids"])
    observation = {
        "origin": "USER_REQUEST_PROVENANCE",
        **finding,
        "request_work_units": [
            deepcopy(unit) for unit in work["work_units"] if unit["unit_id"] in applicable
        ],
        "semantic_values": {
            path: _semantic_value(current_intent, path) for path in finding["semantic_field_paths"]
        },
    }
    return {
        "schema_version": 2,
        "kind": "REQUEST_RECONSIDERATION_REQUIRED",
        "reason_codes": [finding["code"]],
        "based_on_request_intent": deepcopy(current_intent["meta"]),
        "based_on_planning_result": deepcopy(dict(current_plan_ref)),
        "observations": [observation],
    }


def _validate_context(
    intent: Mapping[str, Any], user_request: str, plan_ref: Mapping[str, Any]
) -> dict[str, Any]:
    if type(intent.get("schema_version")) is not int or intent["schema_version"] != 3:
        raise ValueError("Review candidate requires current RequestIntentV3")
    if not isinstance(user_request, str) or not user_request:
        raise ValueError("Review candidate requires the original current request")
    meta = intent.get("meta")
    if not isinstance(meta, Mapping) or set(meta) != {"artifact_id", "revision", "based_on"}:
        raise ValueError("Review candidate requires exact Intent metadata")
    _validate_ref({"artifact_id": meta["artifact_id"], "revision": meta["revision"]})
    if not isinstance(meta["based_on"], list):
        raise ValueError("Intent metadata based_on must be a list")
    for ref in meta["based_on"]:
        _validate_ref(ref)
    _validate_ref(plan_ref)
    return cast(
        dict[str, Any],
        validate_requested_work_definition(intent.get("requested_work"), user_request=user_request),
    )


def _validate_ref(value: object) -> None:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"artifact_id", "revision"}
        or not isinstance(value["artifact_id"], str)
        or not value["artifact_id"].strip()
        or type(value["revision"]) is not int
        or value["revision"] < 1
    ):
        raise ValueError("Review candidate requires an exact current artifact reference")


def _semantic_value(intent: Mapping[str, Any], path: str) -> Any:
    if path not in SEMANTIC_FIELD_PATHS:
        raise ValueError("Review candidate semantic field path is not allowed")
    value: Any = intent
    for part in path[2:].split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise ValueError("Review candidate semantic field does not exist in current Intent")
        value = value[part]
    return deepcopy(value)


def _closed_ids(values: Sequence[str], name: str) -> set[str]:
    if isinstance(values, (str, bytes)) or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise ValueError(f"Known {name} IDs must be a sequence of non-empty strings")
    if len(set(values)) != len(values):
        raise ValueError(f"Known {name} IDs must be unique")
    return set(values)


def _snapshot(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _require_pre_publication(value: bool) -> None:
    if value is not True:
        raise ValueError("Review request reconsideration is evaluation pre-publication only")


__all__ = [
    "DIMENSION",
    "REQUEST_SEMANTICS_ISSUE",
    "SEMANTIC_FIELD_PATHS",
    "ValidatedFinding",
    "build_request_reconsideration_projection",
    "build_review_output_schema",
    "validate_review_candidate",
]
