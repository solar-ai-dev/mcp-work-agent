from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from google_work_agent.application.agents.retrieval.build_query import RouteConstraintPolicy
from google_work_agent.application.agents.retrieval.plan_query import plan_query
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1


def test_plan_query_is__the_only_product_prompt__owner_in_retrieval_core() -> None:
    owner = (
        Path(__file__).resolve().parents[5] / "src/google_work_agent/application/agents/retrieval"
    )
    plan_source = (owner / "plan_query.py").read_text(encoding="utf-8")
    assert "StructuredInferencePort" in plan_source
    assert "PromptReference" in plan_source
    for operation in (
        "build_query.py",
        "execute_read.py",
        "normalize_segments.py",
        "resolve_availability.py",
        "rag_retrieve_rerank.py",
    ):
        source = (owner / operation).read_text(encoding="utf-8")
        assert "PromptReference" not in source
        assert "StructuredInferencePort" not in source


class _OmittingRepositoryInference:
    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        del requested_mode, prompt_ref, input_projection, output_schema_ref
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output={
                "schema_version": 2,
                "route_queries": [
                    {
                        "route_id": "route-1",
                        "operation": "SEARCH",
                        "reason_codes": ["USER_REQUEST"],
                        "search_spec": {"mode": "INITIAL", "constraints": []},
                        "detail_candidate_ref": None,
                    }
                ],
                "required_information": ["issues"],
                "retrieval_order": ["route-1"],
            },
            provider="fake",
            model="fake",
            actual_runtime="API_LLM",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            fallback_reason=None,
        )


def test_plan_query__validated_required_repository__binds_before_semantic_validation() -> None:
    prompt = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="ACTIVE",
        purpose="test",
        input_schema_version="1",
        output_schema_version="2",
    )
    schema = OutputSchemaDefinition(schema_version="test", json_schema={})
    route: InputToolRouteV1 = {
        "route_id": "route-1",
        "connector_id": "github",
        "resource_type": "GITHUB_ISSUE",
        "allowed_read_tool_ids": ["github_list_issues"],
        "required": True,
        "reason_codes": ["USER_REQUEST"],
    }

    result, _ = plan_query(
        llm_runtime=_OmittingRepositoryInference(),
        prompt_ref=prompt,
        revision_prompt_ref=prompt,
        output_schema=schema,
        prompt_input={},
        requested_mode="AUTO",
        frozen_routes=[route],
        route_policies={
            "route-1": RouteConstraintPolicy(
                supported_kinds=frozenset({"CONTAINER_REF", "STATUS_SCOPE"}),
                required_kinds=frozenset({"CONTAINER_REF"}),
            )
        },
        retry_budget=build_default_run_budget(),
        validated_container_refs={"route-1": ["acme/repo"]},
    )

    assert result["route_queries"][0]["search_spec"] == {
        "mode": "INITIAL",
        "constraints": [{"kind": "CONTAINER_REF", "container_refs": ["acme/repo"]}],
    }
