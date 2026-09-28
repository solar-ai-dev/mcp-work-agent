"""V25 schema equivalence and connected candidate checks; zero real model calls."""

from __future__ import annotations

import json
from copy import deepcopy
from itertools import product
from typing import Any, cast

import pytest
from scripts.ru_source_scope_discriminated_candidate import (
    SCHEMA_VERSION,
    SourceScopeDiscriminatedCandidate,
    discriminate_scope_items,
    source_scope_discriminated_candidate,
)
from scripts.ru_source_scope_handoff_candidate import SourceScopeHandoffCandidate

from google_work_agent.adapters.llm.ollama import transport
from google_work_agent.application.agents.request_understanding import (
    preserve_explicit_search_anchors as projection_ops,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.agents.tool_routing.resolve_policy_preconditions import (
    ScopeExpansionResolver,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

REQUEST = "메일만 확인해서 담당자를 알려줘."
UNITS = ("work-1", "work-2")
PROOF = {"source": "USER_REQUEST", "source_text": "메일만"}


class _NoDelegate:
    def infer(self, *args: Any) -> Any:
        raise AssertionError("unexpected extra owner call")


def _candidate(cls: Any = SourceScopeDiscriminatedCandidate) -> Any:
    return cls(
        delegate=_NoDelegate(),
        tool_catalog=load_development_tool_registry(),
        model_id="test",
        sampling_seed=180,
    )


def _schemas() -> tuple[dict[str, Any], dict[str, Any]]:
    with source_scope_discriminated_candidate(user_request=REQUEST, work_unit_ids=UNITS):
        baseline = _candidate(SourceScopeHandoffCandidate)
        candidate = _candidate()
        kwargs = {"work_unit_ids": UNITS, "output_candidates": baseline._output_candidates}
        old = deepcopy(baseline._build_goal_output_schema(**kwargs).json_schema)
        new = deepcopy(candidate._build_goal_output_schema(**kwargs).json_schema)
    return old, new


def _item(schema: dict[str, Any]) -> dict[str, Any]:
    return schema["properties"]["constraints"]["properties"]["additional_constraints"]["items"]


def _raw(*additional: Any) -> dict[str, Any]:
    return {
        "goal": REQUEST,
        "completion_conditions": ["근거로 담당자를 답한다."],
        "constraints": {
            **{
                name: []
                for name in (
                    "search_terms",
                    "business_concepts",
                    "person",
                    "sender",
                    "recipient",
                    "subject",
                    "period",
                )
            },
            "coverage_requirement": {"value": "NOT_COLLECTION", "work_unit_ids": ["work-1"]},
            "additional_constraints": list(additional),
        },
        "analysis_requirement": "NONE",
        "requested_result_mode": "ANSWER_ONLY",
        "requested_outputs": [],
    }


def _scope() -> dict[str, Any]:
    return {
        "field": "required_sources",
        "value": ["EMAIL"],
        "work_unit_ids": ["work-1"],
        "provenance": deepcopy(PROOF),
    }


def _work() -> dict[str, Any]:
    return {
        "work_units": [
            {
                "unit_id": "work-1",
                "request_provenance": [
                    {
                        "source": "USER_REQUEST",
                        "source_text": REQUEST,
                        "start_offset": 0,
                        "end_offset": len(REQUEST),
                    }
                ],
            }
        ],
        "work_relations": [],
    }


def test_only_completed_goal_item_schema_representation_changes() -> None:
    old, new = _schemas()
    original = deepcopy(old)
    assert discriminate_scope_items(old) == new
    assert old == original
    item = _item(new)
    assert set(item) == {"oneOf"}
    ordinary, required, forbidden = item["oneOf"]
    assert "provenance" not in ordinary["properties"]
    assert required["properties"]["field"]["const"] == "required_sources"
    assert forbidden["properties"]["field"]["const"] == "forbidden_sources"
    for branch in (required, forbidden):
        assert branch["required"] == ["field", "value", "work_unit_ids", "provenance"]
    for branch in item["oneOf"]:
        assert branch["properties"]["work_unit_ids"]["items"] == {"enum": list(UNITS)}
        assert "allOf" not in branch
    new["properties"]["constraints"]["properties"]["additional_constraints"]["items"] = _item(old)
    assert new == old
    assert list(new["properties"]) == list(old["properties"])


def test_conditional_and_discriminated_items_accept_identical_valid_language() -> None:
    old, new = map(_item, _schemas())
    absent = object()
    fields = [*old["properties"]["field"]["enum"], "unknown", None]
    values = [
        "EMAIL",
        ["EMAIL", "TASK"],
        ["EMAIL", "EMAIL"],
        "TASK",
        "CALENDAR",
        "ISSUE",
        "ordinary literal",
        ["ordinary", "ordinary"],
        "",
        [],
        [""],
        ["unknown"],
        None,
        7,
        {},
    ]
    proofs = [
        absent,
        deepcopy(PROOF),
        {},
        {"source": "USER_REQUEST"},
        {"source": "OTHER", "source_text": "메일만"},
        {**PROOF, "source_text": ""},
        {**PROOF, "start_offset": 0},
        None,
    ]
    bindings = [["work-1"], list(UNITS), ["foreign"], [], ["work-1", "work-1"]]
    checked = 0
    for field, value, proof, ids in product(fields, values, proofs, bindings):
        item = {"field": field, "value": value, "work_unit_ids": ids}
        if proof is not absent:
            item["provenance"] = proof
        assert bool(validate_output_schema(item, old)) == bool(validate_output_schema(item, new)), (
            item
        )
        checked += 1
    assert checked == len(fields) * len(values) * len(proofs) * len(bindings)
    for malformed in [None, [], "text", 7, {}, {**_scope(), "unknown": True}]:
        assert bool(validate_output_schema(malformed, old)) == bool(
            validate_output_schema(malformed, new)
        )
    for removed in ("field", "value", "work_unit_ids"):
        item = _scope()
        item.pop(removed)
        assert validate_output_schema(item, old) and validate_output_schema(item, new)


def test_missing_scope_proof_has_branch_specific_repair_error_and_is_not_defaulted() -> None:
    old, new = _schemas()
    missing = _scope()
    missing.pop("provenance")
    assert validate_output_schema(_raw(missing), old)
    errors = validate_output_schema(_raw(missing), new)
    assert any("provenance" in error for error in errors)
    assert not any("title" in error for error in errors)
    assert not validate_output_schema(_raw(), new)  # No mandatory scope generation.
    assert "provenance" not in missing


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: item["allOf"].append({"required": ["new_semantics"]}),
        lambda item: item["required"].append("new_semantics"),
        lambda item: item.update(additionalProperties=True),
        lambda item: item["properties"].update(extra={"type": "string"}),
    ],
)
def test_transform_fails_on_unrecognized_v24_contract_changes(mutate: Any) -> None:
    old, _ = _schemas()
    mutate(_item(old))
    with pytest.raises(ValueError, match="unchanged v24"):
        discriminate_scope_items(old)


@pytest.mark.parametrize("valid_after_repair", [True, False])
def test_real_wire_uses_same_discriminated_schema_for_first_and_single_repair(
    monkeypatch: pytest.MonkeyPatch,
    valid_after_repair: bool,
) -> None:
    candidate = _candidate()
    baseline = _candidate(SourceScopeHandoffCandidate)
    assert candidate._goal_output_instruction == baseline._goal_output_instruction
    assert (
        candidate.binding["goal_output_prompt_sha256"]
        == baseline.binding["goal_output_prompt_sha256"]
    )
    assert (
        candidate.binding["source_handoff_contract_sha256"]
        == baseline.binding["source_handoff_contract_sha256"]
    )
    missing = _scope()
    missing.pop("provenance")
    responses = [_raw(missing), _raw(_scope()) if valid_after_repair else _raw(missing)]
    calls = []

    def dispatch(**kwargs: Any) -> Any:
        calls.append(deepcopy(kwargs["payload"]))
        return {
            "response": json.dumps(responses[len(calls) - 1]),
            "model": "test",
            "prompt_eval_count": 3,
            "eval_count": 5,
            "total_duration": 1000000,
        }

    monkeypatch.setattr(transport, "_post_json", dispatch)
    with source_scope_discriminated_candidate(user_request=REQUEST) as session:
        projection = {
            "user_request": REQUEST,
            "selected_resource_refs": [],
            "requested_work": _work(),
        }
        prompt = PromptRegistry().lookup_for_evaluation("request_understanding.identify_goal")
        if not valid_after_repair:
            with pytest.raises(ValueError, match="candidate structured output is invalid"):
                candidate.infer("LOCAL_GPU", prompt, projection, None)
        else:
            result = candidate.infer("LOCAL_GPU", prompt, projection, None)
            assert session.work_unit_ids == ("work-1",)
            projected = projection_ops.project_extractive_source_goal(
                result.structured_output,
                request_text=REQUEST,
            )
            normalized = goal_schema.validate_request_goal_candidate(
                result.structured_output,
                resource_responsibilities={
                    "source_reads": [
                        {
                            "resource_type": "GMAIL_THREAD",
                            "required_information": ["담당자"],
                            "target_scope": "CRITERIA",
                            "work_unit_ids": ["work-1"],
                        }
                    ],
                    "outputs": [],
                },
                effect_prohibitions={"effect_prohibitions": []},
                requested_work=_work(),
                work_unit_ids=("work-1",),
                provenance_sources={"USER_REQUEST": REQUEST},
            )
            intent = finalize_intent(
                normalized,
                {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
                artifact_id="scope-v25",
                user_request=REQUEST,
            )
            scope = next(x for x in intent["constraints"] if x["field"] == "required_sources")
            assert scope == projected["constraints"]["additional_constraints"][0]
            read = ("google_workspace", "TASK", "SOURCE_DEPENDENCY")
            assert ScopeExpansionResolver().out_of_scope_reads(
                request_intent=cast(Any, intent),
                required_reads=[read],
                category_of=coarse_resource_category,
                required_work_unit_bindings={read: ("work-1",)},
            ) == (read,)
    assert len(calls) == 2
    assert calls[0]["format"] == calls[1]["format"]
    assert set(_item(calls[0]["format"])) == {"oneOf"}
    assert calls[0]["system"] == baseline._goal_output_instruction
    assert all(x["options"]["temperature"] == 0.0 and x["options"]["seed"] == 180 for x in calls)
    repair_input = json.loads(calls[1]["prompt"])["input"]
    assert repair_input["candidate_output"] == responses[0]
    assert any("provenance" in error for error in repair_input["schema_errors"])
    assert candidate.additional_provider_call_count == 1
    assert candidate.binding["goal_output_schema_version"] == SCHEMA_VERSION
