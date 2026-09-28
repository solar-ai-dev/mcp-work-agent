"""Fixed synthetic Product Planning inputs; no model, Provider or Gold in the prompt."""

from __future__ import annotations

from contextlib import suppress
from copy import deepcopy
from typing import Any, Literal, cast

from scripts.ru_observation import object_hash

from google_work_agent.application.agents.planning.compose_answer import compose_answer
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerOutlineV1,
)
from google_work_agent.application.agents.planning.outline_answer import outline_answer
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    ResourceResponsibilitiesV1,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.agents.retrieval.project_task_calendar_source_snapshots import (
    task_calendar_source_snapshot,
)

REQUEST = "작업 A의 상태만 알려주고, 작업 B는 예정일만 알려줘."
GROUPS = ("PRODUCT_TASK_FIELD_FULL", "PRODUCT_TASK_FIELD_PARTIAL")
REFERENCE_TIME = "2026-09-29T09:00:00+09:00"


class _CapturedComposition(Exception):
    """Stop preparation at the actual semantic boundary, without supplying a fake answer."""


def build_cases() -> list[dict[str, Any]]:
    # Reuse the existing registry/freshness owner; this is not a second route implementation.
    from scripts.evaluate_registered_answer_choice import _synthetic_component_state

    responsibilities: ResourceResponsibilitiesV1 = {
        "source_reads": [
            {
                "resource_type": "TASK",
                "required_information": [field],
                "target_scope": "SINGULAR",
                "work_unit_ids": ["work-1"],
            }
            for field in ("status", "due")
        ],
        "outputs": [],
    }
    provenance: dict[Literal["USER_REQUEST", "CONFIRMATION_RESPONSE"], str] = {
        "USER_REQUEST": REQUEST
    }
    intent = validate_intent(
        {
            "schema_version": 3,
            "meta": {"artifact_id": "094-intent", "revision": 1, "based_on": []},
            "goal": "각 작업에 대해 요청한 정보를 안내한다.",
            "completion_conditions": ["확인된 작업 정보와 확인하지 못한 범위를 안내한다."],
            "constraints": request_goal_candidate_schema.derive_source_information_constraints(
                responsibilities
            ),
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
            "effect_prohibitions": [],
            "resource_responsibilities": responsibilities,
            "requested_work": {
                "work_units": [
                    {
                        "unit_id": "work-1",
                        "request_provenance": [
                            {
                                "source": "USER_REQUEST",
                                "start_offset": 0,
                                "end_offset": len(REQUEST),
                                "source_text": REQUEST,
                            }
                        ],
                    }
                ],
                "work_relations": [],
            },
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
        require_meta=True,
        provenance_sources=provenance,
    )
    cases: list[dict[str, Any]] = []
    for group in GROUPS:
        partial = group == GROUPS[1]
        fields = [
            {"title": "작업 A", "status": "needsAction", "due": "2026-10-01"},
            *([] if partial else [{"title": "작업 B", "status": "completed", "due": "2026-10-02"}]),
        ]
        evidence: list[dict[str, Any]] = []
        snapshots: dict[str, Any] = {}
        for index, payload in enumerate(fields, start=1):
            handle, ref = f"task:094-{index}", f"094-evidence-{index}"
            observation = task_calendar_source_snapshot(
                {
                    "resource_type": "task",
                    "resource_handle": handle,
                    "parent_id": "094-synthetic-list",
                    "version": "094-synthetic-version",
                    "payload": payload,
                },
                max_snapshot_chars=4000,
            )
            if observation is None:
                raise ValueError("synthetic snapshot failed Product binding")
            snapshots[ref] = observation["snapshot"]
            evidence.append(
                {
                    "schema_version": 1,
                    "evidence_id": ref,
                    "resource_handle": handle,
                    "segment_id": f"{ref}-segment",
                    "kind": "excerpt",
                    "excerpt": "\n".join(f"{key}: {value}" for key, value in payload.items()),
                    "locator": {"source_version_ref": observation["source_version_ref"]},
                    "reason_codes": ["SUPPORTS"],
                }
            )
        refs = [item["evidence_id"] for item in evidence]
        retrieval = {
            "coverage": "PARTIAL" if partial else "SUFFICIENT",
            "missing_information": [],
            "source_statuses": [
                {
                    "route_id": "094-task-route",
                    "resource_type": "task",
                    "work_unit_ids": ["work-1"],
                    "status": "PARTIAL" if partial else "COMPLETE",
                    "evidence_refs": refs,
                    "failure_kind": None,
                    "checked_read_count": 1,
                    "observed_resource_count": len(evidence),
                    "scope_complete": not partial,
                    "continuation_status": "HAS_MORE" if partial else "EXHAUSTED",
                }
            ],
            "evidence_by_work_unit": [{"work_unit_id": "work-1", "evidence_refs": refs}],
        }
        captured: list[dict[str, Any]] = []

        def capture(
            prompt_id: str, prompt_input: Any, *, sink: list[dict[str, Any]] = captured
        ) -> Any:
            if prompt_id != "planning.compose_answer":
                raise ValueError("unexpected semantic boundary during preparation")
            sink.append(deepcopy(dict(prompt_input)))
            raise _CapturedComposition

        outline = outline_answer(
            user_request=REQUEST,
            request_intent=intent,
            evidence=evidence,
            work_analysis=None,
            source_snapshots=snapshots,
            retrieval_result=retrieval,
            invoke=capture,
        )
        with suppress(_CapturedComposition):
            compose_answer(
                user_request=REQUEST,
                request_intent=intent,
                evidence=evidence,
                work_analysis=None,
                answer_outline=cast(AnswerOutlineV1, outline),
                source_snapshots=snapshots,
                retrieval_result=retrieval,
                invoke=capture,
            )
        if len(captured) != 1:
            raise ValueError("heterogeneous Sources did not delegate exactly once to Product")
        projection = captured[0]
        state = _synthetic_component_state(projection, group=group)
        state["retrieval_result"].update(
            evidence_refs=refs,
            source_resource_refs=[item["resource_handle"] for item in evidence],
        )
        cases.append(
            {
                "group": group,
                "case_id": f"{group}-T1",
                "trial": 1,
                "reference_time": REFERENCE_TIME,
                "fault_profile": None,
                "origin": "SYNTHETIC_COMPONENT_NOT_CANONICAL_CASE_OR_UPSTREAM_MODEL_OUTPUT",
                "prompt_input": projection,
                "snapshots": snapshots,
                "component_state": state,
                "input_binding_sha256": object_hash([projection, snapshots, state]),
            }
        )
    return cases
