"""Inactive, owner-local whitespace selector codec; final provenance stays exact."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from scripts.production_goal_output_candidate import (
    ConnectedGoalOutputCandidate,
    _has_pending_confirmation,
)

from google_work_agent.adapters.langgraph.subgraphs.request_understanding import graph as ru_graph
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.projections.identify_goal_projection import (  # noqa: E501
    project_identify_goal_input,
)
from google_work_agent.application.agents.request_understanding import (
    identify_requested_work as work_owner,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestedWorkDefinitionV1,
)
from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    current_provider_dispatch_run_id,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

# Unicode White_Space, explicitly excluding zero-width/BOM and Python's extra C0 separators.
SELECTOR_WHITESPACE = frozenset(
    "\t\n\v\f\r \u0085\u00a0\u1680"
    + "".join(chr(value) for value in range(0x2000, 0x200B))
    + "\u2028\u2029\u202f\u205f\u3000"
)
CODEC_VERSION = "evaluation-work-span-codec-v1"


def _unique_occurrence(text: str, selector: str) -> int | None:
    start = text.find(selector)
    if start < 0:
        return None
    if text.find(selector, start + 1) >= 0:
        raise ValueError("Work selector has multiple occurrences")
    return start


def bind_request_span(selector: str, *, user_request: str) -> dict[str, Any]:
    """Resolve a selector, not a business value; do not modify the authoritative request."""
    if not any(character not in SELECTOR_WHITESPACE for character in selector):
        raise ValueError("Work selector cannot contain only whitespace")
    start = _unique_occurrence(user_request, selector)
    mode = "EXACT"
    if start is not None:
        end = start + len(selector)
    else:
        offsets = [
            index
            for index, character in enumerate(user_request)
            if character not in SELECTOR_WHITESPACE
        ]
        source_view = "".join(user_request[index] for index in offsets)
        selector_view = "".join(
            character for character in selector if character not in SELECTOR_WHITESPACE
        )
        position = _unique_occurrence(source_view, selector_view)
        if position is None:
            raise ValueError("Work selector has no codepoint-identical source interval")
        start = offsets[position]
        end = offsets[position + len(selector_view) - 1] + 1
        mode = "WHITESPACE_SELECTOR"
    return {
        "source": "USER_REQUEST",
        "start_offset": start,
        "end_offset": end,
        "source_text": user_request[start:end],
        "binding_mode": mode,
    }


def materialize_work_spans(
    value: object,
    *,
    user_request: str,
    bindings: list[dict[str, Any]] | None = None,
) -> RequestedWorkDefinitionV1:
    """Keep the existing response shape and work count; bind selectors to exact slices."""
    errors = validate_output_schema(value, work_owner.REQUESTED_WORK_OUTPUT_SCHEMA.json_schema)
    if errors:
        raise ValueError("invalid Work candidate: " + "; ".join(errors))
    positioned: list[tuple[int, int, list[dict[str, Any]]]] = []
    occupied: list[tuple[int, int]] = []
    for unit_index, unit in enumerate(cast(dict[str, Any], value)["work_units"]):
        provenance = []
        for span_index, selector in enumerate(unit["request_spans"]):
            bound = bind_request_span(selector, user_request=user_request)
            start, end = bound["start_offset"], bound["end_offset"]
            if any(start < other_end and other_start < end for other_start, other_end in occupied):
                raise ValueError("Work spans overlap in the original request")
            occupied.append((start, end))
            provenance.append({key: val for key, val in bound.items() if key != "binding_mode"})
            if bindings is not None:
                bindings.append({"unit_index": unit_index, "span_index": span_index, **bound})
        positioned.append(
            (min(item["start_offset"] for item in provenance), unit_index, provenance)
        )
    positioned.sort(key=lambda item: (item[0], item[1]))
    return validate_requested_work_definition(
        {
            "work_units": [
                {"unit_id": f"work-{index}", "request_provenance": provenance}
                for index, (_, _, provenance) in enumerate(positioned, start=1)
            ],
            "work_relations": [],
        },
        user_request=user_request,
    )


@dataclass
class _Invocation:
    run_id: str
    user_request: str
    events: list[dict[str, Any]] = field(default_factory=list)

    def validate(self, value: object, *, user_request: str) -> RequestedWorkDefinitionV1:
        if user_request != self.user_request or current_provider_dispatch_run_id() != self.run_id:
            raise ValueError("Work codec is outside its bound current-Run request")
        event: dict[str, Any] = {"router_validated_candidate": deepcopy(value), "bindings": []}
        self.events.append(event)
        try:
            result = materialize_work_spans(
                value, user_request=user_request, bindings=event["bindings"]
            )
            event["materialized_work_definition"] = deepcopy(result)
            return result
        except Exception as error:
            event["failure_type"] = type(error).__name__
            raise


_active_owner: ContextVar[_Invocation | None] = ContextVar(
    "evaluation_work_span_codec", default=None
)


@contextmanager
def work_span_codec_candidate(*, observations: list[dict[str, Any]]) -> Iterator[None]:
    """Change only the fresh physical RU Work candidate-to-State boundary, not inference."""
    original_node = ru_graph.identify_goal_node
    original_validator = work_owner.validate_requested_work_candidate

    def validate(value: object, *, user_request: str) -> RequestedWorkDefinitionV1:
        owner = _active_owner.get()
        return (
            original_validator(value, user_request=user_request)
            if owner is None
            else owner.validate(value, user_request=user_request)
        )

    def invoke(state: Any, **kwargs: Any) -> Any:
        projected = project_identify_goal_input(state)
        request = projected["request"]
        delegate = kwargs["llm_runtime"]
        if isinstance(delegate, ConnectedGoalOutputCandidate):
            delegate = delegate._delegate
        if (
            state.get("goal_candidate") is not None
            or state.get("request_intent") is not None
            or "confirmation_response" in projected
            or "request_reconsideration" in projected
            or _has_pending_confirmation(delegate, request.run_id)
        ):
            return original_node(state, **kwargs)
        owner = _Invocation(request.run_id, request.request_text)
        token = _active_owner.set(owner)
        try:
            return original_node(state, **kwargs)
        finally:
            _active_owner.reset(token)
            observations.append(
                {
                    "run_id": request.run_id,
                    "codec_version": CODEC_VERSION,
                    "codec_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "prompt_schema_runtime": "UNCHANGED_PRODUCT",
                    "events": deepcopy(owner.events),
                }
            )

    with (
        patch.object(work_owner, "validate_requested_work_candidate", validate),
        patch.object(ru_graph, "identify_goal_node", invoke),
    ):
        yield
