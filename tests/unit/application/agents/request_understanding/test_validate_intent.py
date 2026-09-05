from copy import deepcopy
from typing import cast

import pytest

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    RequestUnderstandingValidationError,
    validate_intent,
    validated_repository_authority,
)
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


def _candidate() -> dict[str, object]:
    return {
        "schema_version": 2,
        "goal": "김대리 관련 메일에서 할 일 정리",
        "completion_conditions": ["할 일을 요약한다"],
        "constraints": [{"kind": "PERSON", "field": "person", "value": "김대리"}],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }


def test_validate_intent__canonical_candidate__preserves_contract() -> None:
    assert validate_intent(_candidate())["goal"] == "김대리 관련 메일에서 할 일 정리"


def test_validate_intent__unknown_schema__fails_closed() -> None:
    invalid = deepcopy(_candidate())
    invalid["schema_version"] = 99
    with pytest.raises(RequestUnderstandingValidationError, match="schema_version"):
        validate_intent(invalid)


@pytest.mark.parametrize(
    "provenance",
    [
        {"source": "USER_REQUEST", "start_offset": 1, "end_offset": 10},
        {"source": "USER_REQUEST", "start_offset": 0, "end_offset": 99},
        {"source": "UNTRUSTED", "start_offset": 0, "end_offset": 10},
    ],
)
def test_validate_intent__rejects_forged__repository_provenance(
    provenance: dict[str, object],
) -> None:
    repository = "acme/repo"
    candidate = _candidate()
    candidate["constraints"] = [
        {
            "kind": "RESOURCE",
            "field": "repository",
            "value": repository,
            "provenance": provenance,
        }
    ]

    with pytest.raises(RequestUnderstandingValidationError, match="provenance"):
        validate_intent(
            candidate,
            provenance_sources={"USER_REQUEST": repository},
        )


def test_validate_intent__rejects_forged_repository_value__against_exact_span() -> None:
    candidate = _candidate()
    candidate["constraints"] = [
        {
            "kind": "RESOURCE",
            "field": "repository",
            "value": "evil/repo",
            "provenance": {
                "source": "USER_REQUEST",
                "start_offset": 0,
                "end_offset": len("acme/repo"),
            },
        }
    ]

    with pytest.raises(RequestUnderstandingValidationError, match="does not match source"):
        validate_intent(
            candidate,
            provenance_sources={"USER_REQUEST": "acme/repo"},
        )


def test_validated_repository_authority__explicit_selected_match__normalizes_once() -> None:
    repository = "acme/repo"

    assert (
        validated_repository_authority(
            _intent(repository),
            selected_resources=(_selected_issue(repository),),
        )
        == repository
    )
    assert validated_repository_authority(_intent(repository), selected_resources=()) == repository
    assert (
        validated_repository_authority(
            _intent(None),
            selected_resources=(_selected_issue(repository),),
        )
        == repository
    )


def test_validated_repository_authority__conflict__fails_closed() -> None:
    with pytest.raises(RequestUnderstandingValidationError, match="conflict"):
        validated_repository_authority(
            _intent("owner-a/repo"),
            selected_resources=(_selected_issue("owner-b/repo"),),
        )


def test_validated_repository_authority__missing_or_unvalidated__is_not_authority() -> None:
    assert validated_repository_authority(_intent(None), selected_resources=()) is None
    intent = _intent("acme/repo")
    intent["constraints"][0].pop("provenance")
    with pytest.raises(RequestUnderstandingValidationError, match="validated provenance"):
        validated_repository_authority(intent, selected_resources=())


def _intent(repository: str | None) -> RequestIntentV2:
    constraints = []
    if repository is not None:
        constraints.append(
            {
                "kind": "RESOURCE",
                "field": "repository",
                "value": repository,
                "provenance": {
                    "source": "USER_REQUEST",
                    "start_offset": 0,
                    "end_offset": len(repository),
                },
            }
        )
    return cast(
        RequestIntentV2,
        {
            **_candidate(),
            "constraints": constraints,
            "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        },
    )


def _selected_issue(repository: str) -> SelectedResourceRef:
    return SelectedResourceRef(
        resource_ref_id="ref-1",
        connector_id="github",
        resource_type="github_issue",
        resource_id=f"{repository}#7",
        parent_resource_id=repository,
    )
