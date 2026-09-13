"""G3 RunBudgetV2: proves the budget gate is wired into a real production
node function, not just the isolated helper. request_understanding's
_classify_node is the simplest of the six SIX_ROLE_BASELINE real-LLM-call
nodes (adapters/langgraph/subgraphs/{request_understanding,context_retrieval,
work_analysis,planning,review,tool_routing}.py all follow the same
ensure_llm_call_budget-before / consume_llm_call_budget-after pattern).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import replace
from typing import Any, Literal, cast

import pytest

from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.graph import (
    RequestUnderstandingSubgraph,
)
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_responsibilities,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_dependencies,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    account_provider_dispatch,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import (
    StructuredInferenceResultV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

PROMPT_REF = PromptReference(
    prompt_bundle_version="test",
    prompt_id="request_understanding.identify_goal",
    prompt_version="v1",
    content_hash="hash",
    agent_role="request_understanding",
    subgraph_name="request_understanding",
    node_name="identify_goal",
    node_state="INITIAL",
    purpose="test",
    input_schema_version="v1",
    output_schema_version="v1",
)
SOURCE_DEPENDENCY_PROMPT_REF = replace(
    PROMPT_REF,
    prompt_id="request_understanding.identify_source_dependencies",
    purpose="identify_source_dependencies",
)
OUTPUT_RESPONSIBILITY_PROMPT_REF = replace(
    PROMPT_REF,
    prompt_id="request_understanding.identify_output_responsibilities",
    purpose="identify_output_responsibilities",
)
EFFECT_PROHIBITION_PROMPT_REF = replace(
    PROMPT_REF,
    prompt_id="request_understanding.identify_effect_prohibitions",
    purpose="identify_effect_prohibitions",
)
SOURCE_STATUS_PROMPT_REF = replace(
    PROMPT_REF,
    prompt_id="request_understanding.identify_source_status",
    purpose="identify_source_status",
)


class _NeverCalledAgent:
    """Fails the test if the Provider boundary is ever reached."""

    def invoke_structured(self, *args: object, **kwargs: object) -> Any:
        raise AssertionError("LLM runtime must not be called once the Run budget is exhausted")

    def infer(self, *args: object, **kwargs: object) -> Any:
        raise AssertionError("LLM runtime must not be called once the Run budget is exhausted")


class _FakeLlmResult:
    def __init__(self, *, structured_output_attempts: int) -> None:
        self.structured_output: dict[str, object] = {}
        self.structured_output_attempts = structured_output_attempts


class _RepairingAgent:
    """Simulates one INITIAL call that needed one SCHEMA_REPAIR attempt --
    LLMRuntimeService already folds that into structured_output_attempts=2
    (see application/llm.py's provider_calls_consumed fix)."""

    def __init__(self, *, structured_output_attempts: int) -> None:
        self._structured_output_attempts = structured_output_attempts
        self._llm_runtime = self
        self.calls = 0

    def invoke_structured(self, *args: object, **kwargs: object) -> _FakeLlmResult:
        self.calls += 1
        for _ in range(self._structured_output_attempts):
            account_provider_dispatch()
        result = _FakeLlmResult(structured_output_attempts=self._structured_output_attempts)
        result.structured_output = {
            "goal": "test goal",
            "completion_conditions": ["done"],
            "constraints": {
                "search_terms": [],
                "business_concepts": [],
                "person": [],
                "sender": [],
                "recipient": [],
                "subject": [],
                "period": [],
                "coverage_requirement": [],
                "additional_constraints": [],
            },
            "resource_responsibilities": {
                "source_reads": [
                    {"resource_type": "TASK", "required_information": ["task_identity"]}
                ],
                "outputs": [],
            },
            "analysis_requirement": "REQUIRED",
        }
        return result

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        del requested_mode, output_schema_ref
        result = self.invoke_structured()
        output = result.structured_output
        if prompt_ref.prompt_id == "request_understanding.identify_source_dependencies":
            responsibilities = cast(Mapping[str, object], output["resource_responsibilities"])
            task_source = cast(list[Mapping[str, object]], responsibilities["source_reads"])[0]
            base = cast(
                Mapping[str, object],
                input_projection.get("base_projection", input_projection),
            )
            candidates = cast(list[Mapping[str, object]], base["source_candidates"])
            output = {
                "source_dependencies": [
                    (
                        {
                            "resource_type": candidate["resource_type"],
                            "dependency": "SOURCE_REQUIRED",
                            "required_information": task_source["required_information"],
                        }
                        if candidate["resource_type"] == "TASK"
                        else {
                            "resource_type": candidate["resource_type"],
                            "dependency": "SOURCE_NOT_REQUIRED",
                        }
                    )
                    for candidate in candidates
                ]
            }
        elif prompt_ref.prompt_id == "request_understanding.identify_output_responsibilities":
            base = cast(
                Mapping[str, object],
                input_projection.get("base_projection", input_projection),
            )
            output = {
                "output_responsibilities": [
                    {"resource_type": candidate["resource_type"], "effect": "NONE"}
                    for candidate in cast(list[Mapping[str, object]], base["output_candidates"])
                ]
            }
        elif prompt_ref.prompt_id == "request_understanding.identify_effect_prohibitions":
            base = cast(
                Mapping[str, object],
                input_projection.get("base_projection", input_projection),
            )
            output = {
                "effect_prohibitions": [
                    {
                        "effect": candidate["effect"],
                        "prohibition": "NOT_FORBIDDEN",
                    }
                    for candidate in cast(list[Mapping[str, object]], base["effect_candidates"])
                ]
            }
        elif prompt_ref.prompt_id == "request_understanding.identify_source_status":
            output = {"statuses": []}
        else:
            output = {
                key: value for key, value in output.items() if key != "resource_responsibilities"
            }
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output=output,
            provider="test-provider",
            model="test-model",
            actual_runtime="LOCAL_GPU",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            fallback_reason=None,
        )


@pytest.fixture(autouse=True)
def _isolate_provider_dispatch_budget() -> Iterator[None]:
    with provider_dispatch_execution_scope():
        yield


def _subgraph(agent: Any = None) -> RequestUnderstandingSubgraph:
    subgraph = object.__new__(RequestUnderstandingSubgraph)
    subgraph._llm_runtime = agent if agent is not None else cast(Any, _NeverCalledAgent())
    subgraph._identify_goal_prompt_ref = PROMPT_REF
    subgraph._identify_effect_prohibitions_prompt_ref = EFFECT_PROHIBITION_PROMPT_REF
    subgraph._identify_source_dependencies_prompt_ref = SOURCE_DEPENDENCY_PROMPT_REF
    subgraph._identify_output_responsibilities_prompt_ref = OUTPUT_RESPONSIBILITY_PROMPT_REF
    subgraph._identify_source_status_prompt_ref = SOURCE_STATUS_PROMPT_REF
    subgraph._source_dependency_candidates = source_dependencies.build_source_dependency_candidates(
        load_signed_tool_registry()
    )
    subgraph._output_responsibility_candidates = (
        output_responsibilities.build_output_responsibility_candidates(load_signed_tool_registry())
    )
    subgraph._graph_profile = GraphProfile.SIX_ROLE_BASELINE
    return subgraph


def _state(*, llm_calls_used: int) -> dict[str, object]:
    return {
        "run_id": "run-1",
        "__request__": WorkflowStartRequest(
            run_id="run-1",
            conversation_id="conversation-1",
            workflow_key="thread-1",
            entry_mode="AGENT_SEARCH",
            requested_mode="AUTO",
            request_text="test request",
            selected_resource_ids=(),
            run_budget=build_default_run_budget(),
            correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
        ),
        "prompt_context": {},
        "run_input": {
            "entry_mode": "AGENT_SEARCH",
            "user_request": "test request",
            "selected_resource_refs": [],
            "requested_mode": "AUTO",
        },
        "trace_context": {
            "agent_node_log": [
                {
                    "agent_subgraph_id": "request_understanding",
                    "agent_invocation_id": "ru-invocation-test",
                }
            ],
        },
        "retry_budget": {
            **build_default_run_budget(),
            "llm_calls_used": llm_calls_used,
        },
    }


def test_exhausted_budget_blocks__the_call_before_the__agent_is_ever_invoked() -> None:
    subgraph = _subgraph()
    state = _state(llm_calls_used=build_default_run_budget()["absolute_llm_call_limit"])

    with pytest.raises(LLMInvocationError) as excinfo:
        subgraph._identify_goal_node(cast(Any, state))

    assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED


def test_a_schema_repair__attempt_consumes_two__llm_calls_not_one() -> None:
    """G3: SCHEMA_REPAIR must also count against llm_calls_used. The node
    consumes provider_calls_consumed==structured_output_attempts, so a call
    that needed one repair attempt (attempts=2) must add 2, not 1."""
    agent = _RepairingAgent(structured_output_attempts=2)
    subgraph = _subgraph(agent)
    state = _state(llm_calls_used=3)

    result = subgraph._identify_goal_node(cast(Any, state))

    assert agent.calls == 5
    assert cast(dict[str, Any], result["retry_budget"])["llm_calls_used"] == 13
