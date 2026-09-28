"""Inactive Source provenance contracts and compiled projection gate; no inference/I/O.

The graph below composes real merge/bind/Query projection operations, not the
Production MainGraph, Query LLM, or Provider execution. Structural admission is
deliberately not a business-semantic verdict.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, cast

import pytest
from langgraph.graph import END, START, StateGraph
from scripts import ru_source_provenance_candidate as candidate
from scripts.ru_observation import object_hash
from tests.support.context_retrieval import request_intent
from tests.support.source_dependency_wire import product_wire as product_wire

from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
)
from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_output_schema,
)
from google_work_agent.application.agents.request_understanding.merge_resource_responsibilities import (  # noqa: E501
    merge_resource_responsibilities,
)
from google_work_agent.application.agents.retrieval.plan_query import (
    RetrievalBudget,
    initial_retrieval_planner_input,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
)
from google_work_agent.application.agents.tool_routing.determine_io_resources import (
    _resource_responsibility_candidate,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)


def _reassemble(
    original: dict[str, Any],
    request: str,
    *,
    work_ids: tuple[str, ...] = ("work-1",),
    work_spans: tuple[tuple[int, int], ...] | None = None,
) -> dict[str, Any]:
    result = deepcopy(original)
    body = json.loads(result["prompt"])
    projection = body["input"]
    projection["user_request"] = request
    projection["goal_candidate"] = {"goal": request}
    spans = ((0, len(request)),) if work_spans is None else work_spans
    assert len(spans) == len(work_ids)
    projection["requested_work"] = validate_requested_work_definition(
        {
            "work_units": [
                {
                    "unit_id": work_id,
                    "request_provenance": [
                        {
                            "source": "USER_REQUEST",
                            "start_offset": start,
                            "end_offset": end,
                            "source_text": request[start:end],
                        }
                    ],
                }
                for work_id, (start, end) in zip(work_ids, spans, strict=True)
            ],
            "work_relations": [],
        },
        user_request=request,
    )
    body["output_schema"] = build_source_dependency_output_schema(
        projection["source_candidates"], work_unit_ids=work_ids
    ).json_schema
    registry = PromptRegistry()
    result["system"] = assemble_prompt(
        registry.lookup_for_evaluation(candidate.PROMPT_ID),
        projection,
        registry=registry,
        execution_scope=EVALUATION,
    )
    result["prompt"] = json.dumps(body, ensure_ascii=False, sort_keys=True)
    result["format"] = deepcopy(body["output_schema"])
    return result


def _output(
    payload: dict[str, Any], required: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    projection = json.loads(payload["prompt"])["input"]
    requirements = {"TASK": ["work-1"]} if required is None else required
    first = projection["request_tokens"][0]["token_id"]
    decisions = []
    for source in projection["source_candidates"]:
        resource = source["resource_type"]
        item: dict[str, Any] = {
            "resource_type": resource,
            "dependency": "SOURCE_NOT_REQUIRED",
        }
        if resource in requirements:
            item.update(
                dependency="SOURCE_REQUIRED",
                required_information=[source["owned_fact_kinds"][0]],
                target_scope="CRITERIA",
                work_unit_ids=requirements[resource],
                source_request_ranges=[{"start_token_id": first, "end_token_id": first}],
            )
        decisions.append(item)
    return {"source_dependencies": decisions}


def _required(value: dict[str, Any]) -> dict[str, Any]:
    return next(i for i in value["source_dependencies"] if i["dependency"] == "SOURCE_REQUIRED")


def _admit(payload: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    return candidate.admit_source(json.dumps(value, ensure_ascii=False), payload)


def test_build_payload__current_first__preserves_context_role_and_runtime(
    product_wire: dict[str, Any],
) -> None:
    original = deepcopy(product_wire)
    result = candidate.build_payload(product_wire)
    before, after = json.loads(original["prompt"]), json.loads(result["prompt"])
    assert {k: v for k, v in after["input"].items() if k != "request_tokens"} == before["input"]
    assert result["format"] == after["output_schema"]
    assert {k: v for k, v in result.items() if k not in {"system", "prompt", "format"}} == {
        k: v for k, v in original.items() if k not in {"system", "prompt", "format"}
    }
    role = PromptRegistry().source_text(candidate.PROMPT_ID).rstrip()
    candidate_role = role + "\n\n" + candidate.DECLARATION
    assert (
        after["prompt_ref"]["content_hash"] == hashlib.sha256(candidate_role.encode()).hexdigest()
    )
    assert result["system"].startswith(candidate_role + "\n\n")
    assert result["system"].endswith(
        json.dumps(after["input"], ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )
    # Erasing only the new structural field reproduces the original Product schema.
    schema = deepcopy(after["output_schema"])
    variant = schema["properties"]["source_dependencies"]["items"]["oneOf"][1]
    variant["required"].remove("source_request_ranges")
    del variant["properties"]["source_request_ranges"]
    assert schema == before["output_schema"]
    result["options"]["seed"] = 1
    assert product_wire == original


@pytest.mark.parametrize("drift", ["system", "format", "ref", "catalog", "schema", "extra"])
def test_build_payload__changed_product_authority__rejects(
    product_wire: dict[str, Any], drift: str
) -> None:
    body = json.loads(product_wire["prompt"])
    if drift == "system":
        product_wire["system"] += "changed"
    elif drift == "format":
        product_wire["format"] = {}
    elif drift == "ref":
        body["prompt_ref"]["content_hash"] = "changed"
    elif drift == "catalog":
        body["input"]["source_candidates"][0]["read_tool_ids"] = ["unknown"]
    elif drift == "schema":
        body["output_schema"] = {}
    else:
        body["input"]["case_id"] = "not-model-input"
    product_wire["prompt"] = json.dumps(body)
    with pytest.raises(ValueError):
        candidate.build_payload(product_wire)


def test_admit_source__token_ranges__reconstructs_exact_offsets(
    product_wire: dict[str, Any],
) -> None:
    request = "\t작업  목록의 제목과 상태를 알려줘.\n새 작업은 만들지 마.  "
    payload = candidate.build_payload(_reassemble(product_wire, request))
    output = _output(payload)
    _required(output)["source_request_ranges"] = [
        {"start_token_id": "t001", "end_token_id": "t003"},
    ]
    before = deepcopy(output)
    admitted = _admit(payload, output)
    assert admitted["validation"]["structural_result"] == "VALIDATED"
    assert admitted["semantic_verdict"] == "NOT_REVIEWED"
    assert admitted["source_artifacts"]["items"][0]["request_provenance"] == [
        {
            "source": "USER_REQUEST",
            "start_offset": 1,
            "end_offset": request.index(" 상태를"),
            "source_text": "작업  목록의 제목과",
        }
    ]
    assert admitted["artifact_sha256"] == object_hash(admitted["source_artifacts"])
    assert admitted["validation"]["validated_output"] == output == before
    assert "source_request_ranges" not in _required(admitted["validated_source"])


@pytest.mark.parametrize(
    "drift",
    [
        "unknown_token",
        "reversed",
        "empty_ranges",
        "empty_token",
        "work",
        "source",
        "negative_extra",
    ],
)
def test_admit_source__invalid_ranges_or_closed_fields__rejects_without_repair(
    product_wire: dict[str, Any], drift: str
) -> None:
    payload = candidate.build_payload(product_wire)
    output = _output(payload)
    item = _required(output)
    if drift == "unknown_token":
        item["source_request_ranges"][0]["start_token_id"] = "t999"
    elif drift == "reversed":
        item["source_request_ranges"] = [{"start_token_id": "t003", "end_token_id": "t001"}]
    elif drift == "empty_ranges":
        item["source_request_ranges"] = []
    elif drift == "empty_token":
        item["source_request_ranges"][0]["start_token_id"] = ""
    elif drift == "work":
        item["work_unit_ids"] = ["foreign-work"]
    elif drift == "source":
        item["resource_type"] = "UNKNOWN_SOURCE"
    else:
        negative = next(
            i for i in output["source_dependencies"] if i["dependency"] == "SOURCE_NOT_REQUIRED"
        )
        negative["source_request_ranges"] = [{"start_token_id": "t001", "end_token_id": "t001"}]
    before = deepcopy(output)
    admitted = _admit(payload, output)
    expected = "OWNER_REJECTED" if drift == "reversed" else "INVALID_SCHEMA"
    assert admitted["validation"]["structural_result"] == expected
    assert admitted["validated_source"] is None
    assert admitted["source_artifacts"] is None
    assert output == before


def test_build_payload__empty_request__rejects_without_invented_token(
    product_wire: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        candidate.build_payload(_reassemble(product_wire, " \n\t"))


def test_admit_source__new_output_span__preserves_semantic_error_as_unreviewed(
    product_wire: dict[str, Any],
) -> None:
    request = "기존 작업들을 확인하고 새 작업을 만들어줘."
    payload = candidate.build_payload(_reassemble(product_wire, request))
    output = _output(payload)
    _required(output)["source_request_ranges"] = [
        {"start_token_id": "t004", "end_token_id": "t006"}
    ]
    admitted = _admit(payload, output)
    assert admitted["validation"]["structural_result"] == "VALIDATED"
    assert admitted["semantic_verdict"] == "NOT_REVIEWED"
    assert admitted["source_artifacts"]["items"][0]["request_provenance"][0]["source_text"] == (
        "새 작업을 만들어줘."
    )
    assert _required(admitted["validated_source"])["dependency"] == "SOURCE_REQUIRED"


def _connected_fixture(product_wire: dict[str, Any]) -> dict[str, Any]:
    request = "Garnet 메일을 요약하고 같은 메일의 기한을 정리해줘."
    boundary = request.index("같은")
    payload = candidate.build_payload(
        _reassemble(
            product_wire,
            request,
            work_ids=("work-1", "work-2"),
            work_spans=((0, boundary - 1), (boundary, len(request))),
        )
    )
    projection = json.loads(payload["prompt"])["input"]
    admission = _admit(
        payload,
        _output(
            payload,
            {
                "GMAIL_THREAD": ["work-1"],
                "GMAIL_MESSAGE": ["work-2"],
            },
        ),
    )
    assert admission["validation"]["structural_result"] == "VALIDATED"
    intent: Any = request_intent()
    intent["goal"] = request
    intent["requested_work"] = deepcopy(projection["requested_work"])
    intent["constraints"] = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": "Garnet",
            "work_unit_ids": ["work-1", "work-2"],
            "provenance": {"source": "USER_REQUEST", "start_offset": 0, "end_offset": 6},
        }
    ]
    return {"projection": projection, "admission": admission, "intent": intent}


def _merge(state: dict[str, Any]) -> dict[str, Any]:
    intent = deepcopy(state["intent"])
    intent["resource_responsibilities"] = merge_resource_responsibilities(
        source_decisions=state["admission"]["validated_source"],
        source_candidates=tuple(state["projection"]["source_candidates"]),
        output_decisions={"output_responsibilities": []},
        output_candidates=(),
    )
    return {**state, "intent": intent}


def _bind(state: dict[str, Any]) -> dict[str, Any]:
    semantic = _resource_responsibility_candidate(state["intent"])
    assert semantic is not None
    ids = iter(f"route-{n}" for n in range(20))
    routes = bind_registry_candidates(
        candidate=semantic,
        tool_catalog=load_development_tool_registry(),
        id_factory=lambda: next(ids),
    )
    return {**state, "input_routes": list(routes.input_routes)}


def _query(state: dict[str, Any]) -> dict[str, Any]:
    query = initial_retrieval_planner_input(
        user_request=state["projection"]["user_request"],
        request_intent=state["intent"],
        input_routes=state["input_routes"],
        retrieval_budget=RetrievalBudget(),
    )
    projected = candidate.project_query_context(
        cast(dict[str, Any], query),
        state["admission"],
        requested_work=state["projection"]["requested_work"],
        input_routes=state["input_routes"],
        source_input={k: v for k, v in state["projection"].items() if k != "request_tokens"},
    )
    return {**state, "query": query, "projected": projected}


def test_compiled_projection__shared_read__preserves_work_union_and_anchors(
    product_wire: dict[str, Any],
) -> None:
    initial = _connected_fixture(product_wire)
    before = deepcopy(initial)
    graph: Any = StateGraph(cast(Any, dict[str, Any]))
    graph.add_node("merge", _merge)
    graph.add_node("bind", _bind)
    graph.add_node("query", _query)
    graph.add_edge(START, "merge")
    graph.add_edge("merge", "bind")
    graph.add_edge("bind", "query")
    graph.add_edge("query", END)
    result = graph.compile().invoke(initial)
    query, projected = result["query"], result["projected"]
    assert initial == before
    assert len(result["input_routes"]) == len(query["input_routes"]) == 1
    assert result["input_routes"][0]["resource_type"] == "GMAIL_THREAD"
    assert query["input_routes"][0]["resource_type"] == "EMAIL"
    assert query["input_routes"][0]["work_unit_ids"] == ["work-1", "work-2"]
    assert {k: v for k, v in projected.items() if k != "source_request_context"} == query
    assert query["required_user_anchors"][0]["keyword_terms"] == ["Garnet"]
    assert len(projected["source_request_context"]) == 1
    sources = projected["source_request_context"][0]["sources"]
    assert sources == result["admission"]["source_artifacts"]["items"]
    assert {i["source_item"]["resource_type"] for i in sources} == {
        "GMAIL_THREAD",
        "GMAIL_MESSAGE",
    }
    assert result["admission"]["semantic_verdict"] == "NOT_REVIEWED"


@pytest.mark.parametrize(
    "drift",
    [
        "request",
        "artifact",
        "work",
        "owner_output",
        "route_work",
        "route_id",
        "coarse_type",
        "selected_identity",
        "intent_work",
        "intent_source",
        "duplicate_route",
        "already_bound",
    ],
)
def test_project_query_context__stale_or_corrupt_binding__rejects(
    product_wire: dict[str, Any], drift: str
) -> None:
    state = _bind(_merge(_connected_fixture(product_wire)))
    query = initial_retrieval_planner_input(
        user_request=state["projection"]["user_request"],
        request_intent=state["intent"],
        input_routes=state["input_routes"],
        retrieval_budget=RetrievalBudget(),
    )
    work = deepcopy(state["projection"]["requested_work"])
    admission = deepcopy(state["admission"])
    source_input = {k: v for k, v in deepcopy(state["projection"]).items() if k != "request_tokens"}
    if drift == "request":
        query["user_request"] = "Changed current request"
    elif drift == "artifact":
        admission["source_artifacts"]["items"][0]["request_provenance"][0]["source_text"] = "forged"
    elif drift == "work":
        work["work_units"][0]["unit_id"] = "different-work"
    elif drift == "owner_output":
        _required(admission["validated_source"])["required_information"] = ["different fact"]
    elif drift == "route_work":
        cast(Any, query["input_routes"])[0]["work_unit_ids"] = ["work-1"]
    elif drift == "route_id":
        cast(Any, query["input_routes"])[0]["route_id"] = "unknown-route"
    elif drift == "coarse_type":
        cast(Any, query["input_routes"])[0]["resource_type"] = "TASK"
    elif drift == "selected_identity":
        source_input["selected_resource_refs"] = ["gmail_thread:another-selected-identity"]
    elif drift == "intent_work":
        cast(Any, query["request_intent"])["requested_work"]["work_relations"] = [
            {"unexpected": "changed relationship"}
        ]
    elif drift == "intent_source":
        cast(Any, query["request_intent"])["resource_responsibilities"]["source_reads"][0][
            "target_scope"
        ] = "SINGULAR"
    elif drift == "duplicate_route":
        cast(Any, query["input_routes"]).append(deepcopy(cast(Any, query["input_routes"])[0]))
    else:
        query["source_request_context"] = []
    before = deepcopy((query, admission, work, state["input_routes"], source_input))
    with pytest.raises(ValueError):
        candidate.project_query_context(
            cast(dict[str, Any], query),
            admission,
            requested_work=work,
            input_routes=state["input_routes"],
            source_input=source_input,
        )
    assert (query, admission, work, state["input_routes"], source_input) == before


def test_admit_source__no_source__retains_empty_artifacts_without_invention(
    product_wire: dict[str, Any],
) -> None:
    payload = candidate.build_payload(product_wire)
    output = _output(payload, {})
    admitted = _admit(payload, output)
    assert admitted["validation"]["structural_result"] == "VALIDATED"
    assert admitted["validated_source"] == output
    assert admitted["source_artifacts"]["items"] == []
    assert admitted["semantic_verdict"] == "NOT_REVIEWED"


@pytest.mark.parametrize("field", ["request_tokens", "output_schema", "format"])
def test_admit_source__modified_frozen_contract__rejects(
    product_wire: dict[str, Any], field: str
) -> None:
    payload = candidate.build_payload(product_wire)
    output = _output(payload)
    body = json.loads(payload["prompt"])
    if field == "request_tokens":
        body["input"]["request_tokens"][0]["text"] = "rewritten"
    elif field == "output_schema":
        body["output_schema"] = {}
    else:
        payload["format"] = {}
    payload["prompt"] = json.dumps(body)
    with pytest.raises(ValueError, match="drift"):
        _admit(payload, output)
