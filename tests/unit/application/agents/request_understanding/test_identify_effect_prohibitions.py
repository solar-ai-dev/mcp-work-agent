from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding import (
    identify_effect_prohibitions as effect_prohibitions,
)
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_responsibilities,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    effect_prohibition_decision,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference

_RESOURCE_CANDIDATES = output_responsibilities.build_output_responsibility_candidates(
    load_signed_tool_registry()
)
_EFFECT_CANDIDATES = effect_prohibitions.build_effect_prohibition_candidates(_RESOURCE_CANDIDATES)


def _prompt() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.identify_effect_prohibitions",
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name="identify_goal",
        node_state="INITIAL",
        purpose="identify_effect_prohibitions",
        input_schema_version="v1",
        output_schema_version="v1",
    )


def _prohibitions(*forbidden: str) -> dict[str, object]:
    return {
        "effect_prohibitions": [
            {
                "effect": candidate["effect"],
                "prohibition": (
                    "FORBIDDEN" if candidate["effect"] in forbidden else "NOT_FORBIDDEN"
                ),
            }
            for candidate in _EFFECT_CANDIDATES
        ]
    }


def _output_decisions(*, gmail_message_effect: str | None = None) -> dict[str, object]:
    decisions: list[dict[str, object]] = []
    for candidate in _RESOURCE_CANDIDATES:
        if candidate["resource_type"] == "GMAIL_MESSAGE" and gmail_message_effect is not None:
            decisions.append(
                {
                    "resource_type": "GMAIL_MESSAGE",
                    "effect": gmail_message_effect,
                }
            )
        else:
            decisions.append({"resource_type": candidate["resource_type"], "effect": "NONE"})
    return {"output_responsibilities": decisions}


def test_effect_candidates__reuse_runtime_supported_effect_exact_set() -> None:
    assert [candidate["effect"] for candidate in _EFFECT_CANDIDATES] == [
        "CREATE",
        "UPDATE",
        "SEND",
        "DELETE",
    ]


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_effect_prohibition_schema__rejects_non_exact_candidate_set(mutation: str) -> None:
    value = _prohibitions()
    decisions = cast(list[dict[str, object]], value["effect_prohibitions"])
    if mutation == "missing":
        decisions.pop()
    elif mutation == "extra":
        decisions.append({"effect": "ARCHIVE", "prohibition": "NOT_FORBIDDEN"})
    else:
        decisions[-1] = deepcopy(decisions[0])

    errors = validate_output_schema(
        value,
        effect_prohibitions.build_effect_prohibition_output_schema(_EFFECT_CANDIDATES).json_schema,
    )

    assert errors


@pytest.mark.parametrize(
    ("request_text", "candidate", "expected"),
    [
        (
            "Draft로 저장하되 실제 전송은 하지 않는다.",
            _prohibitions("SEND"),
            frozenset({"SEND"}),
        ),
        ("메일을 전송한다.", _prohibitions(), frozenset()),
        ("금지 문구를 Draft 본문에 인용한다.", _prohibitions(), frozenset()),
        ("가정 상황을 설명한다.", _prohibitions(), frozenset()),
    ],
)
def test_effect_prohibition_operation__keeps_only_model_owned_explicit_prohibition(
    request_text: str,
    candidate: dict[str, object],
    expected: frozenset[str],
) -> None:
    runtime = FakeStructuredInferencePort(outputs=[candidate], validate_schema=True)

    result = effect_prohibitions.identify_effect_prohibitions(
        llm_runtime=runtime,
        requested_mode="LOCAL_GPU",
        prompt_ref=_prompt(),
        prompt_input={"user_request": request_text, "selected_resource_refs": []},
        goal_candidate={"goal": "요청 수행", "completion_conditions": []},
        effect_candidates=_EFFECT_CANDIDATES,
    )

    assert effect_prohibitions.prohibited_effects(result) == expected
    assert runtime.calls[0]["prompt_input"]["effect_candidates"] == list(_EFFECT_CANDIDATES)


def test_send_prohibition__removes_send_variant_and_defends_post_inference() -> None:
    prohibitions = cast(
        effect_prohibition_decision.EffectProhibitionDecisionCandidateV1,
        effect_prohibitions.validate_effect_prohibition_candidate(
            _prohibitions("SEND"),
            effect_candidates=_EFFECT_CANDIDATES,
        ),
    )
    forbidden = effect_prohibitions.prohibited_effects(prohibitions)
    invalid = _output_decisions(gmail_message_effect="SEND")

    assert validate_output_schema(
        invalid,
        output_responsibilities.build_output_responsibility_output_schema(
            _RESOURCE_CANDIDATES,
            prohibited_effects=forbidden,
        ).json_schema,
    )
    with pytest.raises(
        output_responsibilities.ProhibitedOutputResponsibilityDecisionError
    ) as excinfo:
        output_responsibilities.validate_output_responsibility_candidate(
            invalid,
            output_candidates=_RESOURCE_CANDIDATES,
            prohibited_effects=forbidden,
        )
    assert excinfo.value.reason_code == "REQUEST_PROHIBITED_OUTPUT_EFFECT_SELECTED"
    assert excinfo.value.affected_field_paths == ("$.output_responsibilities[0].effect",)


def test_send_not_forbidden__keeps_send_variant_available() -> None:
    candidate = _output_decisions(gmail_message_effect="SEND")

    result = output_responsibilities.validate_output_responsibility_candidate(
        candidate,
        output_candidates=_RESOURCE_CANDIDATES,
        prohibited_effects=(),
    )

    message = next(
        decision
        for decision in result["output_responsibilities"]
        if decision["resource_type"] == "GMAIL_MESSAGE"
    )
    assert message == {
        "resource_type": "GMAIL_MESSAGE",
        "effect": "SEND",
    }
