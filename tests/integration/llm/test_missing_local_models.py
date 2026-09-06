"""Real production composition; only the external Ollama transport is fake."""

from pathlib import Path

import pytest
from tests.support.fakes import FakeOllamaTransport
from tests.support.production_runtime import build_test_production_container

from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.api import composition
from google_work_agent.application.agents.request_understanding.identify_goal import (
    IDENTIFY_GOAL_OUTPUT_SCHEMA,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    load_prompt_reference,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)
from google_work_agent.ports.system.readiness_port import ReadinessState


def test_no_local_models__preserves_core_readiness__and_blocks_inference_before_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transport = FakeOllamaTransport()
    monkeypatch.setattr(composition, "OllamaHTTPClient", lambda: transport)
    container = build_test_production_container(
        runtime_root=tmp_path, keyring_store=SessionMemorySecretStore()
    )
    try:
        runtime = container.structured_inference_port
        assert runtime is not None
        assert container.readiness_aggregator.evaluate().state is ReadinessState.READY
        assert runtime.status_service.get_status("LOCAL_GPU").availability != "READY"
        assert all(
            not model.installed and not model.approved
            for model in runtime.status_service.list_local_models()
        )
        with pytest.raises(LLMInvocationError) as failure:
            runtime.infer(
                "LOCAL_GPU",
                load_prompt_reference(
                    "request_understanding.identify_goal", execution_scope=DEVELOPMENT_SMOKE
                ),
                {"user_request": "회의 준비 방법을 설명해 줘", "selected_resource_refs": []},
                IDENTIFY_GOAL_OUTPUT_SCHEMA,
            )
        assert failure.value.code in {
            LLMErrorCode.LOCAL_UNAVAILABLE,
            LLMErrorCode.MODEL_NOT_APPROVED,
        }
        assert not [call for call in transport.invocations if call["kind"] != "probe"]
        assert container.readiness_aggregator.evaluate().state is ReadinessState.READY
    finally:
        for close in reversed(container.shutdown_callbacks):
            close()
