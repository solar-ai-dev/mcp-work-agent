"""Measure Settings -> production Router -> Ollama through a production Graph node.

No account data or external WRITE is used. The isolated runtime uses the real
catalog, hardware probe, Prompt, schema validator, Router and Ollama transport.
This is a node/runtime measurement, not a full Conversation E2E.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import fields
from functools import partial
from io import TextIOWrapper
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Literal, cast
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.main.state import initial_graph_state
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes import (
    identify_goal_node,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.api.composition import ProductionRuntimeConfig, build_production_runtime
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_responsibilities,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_dependencies,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    load_prompt_reference,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.application.use_cases.setting.update_settings import UpdateSettingsCommand
from google_work_agent.ports.llm.local_model_profile import SELECTABLE_LOCAL_MODEL_IDS
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import (
    StructuredInferencePort,
    StructuredInferenceResultV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1


class ObservedInference:
    """Observe the typed result without changing provider or routing decisions."""

    def __init__(self, delegate: StructuredInferencePort) -> None:
        self.delegate = delegate
        self.results: list[StructuredInferenceResultV1] = []

    def infer(self, *args: Any) -> StructuredInferenceResultV1:
        result = self.delegate.infer(*args)
        self.results.append(result)
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-manifest", type=Path)
    arguments = parser.parse_args()
    _measure(
        mkdtemp(prefix="gwa-local-runtime-"),
        prompt_manifest_path=arguments.prompt_manifest,
    )


def _measure(directory: str, *, prompt_manifest_path: Path | None = None) -> None:
    config = ProductionRuntimeConfig.development(
        runtime_root=Path(directory),
        working_directory=Path(__file__).resolve().parents[1],
        mcp_manifest_version="2026-08-07.p0",
        keyring_store=SessionMemorySecretStore(),
        prompt_manifest_path=prompt_manifest_path,
    )
    container = build_production_runtime(
        **{field.name: getattr(config, field.name) for field in fields(config)},
        bootstrap_secret=uuid4().hex,
        service_instance_id=f"measurement-{uuid4()}",
    )
    try:
        runtime = container.structured_inference_port
        assert runtime is not None
        assert container.llm_runtime_selection is not None
        assert container.update_settings_handler is not None
        # No durable Run is created by this node-only measurement. Preserve
        # production event recording as diagnostic events, without a fake FK.
        runtime.run_context_provider = lambda: None
        observed = ObservedInference(runtime)

        def prompt_reference(prompt_id: str) -> PromptReference:
            return load_prompt_reference(
                prompt_id,
                manifest_path=prompt_manifest_path,
                execution_scope=DEVELOPMENT_SMOKE,
            )

        prompt = prompt_reference("request_understanding.identify_goal")
        tool_catalog = load_signed_tool_registry()
        node = partial(
            identify_goal_node.identify_goal_node,
            llm_runtime=observed,
            prompt_ref=prompt,
            effect_prohibition_prompt_ref=prompt_reference(
                "request_understanding.identify_effect_prohibitions"
            ),
            source_dependency_prompt_ref=prompt_reference(
                "request_understanding.identify_source_dependencies"
            ),
            output_responsibility_prompt_ref=prompt_reference(
                "request_understanding.identify_output_responsibilities"
            ),
            source_status_prompt_ref=prompt_reference(
                "request_understanding.identify_source_status"
            ),
            source_dependency_candidates=source_dependencies.build_source_dependency_candidates(
                tool_catalog
            ),
            output_responsibility_candidates=(
                output_responsibilities.build_output_responsibility_candidates(tool_catalog)
            ),
        )
        profile = container.llm_runtime_selection.local_model_profile
        builder = StateGraph(RequestUnderstandingStateV2)
        builder.add_node("identify_goal", lambda state: node(state))
        builder.add_edge(START, "identify_goal")
        builder.add_edge("identify_goal", END)
        graph = builder.compile()
        for model in SELECTABLE_LOCAL_MODEL_IDS:
            container.update_settings_handler(
                UpdateSettingsCommand(
                    str(uuid4()),
                    SettingsPatchV1(
                        schema_version=1,
                        preferred_local_model_id=cast(Literal["qwen3.5:9b", "qwen3.5:4b"], model),
                        preferred_llm_mode="LOCAL_GPU",
                        external_llm_consent=False,
                    ),
                )
            )
            request = WorkflowStartRequest(
                run_id=str(uuid4()),
                conversation_id=str(uuid4()),
                workflow_key=str(uuid4()),
                entry_mode="AGENT_SEARCH",
                requested_mode="LOCAL_GPU",
                request_text="일반적인 회의 준비 방법을 간단히 설명해 줘. 외부 자료는 조회하지 마.",
                selected_resource_ids=(),
                correlation=WorkflowCorrelationContext(str(uuid4()), None, "1"),
                run_budget=build_default_run_budget(started_at_ms=int(time.time() * 1000)),
            )
            state = initial_graph_state(
                request,
                graph_profile=GraphProfile.SIX_ROLE_BASELINE,
                graph_version="local-runtime-measurement",
                initial_target="request.identify_goal",
            )
            with provider_dispatch_execution_scope(
                run_id=request.run_id, now_ms=lambda: int(time.time() * 1000)
            ):
                updates = list(
                    graph.stream(cast(RequestUnderstandingStateV2, state), stream_mode="updates")
                )
            result = observed.results[-1]
            final = updates[-1]["identify_goal"]
            assert result.model == model and result.actual_runtime == "LOCAL_GPU"
            assert result.provider == "ollama" and result.fallback_reason is None
            assert final["goal_candidate"]["requested_effect_hints"] == []
            assert final["goal_candidate"]["requested_resource_hints"] == []
            print(
                json.dumps(
                    {
                        "model": model,
                        "actual_model": result.model,
                        "actual_runtime": result.actual_runtime,
                        "inference_class": profile.inference_class_for_prompt(
                            prompt.prompt_id
                        ).value,
                        "prompt": prompt.prompt_id,
                        "prompt_hash": prompt.content_hash,
                        "path": [
                            "START",
                            *[name for update in updates for name in update],
                            "END",
                        ],
                        "provider_calls": final["retry_budget"]["llm_calls_used"],
                        "latency_ms": result.latency_ms,
                        "final_typed_result": final["goal_candidate"],
                        "external_llm_consent": False,
                        "connector_calls": 0,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    finally:
        for close in reversed(container.shutdown_callbacks):
            close()
        print(json.dumps({"diagnostic_runtime_root": directory}), flush=True)


if __name__ == "__main__":
    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
