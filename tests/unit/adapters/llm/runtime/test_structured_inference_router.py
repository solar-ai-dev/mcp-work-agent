from __future__ import annotations

from dataclasses import dataclass, field, replace
from unittest.mock import Mock

import pytest
from tests.support.external_llm_scope import ExternalScopeCheckpoint
from tests.support.llm_runtime import runtime_selection, settings_view

from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.ports.llm.llm_credential_port import LlmCredentialStatus
from google_work_agent.ports.llm.llm_runtime_status_port import LlmProviderRuntimeStatus
from google_work_agent.ports.llm.local_model_profile import LocalInferenceClass, LocalModelProfileV1
from google_work_agent.ports.llm.structured_inference_contracts import (
    ActualRuntime,
    ApprovedModelInfo,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)
from google_work_agent.ports.system.hardware_probe_port import HardwareProfileV1

PROMPT = PromptReference(
    "1", "test", "1", "hash", "role", "graph", "node", "state", "test", "1", "1"
)
SCHEMA = OutputSchemaDefinition(
    "1",
    {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
        "additionalProperties": False,
    },
)


@dataclass
class _Provider:
    runtime: ActualRuntime = ActualRuntime.API_LLM
    calls: int = 0
    checkpoint_to_stale: ExternalScopeCheckpoint | None = None
    failure: LLMInvocationError | None = None
    content: object = field(default_factory=lambda: {"answer": "ok"})

    @property
    def provider_name(self) -> str:
        return "api" if self.runtime is ActualRuntime.API_LLM else "ollama"

    def invoke_structured(self, **kwargs: object) -> ProviderResponsePayload:
        del kwargs
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        if self.checkpoint_to_stale is not None:
            self.checkpoint_to_stale.scope = _scope(scope_hash="stale-after-first-call")
            return ProviderResponsePayload({}, "model", None, 1, 1, 1)
        return ProviderResponsePayload(self.content, "model", None, 1, 1, 1)


class _Status:
    def get_status(self, provider: str) -> LlmProviderRuntimeStatus:
        return LlmProviderRuntimeStatus(1, provider, True, "READY", "model", None)

    def get_approved_model(self, model_id: str) -> ApprovedModelInfo | None:
        return ApprovedModelInfo(model_id, "OLLAMA", "1", "1")

    def get_selected_model(self) -> ApprovedModelInfo:
        return ApprovedModelInfo("qwen3.5:9b", "OLLAMA", "1", "1")

    def get_model_for_prompt(self, prompt_id: str) -> ApprovedModelInfo:
        model_id = (
            "qwen3.5:4b" if prompt_id == "request_understanding.identify_goal" else "qwen3.5:9b"
        )
        return ApprovedModelInfo(model_id, "OLLAMA", "1", "1")


class _Credential:
    def get_credential_status(self, provider: str) -> LlmCredentialStatus:
        return LlmCredentialStatus(1, provider, True, "KEYRING", "VALID")

    def read_secret(self, provider: str) -> bytes:
        del provider
        return b"key"


class _Hardware:
    def probe(self) -> HardwareProfileV1:
        return HardwareProfileV1(
            1,
            8,
            16 * 1024**3,
            True,
            "gpu",
            8 * 1024**3,
            True,
            "1",
            True,
            "WINDOWS",
            "AMD64",
            (),
        )


@dataclass
class _Repairer:
    calls: int = 0
    failed_outputs: list[object] = field(default_factory=list)

    def repair(self, **kwargs: object) -> object:
        self.calls += 1
        self.failed_outputs.append(kwargs["failed_output"])
        return {"answer": "repaired"}


def _scope(*, scope_hash: str = "scope-hash") -> ExternalLlmTransferScopeV1:
    return ExternalLlmTransferScopeV1(1, "run-1", 1, scope_hash, ["user_request"], ["USER_REQUEST"])


def _router(
    *,
    checkpoint: ExternalScopeCheckpoint,
    api: _Provider,
    local: _Provider | None = None,
    consent: bool = True,
    repairer: _Repairer | None = None,
    deployment_profile: str = "LOCAL_CAPABLE",
) -> StructuredInferenceRuntimeRouter:
    settings = settings_view(preferred_llm_mode="API_LLM", external_llm_consent=consent)
    selection = runtime_selection(
        deployment_profile=deployment_profile,
        model=(
            ApprovedModelInfo("model", "OLLAMA", "1", "1")
            if deployment_profile == "LOCAL_CAPABLE"
            else None
        ),
    )
    local_provider = local or _Provider(runtime=ActualRuntime.LOCAL_GPU)
    return StructuredInferenceRuntimeRouter(
        settings_service=lambda: settings,
        runtime_selection=selection,
        status_service=_Status(),  # type: ignore[arg-type]
        credential_service=_Credential(),  # type: ignore[arg-type]
        hardware_probe=_Hardware(),
        api_provider_name="api",
        api_provider=api,
        ollama_provider_factory=lambda _model: local_provider,
        runtime_policy=RuntimePolicy(),
        checkpoint=checkpoint,  # type: ignore[arg-type]
        schema_repairer=repairer,
        run_context_provider=lambda: "run-1",
        external_scope_projector=lambda _run_id, _source_kinds, _data_classes: _scope(),
    )


def test_api_only_local_request__fails_before__either_provider_dispatch() -> None:
    checkpoint = ExternalScopeCheckpoint(scope=_scope())
    api = _Provider()
    local = _Provider(runtime=ActualRuntime.LOCAL_GPU)
    router = _router(
        checkpoint=checkpoint,
        api=api,
        local=local,
        deployment_profile="API_ONLY",
    )

    with pytest.raises(LLMInvocationError) as raised:
        router.infer("LOCAL_GPU", PROMPT, {"user_request": "hello"}, SCHEMA)

    assert raised.value.code is LLMErrorCode.RUNTIME_MODE_BLOCKED
    assert api.calls == 0
    assert local.calls == 0


def test_local_request__uses_profile__model_for_prompt() -> None:
    checkpoint = ExternalScopeCheckpoint(scope=_scope())
    local = _Provider(runtime=ActualRuntime.LOCAL_GPU)
    router = _router(checkpoint=checkpoint, api=_Provider(), local=local)
    selected: list[str] = []

    def select_local_provider(model: ApprovedModelInfo) -> _Provider:
        selected.append(model.model_id)
        return local

    router.ollama_provider_factory = select_local_provider

    router.infer(
        "LOCAL_GPU",
        replace(PROMPT, prompt_id="request_understanding.identify_goal"),
        {"user_request": "hello"},
        SCHEMA,
    )

    assert selected == ["qwen3.5:4b"]
    assert local.calls == 1


def test_local_request__with_explicit_mode__does_not_probe_api_status_or_credentials() -> None:
    router = _router(
        checkpoint=ExternalScopeCheckpoint(scope=_scope()),
        api=_Provider(),
    )
    status = Mock(wraps=router.status_service)
    credential = Mock(wraps=router.credential_service)
    router.status_service = status
    router.credential_service = credential

    router.infer("LOCAL_GPU", PROMPT, {"user_request": "hello"}, SCHEMA)

    status.get_status.assert_not_called()
    credential.get_credential_status.assert_not_called()
    credential.read_secret.assert_not_called()


def test_api_request__with_explicit_mode__does_not_inspect_local_model_or_hardware() -> None:
    api = _Provider()
    router = _router(
        checkpoint=ExternalScopeCheckpoint(scope=_scope()),
        api=api,
    )
    status = Mock(wraps=router.status_service)
    hardware = Mock(wraps=router.hardware_probe)
    router.status_service = status
    router.hardware_probe = hardware

    router.infer("API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA)

    status.get_model_for_prompt.assert_not_called()
    hardware.probe.assert_not_called()
    assert api.calls == 1


def test_local_inference_trace__actual_provider_result__includes_class_profile_and_model() -> None:
    router = _router(checkpoint=ExternalScopeCheckpoint(scope=_scope()), api=_Provider())
    router.runtime_selection = replace(
        router.runtime_selection,
        local_model_profile=LocalModelProfileV1(
            1,
            "single-9b",
            "OLLAMA",
            "qwen3.5:9b",
            "qwen3.5:9b",
            LocalInferenceClass.REASONING,
            (),
        ),
    )
    recorder = Mock()
    router.event_recorder = recorder
    result = router.infer("LOCAL_GPU", PROMPT, {"user_request": "hello"}, SCHEMA)
    calls = [call.kwargs for call in recorder.record.call_args_list]
    started = next(call["attributes"] for call in calls if call["event_name"] == "LLM_CALL_STARTED")
    completed = next(
        call["attributes"] for call in calls if call["event_name"] == "LLM_CALL_COMPLETED"
    )
    assert started["inference_class"] == completed["inference_class"] == "REASONING"
    assert started["local_model_profile_id"] == completed["local_model_profile_id"] == "single-9b"
    assert started["selected_model_id"] == completed["selected_model_id"] == "qwen3.5:9b"
    assert completed["model"] == result.model


def test_local_inference_failure__traces_selected_model__without_unsafe_detail() -> None:
    local = _Provider(
        runtime=ActualRuntime.LOCAL_GPU,
        failure=LLMInvocationError(
            LLMErrorCode.OUTPUT_SCHEMA_INVALID,
            "unsafe validator detail must not be traced",
            affected_field_paths=("$.route_queries[0].operation",),
        ),
    )
    router = _router(
        checkpoint=ExternalScopeCheckpoint(scope=_scope()),
        api=_Provider(),
        local=local,
    )
    recorder = Mock()
    router.event_recorder = recorder
    prompt = replace(PROMPT, prompt_id="request_understanding.identify_goal")

    with pytest.raises(LLMInvocationError) as raised:
        router.infer("LOCAL_GPU", prompt, {"user_request": "hello"}, SCHEMA)

    assert raised.value.code is LLMErrorCode.OUTPUT_SCHEMA_INVALID
    calls = [call.kwargs for call in recorder.record.call_args_list]
    selected = next(
        call["attributes"] for call in calls if call["event_name"] == "LLM_RUNTIME_SELECTED"
    )
    started = next(call["attributes"] for call in calls if call["event_name"] == "LLM_CALL_STARTED")
    failed = next(call["attributes"] for call in calls if call["event_name"] == "LLM_CALL_FAILED")
    assert selected["selected_model_id"] == "qwen3.5:4b"
    assert started["selected_model_id"] == failed["selected_model_id"] == "qwen3.5:4b"
    assert failed["safe_error_code"] == LLMErrorCode.OUTPUT_SCHEMA_INVALID.value
    assert failed["output_schema_id"] == SCHEMA.schema_version
    assert failed["error_type"] == "LLMInvocationError"
    assert failed["affected_field_paths"] == ["$.route_queries[0].operation"]
    assert failed["provider_dispatch_occurred"] is True
    assert "unsafe validator detail" not in repr(failed)


def test_schema_failure_trace__field_path__omits_output_value() -> None:
    local = _Provider(runtime=ActualRuntime.LOCAL_GPU, content={"answer": 42})
    router = _router(
        checkpoint=ExternalScopeCheckpoint(scope=_scope()),
        api=_Provider(),
        local=local,
    )
    recorder = Mock()
    router.event_recorder = recorder

    with pytest.raises(LLMInvocationError) as raised:
        router.infer("LOCAL_GPU", PROMPT, {"user_request": "hello"}, SCHEMA)

    assert raised.value.affected_field_paths == ("$.answer",)
    failed = next(
        call.kwargs["attributes"]
        for call in recorder.record.call_args_list
        if call.kwargs["event_name"] == "LLM_CALL_FAILED"
    )
    assert failed["affected_field_paths"] == ["$.answer"]
    assert failed["provider_dispatch_occurred"] is True
    assert "42" not in repr(failed)


@pytest.mark.parametrize("published", [None, _scope(scope_hash="different")])
def test_api_provider_is__not_called_without__exact_published_scope(
    published: ExternalLlmTransferScopeV1 | None,
) -> None:
    checkpoint = ExternalScopeCheckpoint(scope=published)
    provider = _Provider()
    with pytest.raises(LLMInvocationError):
        _router(checkpoint=checkpoint, api=provider).infer(
            "API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA
        )
    assert provider.calls == 0


def test_exact_published__scope_allows__one_api_call() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider()
    result = _router(checkpoint=checkpoint, api=provider).infer(
        "API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA
    )
    assert result.structured_output == {"answer": "ok"}
    assert provider.calls == 1


def test_runtime_circuit_callbacks__guard_and_record__the_selected_leaf() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider()
    router = _router(checkpoint=checkpoint, api=provider)
    events: list[tuple[str, ActualRuntime, str | None]] = []
    router.before_runtime_dispatch = lambda runtime: events.append(("guard", runtime, None))
    router.record_runtime_result = lambda runtime, error: events.append(("result", runtime, error))

    router.infer("API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA)

    assert events == [
        ("guard", ActualRuntime.API_LLM, None),
        ("result", ActualRuntime.API_LLM, None),
    ]


def test_json_validation__malformed_response__uses_bounded_schema_repair() -> None:
    checkpoint = ExternalScopeCheckpoint(scope=_scope())
    malformed = '{"answer":"unterminated'
    provider = _Provider(runtime=ActualRuntime.LOCAL_GPU, content=malformed)
    repairer = _Repairer()

    result = _router(
        checkpoint=checkpoint,
        api=_Provider(),
        local=provider,
        repairer=repairer,
    ).infer("LOCAL_GPU", PROMPT, {"user_request": "hello"}, SCHEMA)

    assert result.structured_output == {"answer": "repaired"}
    assert provider.calls == 1
    assert repairer.calls == 1
    assert repairer.failed_outputs == [malformed]


def test_runtime_circuit__guard_blocks__before_provider_dispatch() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider()
    router = _router(checkpoint=checkpoint, api=provider)

    def block(_runtime: ActualRuntime) -> None:
        raise LLMInvocationError(LLMErrorCode.PROVIDER_UNAVAILABLE, "circuit open")

    router.before_runtime_dispatch = block

    with pytest.raises(LLMInvocationError, match="circuit open"):
        router.infer("API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA)

    assert provider.calls == 0


def test_consent_revoke_blocks__api_call_even__with_exact_scope() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider()
    with pytest.raises(LLMInvocationError) as captured:
        _router(checkpoint=checkpoint, api=provider, consent=False).infer(
            "API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA
        )
    assert captured.value.code is LLMErrorCode.CONSENT_REQUIRED
    assert provider.calls == 0


def test_scope_is__rechecked_before_api__schema_repair_call() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider(checkpoint_to_stale=checkpoint)
    repairer = _Repairer()
    with pytest.raises(LLMInvocationError):
        _router(checkpoint=checkpoint, api=provider, repairer=repairer).infer(
            "API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA
        )
    assert provider.calls == 1
    assert repairer.calls == 0


def test_auto_fallback_does__not_call_api__without_published_scope() -> None:
    checkpoint = ExternalScopeCheckpoint()
    api = _Provider()
    local = _Provider(
        runtime=ActualRuntime.LOCAL_GPU,
        failure=LLMInvocationError(LLMErrorCode.GPU_OOM, "oom"),
    )
    with pytest.raises(LLMInvocationError):
        _router(checkpoint=checkpoint, api=api, local=local).infer(
            "AUTO", PROMPT, {"user_request": "hello"}, SCHEMA
        )
    assert local.calls == 1
    assert api.calls == 0
