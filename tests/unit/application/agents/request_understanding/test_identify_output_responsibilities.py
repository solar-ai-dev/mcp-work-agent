from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import cast

import pytest

from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_responsibilities,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

_CANDIDATES = output_responsibilities.build_output_responsibility_candidates(
    load_signed_tool_registry()
)


def _decisions(*, outputs: dict[str, str] | None = None) -> dict[str, object]:
    outputs = outputs or {}
    return {
        "output_responsibilities": [
            {
                "resource_type": candidate["resource_type"],
                "effect": outputs.get(candidate["resource_type"], "NONE"),
            }
            for candidate in _CANDIDATES
        ]
    }


def test_registry_candidates__are_exact_write_capabilities() -> None:
    by_resource = {candidate["resource_type"]: candidate for candidate in _CANDIDATES}
    assert by_resource["GMAIL_DRAFT"]["allowed_output_effects"] == ["CREATE", "UPDATE"]
    assert by_resource["GMAIL_MESSAGE"]["allowed_output_effects"] == ["SEND"]
    assert "GMAIL_THREAD" not in by_resource


@pytest.mark.parametrize(
    "mutate",
    [
        lambda items: items.pop(),
        lambda items: items.append({"resource_type": "UNREGISTERED", "effect": "NONE"}),
        lambda items: items.__setitem__(1, deepcopy(items[0])),
        lambda items: items[0].update({"effect": "CREATE"}),
    ],
)
def test_output_schema__rejects_non_exact_and_unsupported_decisions(
    mutate: Callable[[list[dict[str, object]]], object],
) -> None:
    candidate = _decisions()
    items = cast(list[dict[str, object]], candidate["output_responsibilities"])
    mutate(items)

    assert validate_output_schema(
        candidate,
        output_responsibilities.build_output_responsibility_output_schema(_CANDIDATES).json_schema,
    )


def test_output_validation__keeps_requested_effect_without_source_authority() -> None:
    candidate = _decisions(outputs={"TASK": "CREATE", "GMAIL_MESSAGE": "SEND"})

    assert (
        output_responsibilities.validate_output_responsibility_candidate(
            candidate,
            output_candidates=_CANDIDATES,
        )
        == candidate
    )


def test_output_schema__removes_explicitly_prohibited_effect() -> None:
    candidate = _decisions(outputs={"GMAIL_DRAFT": "CREATE", "GMAIL_MESSAGE": "SEND"})

    assert validate_output_schema(
        candidate,
        output_responsibilities.build_output_responsibility_output_schema(
            _CANDIDATES,
            prohibited_effects={"SEND"},
        ).json_schema,
    )
