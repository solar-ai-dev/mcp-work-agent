from copy import deepcopy
from types import SimpleNamespace

import pytest
from scripts.evaluate_request_tool_route_horizontal import _AtomicRecordingInferencePort
from scripts.ru_observation import metrics, observe_local_calls, source_format_only_envelope
from scripts.ru_source_demand_candidate import (
    JointRoleAuthorityCandidate,
    bind_needs,
    binding_schema,
    demand_schema,
    expand_demands,
    source_catalog,
)

from google_work_agent.adapters.llm.ollama import transport as ollama_transport
from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def test_projection_does_not_invent_sources_or_change_binding() -> None:
    catalog = source_catalog(
        [
            {"resource_type": "TASK", "owned_fact_kinds": ["notes"]},
            {"resource_type": "CALENDAR_EVENT", "owned_fact_kinds": ["start", "end"]},
        ]
    )
    raw = {
        "source_demands": [
            {
                "information_needed": ["진행 상태"],
                "source_ref": "s01",
                "target_scope": "CRITERIA",
                "work_unit_ids": ["w2", "w1"],
            }
        ]
    }
    before = deepcopy(raw)
    output = expand_demands(raw, catalog)
    assert output["source_dependencies"] == [
        {
            "resource_type": "TASK",
            "dependency": "SOURCE_REQUIRED",
            "required_information": ["진행 상태"],
            "target_scope": "CRITERIA",
            "work_unit_ids": ["w2", "w1"],
        },
        {"resource_type": "CALENDAR_EVENT", "dependency": "SOURCE_NOT_REQUIRED"},
    ]
    assert raw == before


def test_empty_selection_is_not_replaced_with_a_business_default() -> None:
    output = expand_demands({"source_demands": []}, [{"ref": "s01", "resource_type": "TASK"}])
    assert output["source_dependencies"][0]["dependency"] == "SOURCE_NOT_REQUIRED"


@pytest.mark.parametrize("refs", [["unknown"], ["s01", "s01"]])
def test_closed_unique_source_binding_rejects_invalid_refs(refs: list[str]) -> None:
    with pytest.raises(ValueError, match="closed and unique"):
        expand_demands(
            {
                "source_demands": [
                    {
                        "source_ref": ref,
                        "information_needed": ["a"],
                        "target_scope": "SINGULAR",
                        "work_unit_ids": ["w"],
                    }
                    for ref in refs
                ]
            },
            [{"ref": "s01", "resource_type": "TASK"}],
        )


def test_schema_rejects_foreign_work_unit_without_deciding_source_semantics() -> None:
    schema = demand_schema(["s01"], ["w1"]).json_schema
    value = {
        "source_demands": [
            {
                "information_needed": ["任意の事実"],
                "source_ref": "s01",
                "target_scope": "CRITERIA",
                "work_unit_ids": ["w2"],
            }
        ]
    }
    assert validate_output_schema(value, schema)
    value["source_demands"][0]["work_unit_ids"] = ["w1"]
    assert not validate_output_schema(value, schema)


def test_transport_failure_is_counted_and_input_retained(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise TimeoutError("bounded test timeout")

    monkeypatch.setattr(OllamaHTTPClient, "invoke_structured", fail)
    records = []
    with observe_local_calls(records), pytest.raises(TimeoutError):
        OllamaHTTPClient().invoke_structured(
            prompt_ref=SimpleNamespace(prompt_id="test"),
            prompt_input={"user_request": "x"},
            output_schema=SimpleNamespace(json_schema={}),
            instruction_text="instruction",
            model_id="test",
            timeout_seconds=1,
        )
    assert records[0]["input"] == {"user_request": "x"}
    assert records[0]["error_type"] == "TimeoutError"
    assert metrics(records)["calls"] == 1
    assert metrics(records)["missing_usage_calls"] == 1


def test_second_stage_cannot_rewrite_confirmed_information_or_work_binding() -> None:
    raw = {"bindings": {"d1": "s01", "d2": "s01"}}
    needs = [
        {
            "demand_id": "d1",
            "information_needed": ["원문 정보"],
            "work_unit_ids": ["w1"],
            "target_scope": "CRITERIA",
        },
        {
            "demand_id": "d2",
            "information_needed": ["다른 정보"],
            "work_unit_ids": ["w2"],
            "target_scope": "CRITERIA",
        },
    ]
    result = bind_needs(needs, raw, [{"ref": "s01", "resource_type": "TASK"}])
    item = result["source_dependencies"][0]
    assert item["required_information"] == ["원문 정보", "다른 정보"]
    assert item["work_unit_ids"] == ["w1", "w2"]
    assert validate_output_schema(
        {"bindings": {"d1": "s01", "d2": "s01"}, "information_needed": ["rewrite"]},
        binding_schema(["d1", "d2"], ["s01"]).json_schema,
    )


def test_joint_role_schema_retains_v4_modality_and_closed_bindings() -> None:
    candidate = JointRoleAuthorityCandidate(
        delegate=None,
        tool_catalog=load_development_tool_registry(),
        model_id="test",
        sampling_seed=1,
    )
    schema = candidate._build_goal_output_schema(
        work_unit_ids=("w1", "w2"), output_candidates=candidate._output_candidates
    ).json_schema
    assert schema["allOf"][0]["then"]["properties"]["requested_outputs"] == {"maxItems": 0}
    assert schema["allOf"][1]["then"]["properties"]["requested_outputs"] == {"minItems": 1}
    assert "source_demands" in schema["required"]
    assert "explicit_prohibitions" not in schema["properties"]
    properties = schema["properties"]["source_demands"]["items"]["properties"]
    assert properties["work_unit_ids"]["items"]["enum"] == ["w1", "w2"]


def test_failed_owner_input_is_not_lost() -> None:
    class FailingPort:
        def infer(self, *args: object, **kwargs: object) -> None:
            raise ValueError("invalid candidate")

    recorder = _AtomicRecordingInferencePort(FailingPort())
    with pytest.raises(ValueError):
        recorder.infer("LOCAL_GPU", SimpleNamespace(prompt_id="test"), {"user_request": "x"}, None)
    assert recorder.atomic[0]["input"] == {"user_request": "x"}
    assert recorder.atomic[0]["status"] == "ERROR"


def test_envelope_candidate_keeps_decoding_schema_and_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    sent = []
    monkeypatch.setattr(ollama_transport, "_post_json", lambda **kwargs: sent.append(kwargs) or {})
    payload = {
        "prompt": json.dumps(
            {
                "prompt_ref": {"prompt_id": "request_understanding.identify_source_dependencies"},
                "input": {"user_request": "原文"},
                "output_schema": {"type": "object"},
            }
        ),
        "format": {"type": "object"},
        "options": {"temperature": 0, "seed": 7},
        "think": False,
    }
    before = deepcopy(payload)
    with source_format_only_envelope([]):
        ollama_transport._post_json(
            endpoint="unused", path="/api/generate", payload=payload, timeout_seconds=1
        )
    actual = sent[0]["payload"]
    assert actual["format"] == payload["format"]
    assert actual["options"] == payload["options"]
    assert actual["think"] is False
    assert json.loads(actual["prompt"])["input"] == {"user_request": "原文"}
    assert "output_schema" not in json.loads(actual["prompt"])
    assert payload == before
