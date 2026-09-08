from dataclasses import dataclass, replace

import pytest

from google_work_agent.adapters.llm.runtime.local_model_selection import (
    LocalModelSelectionResolver,
)
from google_work_agent.ports.llm.local_model_catalog_port import InstalledLocalModelV1
from google_work_agent.ports.llm.local_model_profile import (
    LocalInferenceClass,
    LocalModelProfileV1,
)
from google_work_agent.ports.llm.runtime_selection import (
    LlmRuntimeSelectionV1,
    LocalRuntimeActivationStatus,
    LocalRuntimeRequirementsV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import ApprovedModelInfo


@dataclass(frozen=True)
class _Catalog:
    models: tuple[InstalledLocalModelV1, ...]

    def list_installed_models(self) -> tuple[InstalledLocalModelV1, ...]:
        return self.models


@pytest.mark.parametrize(
    "installed_ids", [(), ("qwen3.5:9b",), ("qwen3.5:4b",), ("qwen3.5:9b", "qwen3.5:4b")]
)
@pytest.mark.parametrize("preferred", ["qwen3.5:9b", "qwen3.5:4b"])
def test_model_catalog_matrix__uses_only_ready_model__or_preserves_valid_choice(
    installed_ids: tuple[str, ...], preferred: str
) -> None:
    resolver = LocalModelSelectionResolver(
        _selection(),
        _Catalog(tuple(InstalledLocalModelV1(model, "a" * 64) for model in installed_ids)),
        allow_development_models=True,
        preferred_model_id=lambda: preferred,
    )
    options = resolver.list_options()
    assert {option.model_id for option in options if option.installed and option.approved} == set(
        installed_ids
    )
    for prompt in ("request_understanding.identify_goal", "planning.compose_answer"):
        selected = resolver.get_model_for_prompt(prompt)
        if not installed_ids:
            assert selected is None
        elif len(installed_ids) == 1:
            assert selected is not None and selected.model_id == installed_ids[0]
        else:
            assert selected is not None and selected.model_id == preferred


def test_local_model_selection__with_both_ready_and_no_valid_preference__requires_user_choice() -> None:
    resolver = LocalModelSelectionResolver(
        _selection(),
        _Catalog(
            tuple(
                InstalledLocalModelV1(model, "a" * 64)
                for model in ("qwen3.5:9b", "qwen3.5:4b")
            )
        ),
        allow_development_models=True,
    )

    assert resolver.get_selected_model() is None
    assert not any(item.selected for item in resolver.list_options())


def test_user_choice__uses_ready_4b_without_9b__for_both_inference_classes() -> None:
    selected = replace(
        _selection(),
        local_model_profile=LocalModelProfileV1(
            schema_version=1,
            profile_id="single-9b",
            runtime="OLLAMA",
            worker_model_id="qwen3.5:9b",
            reasoning_model_id="qwen3.5:9b",
            default_inference_class=LocalInferenceClass.REASONING,
            prompt_inference_classes=(),
        ),
    )
    resolver = LocalModelSelectionResolver(
        selected,
        _Catalog((InstalledLocalModelV1("qwen3.5:4b", "sha256:" + "d" * 64),)),
        allow_development_models=True,
        preferred_model_id=lambda: "qwen3.5:4b",
    )
    for prompt in ("request_understanding.identify_goal", "planning.compose_answer"):
        model = resolver.get_model_for_prompt(prompt)
        assert model is not None
        assert model.model_id == "qwen3.5:4b"
    assert [item.model_id for item in resolver.list_options() if item.selected] == ["qwen3.5:4b"]


def test_user_choice__missing_or_wrong_digest__does_not_fall_back() -> None:
    approved = ApprovedModelInfo("qwen3.5:4b", "OLLAMA", "1", "1", digest="a" * 64)
    resolver = LocalModelSelectionResolver(
        _selection(approved),
        _Catalog((InstalledLocalModelV1("qwen3.5:4b", "sha256:" + "b" * 64),)),
        preferred_model_id=lambda: "qwen3.5:4b",
    )
    assert resolver.get_selected_model() is None
    assert not next(
        item for item in resolver.list_options() if item.model_id == "qwen3.5:4b"
    ).approved


def _profile() -> LocalModelProfileV1:
    return LocalModelProfileV1(
        schema_version=1,
        profile_id="test-profile",
        runtime="OLLAMA",
        worker_model_id="qwen3.5:4b",
        reasoning_model_id="qwen3.5:9b",
        default_inference_class=LocalInferenceClass.REASONING,
        prompt_inference_classes=(
            ("request_understanding.identify_goal", LocalInferenceClass.WORKER),
        ),
    )


def _selection(*models: ApprovedModelInfo) -> LlmRuntimeSelectionV1:
    return LlmRuntimeSelectionV1(
        schema_version=1,
        deployment_profile="LOCAL_CAPABLE",
        selected_model=models[-1] if models else None,
        ollama_endpoint_policy="FIXED_LOOPBACK_OLLAMA_V1",
        model_manifest_hash="a" * 64 if models else None,
        product_decision_hash="b" * 64 if models else None,
        local_runtime_activation_status=LocalRuntimeActivationStatus.ACTIVE,
        requirements=LocalRuntimeRequirementsV1(4, 8 * 1024**3, 4 * 1024**3, "WINDOWS", "AMD64"),
        release_version="test",
        approved_models=models,
        local_model_profile=_profile(),
    )


def test_signed_local_models__allow_only__manifest_models() -> None:
    worker = ApprovedModelInfo("qwen3.5:4b", "OLLAMA", "1", "1", digest="a" * 64)
    reasoning = ApprovedModelInfo("qwen3.5:9b", "OLLAMA", "1", "1", digest="b" * 64)
    resolver = LocalModelSelectionResolver(
        runtime_selection=_selection(worker, reasoning),
        catalog=_Catalog(
            (
                InstalledLocalModelV1("qwen2.5:7b", "c" * 64),
                InstalledLocalModelV1("qwen3.5:4b", "a" * 64),
                InstalledLocalModelV1("qwen3.5:9b", "b" * 64),
            )
        ),
        preferred_model_id=lambda: "qwen3.5:9b",
    )

    assert [(item.model_id, item.approved, item.selected) for item in resolver.list_options()] == [
        ("qwen3.5:9b", True, True),
        ("qwen3.5:4b", True, False),
    ]
    assert resolver.get_selected_model() == reasoning
    assert resolver.get_model_for_prompt("request_understanding.identify_goal") == reasoning
    assert resolver.get_model_for_prompt("planning.compose_answer") == reasoning


def test_development_profile__approves_only__installed_profile_models() -> None:
    resolver = LocalModelSelectionResolver(
        runtime_selection=_selection(),
        catalog=_Catalog(
            (
                InstalledLocalModelV1("qwen2.5:7b", "sha256:" + "c" * 64),
                InstalledLocalModelV1("qwen3.5:4b", "sha256:" + "d" * 64),
                InstalledLocalModelV1("qwen3.5:9b", "sha256:" + "e" * 64),
            )
        ),
        allow_development_models=True,
        preferred_model_id=lambda: "qwen3.5:9b",
    )

    worker = resolver.get_model_for_prompt("request_understanding.identify_goal")
    reasoning = resolver.get_model_for_prompt("review.inspect_goal_and_evidence")
    assert worker is not None and worker.model_id == "qwen3.5:9b"
    assert reasoning is not None and reasoning.model_id == "qwen3.5:9b"
    assert resolver.get_approved_model("qwen2.5:7b") is None


def test_profile_readiness__requires_selected_model__not_both_models() -> None:
    worker = ApprovedModelInfo("qwen3.5:4b", "OLLAMA", "1", "1")
    reasoning = ApprovedModelInfo("qwen3.5:9b", "OLLAMA", "1", "1")
    resolver = LocalModelSelectionResolver(
        runtime_selection=_selection(worker, reasoning),
        catalog=_Catalog((InstalledLocalModelV1("qwen3.5:9b", None),)),
    )

    assert resolver.get_selected_model() == reasoning
    assert resolver.get_model_for_prompt("planning.compose_answer") == reasoning
    assert [(item.model_id, item.installed, item.selected) for item in resolver.list_options()] == [
        ("qwen3.5:9b", True, True),
        ("qwen3.5:4b", False, False),
    ]
