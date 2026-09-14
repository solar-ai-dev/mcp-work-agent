from typing import TypedDict

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
)
from google_work_agent.application.agents.work_analysis.extract_work_facts import (
    extract_work_facts_with_budget,
)
from google_work_agent.application.use_cases.run.guard_run_budget import RunBudgetV2
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

from ..projections.extract_work_facts_projection import (
    project_extract_work_facts_input,
)


class _ExtractWorkFactsUpdate(TypedDict):
    fact_candidates: list[WorkFactV1]
    retry_budget: RunBudgetV2


def extract_work_facts_node(
    state: WorkAnalysisLocalState,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
) -> _ExtractWorkFactsUpdate:
    fact_candidates, retry_budget = extract_work_facts_with_budget(
        **project_extract_work_facts_input(state),
        llm_runtime=llm_runtime,
        prompt_ref=prompt_ref,
        requested_mode=requested_mode,
        retry_budget=state["retry_budget"],
    )
    return {
        "fact_candidates": fact_candidates,
        "retry_budget": retry_budget,
    }
