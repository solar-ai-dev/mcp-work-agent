from __future__ import annotations

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
                "effect": outputs[candidate["resource_type"]],
            }
            for candidate in _CANDIDATES
            if candidate["resource_type"] in outputs
        ]
    }


def test_registry_candidates__from_runtime_registry__match_write_capabilities() -> None:
    by_resource = {candidate["resource_type"]: candidate for candidate in _CANDIDATES}
    assert by_resource["GMAIL_DRAFT"]["allowed_output_effects"] == ["CREATE", "UPDATE"]
    assert by_resource["GMAIL_MESSAGE"]["allowed_output_effects"] == ["SEND"]
    assert "GMAIL_THREAD" not in by_resource


@pytest.mark.parametrize("mutation", ["unregistered", "duplicate", "unsupported"])
def test_output_schema__with_non_candidate_or_unsupported_decisions__rejects_candidate(
    mutation: str,
) -> None:
    candidate = _decisions(outputs={"GMAIL_DRAFT": "CREATE"})
    items = cast(list[dict[str, object]], candidate["output_responsibilities"])
    if mutation == "unregistered":
        items.append({"resource_type": "UNREGISTERED", "effect": "CREATE"})
    elif mutation == "duplicate":
        items.append(deepcopy(items[0]))
    else:
        items[0]["effect"] = "SEND"

    assert validate_output_schema(
        candidate,
        output_responsibilities.build_output_responsibility_output_schema(_CANDIDATES).json_schema,
    )


@pytest.mark.parametrize("candidate", [_decisions(), _decisions(outputs={"TASK": "CREATE"})])
def test_output_schema__with_empty_or_requested_subset__accepts_candidate(
    candidate: dict[str, object],
) -> None:
    assert validate_output_schema(
        candidate,
        output_responsibilities.build_output_responsibility_output_schema(_CANDIDATES).json_schema,
    ) == []


def test_output_validation__with_duplicate_resource__rejects_candidate(
) -> None:
    candidate = _decisions(outputs={"GMAIL_DRAFT": "CREATE"})
    items = cast(list[dict[str, object]], candidate["output_responsibilities"])
    items.append({"resource_type": "GMAIL_DRAFT", "effect": "UPDATE"})

    with pytest.raises(ValueError, match="candidate is invalid"):
        output_responsibilities.validate_output_responsibility_candidate(
            candidate,
            output_candidates=_CANDIDATES,
        )


def test_output_validation__without_source_authority__keeps_requested_effect() -> None:
    candidate = _decisions(outputs={"TASK": "CREATE", "GMAIL_MESSAGE": "SEND"})

    assert (
        output_responsibilities.validate_output_responsibility_candidate(
            candidate,
            output_candidates=_CANDIDATES,
        )
        == candidate
    )


def test_output_schema__with_prohibited_effect__removes_effect() -> None:
    candidate = _decisions(outputs={"GMAIL_DRAFT": "CREATE", "GMAIL_MESSAGE": "SEND"})

    assert validate_output_schema(
        candidate,
        output_responsibilities.build_output_responsibility_output_schema(
            _CANDIDATES,
            prohibited_effects={"SEND"},
        ).json_schema,
    )
