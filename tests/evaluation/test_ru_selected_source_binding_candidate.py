"""Exact-selected component tests: real Registry/Query/READ consumer, fake Connector."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from itertools import count
from typing import Any, cast
from unittest.mock import patch

import pytest
from scripts import ru_selected_source_binding_candidate as candidate
from scripts.ru_source_requirements_candidate import build_source_requirements_output_schema

from google_work_agent.adapters.system.memory.run_retrieval_cache import InMemoryRunRetrievalCache
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.agents.retrieval.execute_read import execute_read
from google_work_agent.application.agents.tool_routing.validate_route import validate_route
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1, JsonValue
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef

_CATALOG = load_development_tool_registry()
_SOURCES = source_ops.build_source_dependency_candidates(_CATALOG)
_WORKS = ("work-1", "work-2")
_REFS = (
    SelectedResourceRef("selected-alpha", "google_workspace", "gmail_thread", "thread-a"),
    SelectedResourceRef("selected-beta", "google_workspace", "gmail_thread", "thread-b"),
)


def _requirement(ref: str, *works: str, information: str = "subject") -> dict[str, Any]:
    return {
        "required_information": [information],
        "target_scope": "SINGULAR",
        "work_unit_ids": list(works),
        "selected_resource_ref_ids": [ref],
    }


def _value(*requirements: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_dependencies": [
            {
                "resource_type": item["resource_type"],
                "dependency": "SOURCE_REQUIRED",
                "requirements": deepcopy(list(requirements)),
            }
            if item["resource_type"] == "GMAIL_THREAD" and requirements
            else {"resource_type": item["resource_type"], "dependency": "SOURCE_NOT_REQUIRED"}
            for item in _SOURCES
        ]
    }


def _build(value: object, refs: tuple[SelectedResourceRef, ...] = _REFS) -> Any:
    sequence = count()
    return candidate.build_selected_source_handoff(
        value,
        source_candidates=_SOURCES,
        work_unit_ids=_WORKS,
        selected_resources=refs,
        tool_catalog=_CATALOG,
        id_factory=lambda: f"route-{next(sequence)}",
    )


class _Reader:
    def __init__(self) -> None:
        self.calls: list[dict[str, JsonValue]] = []

    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        assert binding.effect == "READ"
        self.calls.append(dict(tool_arguments))
        return ConnectorReadResultV1(
            1,
            binding.tool_id,
            f"fake-{len(self.calls)}",
            {"item": {"resource_id": tool_arguments["thread_id"]}},
            None,
            1,
        )


@pytest.mark.parametrize("shared", [True, False], ids=["one-identity", "two-identities"])
def test_closed_bindings_reach_existing_query_and_read_consumer_without_cross_product(
    shared: bool,
) -> None:
    value = _value(
        _requirement("selected-alpha", "work-1", information="message_history"),
        _requirement("selected-alpha" if shared else "selected-beta", "work-2"),
    )
    original = deepcopy(value)
    with patch.object(
        candidate, "registry_candidates_for_route", wraps=candidate.registry_candidates_for_route
    ) as lookup:
        result = _build(value, (_REFS[0],) if shared else _REFS)
    assert lookup.call_count == 1
    expected_count = 1 if shared else 2
    routes = [item.route for item in result.acquisitions]
    assert len(routes) == len(result.fetch_plans) == expected_count
    assert [route["work_unit_ids"] for route in routes] == (
        [list(_WORKS)] if shared else [["work-1"], ["work-2"]]
    )
    assert result.requirements[0].required_information == ("message_history",)
    assert result.requirements[1].required_information == ("subject",)
    assert [item.work_unit_ids for item in result.requirements] == [("work-1",), ("work-2",)]
    assert all(query["operation"] == "DETAIL_FETCH" for query in result.query_plan["route_queries"])
    # The existing Product shape validates unchanged; the candidate binding is an
    # explicit evaluation envelope, not a hidden extra field in Product V3.
    validate_route(
        {
            "schema_version": 2,
            "tool_registry_version": _CATALOG.contract_version,
            "input_plan": {
                "schema_version": 1,
                "meta": {
                    "artifact_id": "in",
                    "revision": 1,
                    "based_on": [{"artifact_id": "intent", "revision": 1}],
                },
                "input_routes": routes,
            },
            "output_plan": {
                "schema_version": 1,
                "meta": {
                    "artifact_id": "out",
                    "revision": 1,
                    "based_on": [{"artifact_id": "intent", "revision": 1}],
                },
                "output_mode": "ANSWER",
            },
        },
        tool_catalog=_CATALOG,
    )
    reader = _Reader()
    cache = InMemoryRunRetrievalCache()
    budget = build_default_run_budget()
    binding = _CATALOG.bind_required("google_workspace", "gmail_get_thread", "READ")
    for index, fetch in enumerate(result.fetch_plans):
        identity = result.exact_bindings["identities_by_ref"][fetch["detail_candidate_ref"]]
        execution = execute_read(
            plan=fetch,
            run_id="selected-component",
            binding=binding,
            tool_arguments={"thread_id": identity["resource_id"]},
            connector_reader=reader,
            read_result_cache=cache,
            read_result_handle=f"read-{index}",
            run_budget=budget,
            now_ms=0,
            prior_query_attempts=[],
        )
        assert execution.status == "COMPLETE"
    assert reader.calls == (
        [{"thread_id": "thread-a"}]
        if shared
        else [{"thread_id": "thread-a"}, {"thread_id": "thread-b"}]
    )
    assert budget["connector_calls_used"] == expected_count
    assert value == original


def test_one_work_with_two_distinct_selected_targets_is_not_merged_by_old_source_normalizer() -> (
    None
):
    result = _build(
        _value(
            _requirement("selected-alpha", "work-1"),
            _requirement("selected-beta", "work-1"),
        )
    )
    assert len(result.requirements) == len(result.acquisitions) == 2
    assert [item.route["work_unit_ids"] for item in result.acquisitions] == [["work-1"], ["work-1"]]
    assert [item.identity.resource_id for item in result.acquisitions] == ["thread-a", "thread-b"]


def test_unbound_selection_fails_closed_instead_of_expanding_another_source_binding() -> None:
    with pytest.raises(ValueError, match="no explicit Source WorkUnit binding"):
        _build(_value(_requirement("selected-beta", "work-2")))


def test_one_selected_identity_retains_only_its_explicit_work_binding() -> None:
    result = _build(_value(_requirement("selected-beta", "work-2")), (_REFS[1],))
    assert len(result.acquisitions) == 1
    assert result.acquisitions[0].route["work_unit_ids"] == ["work-2"]
    assert result.acquisitions[0].identity.resource_id == "thread-b"


def test_all_not_required_cannot_bypass_current_selected_read_requirement() -> None:
    with pytest.raises(ValueError):
        _build(_value())


def test_alias_refs_share_acquisition_without_losing_ref_membership() -> None:
    refs = (_REFS[0], replace(_REFS[0], resource_ref_id="alias"))
    result = _build(
        _value(
            _requirement("selected-alpha", "work-1"),
            _requirement("alias", "work-2"),
        ),
        refs,
    )
    assert len(result.acquisitions) == 1
    assert result.acquisitions[0].selected_resource_ref_ids == ("selected-alpha", "alias")
    assert result.acquisitions[0].route["work_unit_ids"] == list(_WORKS)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-ref",
        "empty-ref",
        "unknown-ref",
        "native-id-instead-of-ref",
        "duplicate-ref",
        "unknown-work",
        "empty-work",
        "duplicate-resource",
        "duplicate-requirement",
        "empty-information",
        "mixed-discovery",
        "write-field",
        "not-required-payload",
    ],
)
def test_invalid_or_out_of_scope_candidate_fails_before_route_or_read(mutation: str) -> None:
    value = _value(_requirement("selected-alpha", "work-1"))
    decision = next(item for item in value["source_dependencies"] if "requirements" in item)
    requirement = decision["requirements"][0]
    if mutation == "missing-ref":
        del requirement["selected_resource_ref_ids"]
    elif mutation == "empty-ref":
        requirement["selected_resource_ref_ids"] = []
    elif mutation == "unknown-ref":
        requirement["selected_resource_ref_ids"] = ["other-run"]
    elif mutation == "native-id-instead-of-ref":
        requirement["selected_resource_ref_ids"] = ["thread-a"]
    elif mutation == "duplicate-ref":
        requirement["selected_resource_ref_ids"] *= 2
    elif mutation == "unknown-work":
        requirement["work_unit_ids"] = ["work-3"]
    elif mutation == "empty-work":
        requirement["work_unit_ids"] = []
    elif mutation == "duplicate-resource":
        value["source_dependencies"].append(deepcopy(decision))
    elif mutation == "duplicate-requirement":
        decision["requirements"].append(deepcopy(requirement))
    elif mutation == "empty-information":
        requirement["required_information"] = [" []{} "]
    elif mutation == "mixed-discovery":
        requirement["target_scope"] = "CRITERIA"
    elif mutation == "write-field":
        requirement["effect"] = "SEND"
    elif mutation == "not-required-payload":
        decision["dependency"] = "SOURCE_NOT_REQUIRED"
    with patch.object(candidate, "registry_candidates_for_route") as lookup:
        with pytest.raises(ValueError):
            _build(value)
        lookup.assert_not_called()


@pytest.mark.parametrize(
    "mutation", ["wrong-resource", "wrong-connector", "duplicate-id", "no-selection"]
)
def test_selected_authority_mismatch_is_not_repaired_by_guessing(mutation: str) -> None:
    refs: tuple[SelectedResourceRef, ...] = (_REFS[0],)
    expected = "unique"
    if mutation == "wrong-resource":
        refs = (replace(_REFS[0], resource_type="gmail_draft"),)
        expected = "resource does not match"
    elif mutation == "wrong-connector":
        refs = (replace(_REFS[0], connector_id="other-account-connector"),)
        expected = "connector does not match"
    elif mutation == "duplicate-id":
        refs = (_REFS[0], replace(_REFS[1], resource_ref_id=_REFS[0].resource_ref_id))
    elif mutation == "no-selection":
        refs = ()
        expected = "requires current-Run selected refs"
    with pytest.raises(ValueError, match=expected):
        _build(_value(_requirement("selected-alpha", "work-1")), refs)


def test_cross_route_exact_ref_substitution_is_rejected_by_existing_query_validator() -> None:
    result = _build(
        _value(
            _requirement("selected-alpha", "work-1"),
            _requirement("selected-beta", "work-2"),
        )
    )
    tampered = deepcopy(result.query_plan)
    tampered["route_queries"][0]["detail_candidate_ref"] = "gmail_thread:thread-b"
    with pytest.raises(RetrievalV2ValidationError, match="validated candidate or exact-resource"):
        validate_retrieval_query_plan_v2(
            tampered,
            frozen_routes=[item.route for item in result.acquisitions],
            supported_constraint_kinds={},
            validated_resource_refs=result.exact_bindings["refs_by_route"],
        )


def test_ambiguous_product_ref_parent_collision_fails_closed_instead_of_overwriting_identity() -> (
    None
):
    refs = (_REFS[0], replace(_REFS[0], resource_ref_id="other-parent", parent_resource_id="other"))
    with pytest.raises(ValueError, match="cannot distinguish these parents"):
        _build(
            _value(
                _requirement("selected-alpha", "work-1"),
                _requirement("other-parent", "work-2"),
            ),
            refs,
        )


def test_duplicate_route_ids_are_not_accepted() -> None:
    with pytest.raises(ValueError, match="route ids must be non-empty and unique"):
        candidate.build_selected_source_handoff(
            _value(
                _requirement("selected-alpha", "work-1"), _requirement("selected-beta", "work-2")
            ),
            source_candidates=_SOURCES,
            work_unit_ids=_WORKS,
            selected_resources=_REFS,
            tool_catalog=_CATALOG,
            id_factory=lambda: "duplicate",
        )


def test_candidate_schema_only_adds_closed_ref_without_mutating_existing_requirements_schema() -> (
    None
):
    base = build_source_requirements_output_schema(
        _SOURCES,
        work_unit_ids=_WORKS,
        require_at_least_one_source=True,
    )
    original = deepcopy(base.json_schema)
    modified = candidate.build_selected_source_output_schema(
        _SOURCES,
        work_unit_ids=_WORKS,
        selected_resources=_REFS,
    )
    shape = cast(dict[str, Any], deepcopy(modified.json_schema))
    required = shape["properties"]["source_dependencies"]["items"]["oneOf"][1]
    item = required["properties"]["requirements"]["items"]
    item["required"].remove("selected_resource_ref_ids")
    del item["properties"]["selected_resource_ref_ids"]
    assert shape == original == base.json_schema
