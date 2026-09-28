"""Inactive, invocation-local v4 Goal/Output bridge into the actual Product RU node.

Use ``goal_output_node_candidate`` around the isolated snapshot runtime and compose
``decorate_goal_output_provider`` inside the existing Provider observer. No Graph,
active Prompt, persistent semantic State, or release registry is changed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from evaluation.request_semantic_authority_candidate import (
    GoalOutputModalityAuthorityCandidate,
    _cached_result,
    _work_unit_ids,
)
from scripts.ru_observation import object_hash

from google_work_agent.adapters.langgraph.subgraphs.request_understanding import graph as ru_graph
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.projections.identify_goal_projection import (  # noqa: E501
    project_identify_goal_input,
)
from google_work_agent.adapters.llm.ollama.structured_inference import (
    OllamaStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import (
    PromptRepairSchemaRepairer,
)
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_ops,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import (
    EVALUATION,
    PromptRegistry,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1

GOAL_SLOT = "request_understanding.identify_goal"
OUTPUT_SLOT = "request_understanding.identify_output_responsibilities"
EVALUATION_SLOT = "evaluation.request_understanding.identify_goal_output_authority"
INPUT_VERSION = "evaluation-goal-output-connected-input-v1"
OUTPUT_VERSION = "evaluation-goal-output-modality-authority-v4"
_GOAL_FIELDS = ("goal", "completion_conditions", "constraints", "analysis_requirement")
_active_registry: ContextVar[_EvaluationRegistry | None] = ContextVar(
    "evaluation_goal_output_registry", default=None
)


class _EvaluationRegistry:
    """A separate evaluation resolver, not an extension of the live Product registry."""

    def __init__(
        self,
        *,
        prompt_ref: PromptReference,
        instruction: str,
        expected_input: Mapping[str, object],
        product_registry: PromptRegistry,
    ) -> None:
        self.prompt_ref = prompt_ref
        self.instruction = instruction
        self.expected_input = deepcopy(dict(expected_input))
        self.product_registry = product_registry
        self.input_contract = self

    def lookup_for_evaluation(self, prompt_id: str) -> PromptReference:
        if prompt_id != self.prompt_ref.prompt_id:
            raise LookupError("unregistered evaluation Prompt")
        return self.prompt_ref

    def source_text(self, prompt_id: str) -> str:
        self.lookup_for_evaluation(prompt_id)
        return self.instruction

    def resolve(self, prompt_id: str, *_args: object, **_kwargs: object) -> PromptReference:
        return self.lookup_for_evaluation(prompt_id)

    def validate_projection(self, prompt_id: str, projection: Mapping[str, object]) -> None:
        self.lookup_for_evaluation(prompt_id)
        product_input = {
            key: value for key, value in projection.items() if key != "output_candidates"
        }
        self.product_registry.input_contract.validate_projection(GOAL_SLOT, product_input)
        if dict(projection) != self.expected_input:
            raise ValueError("evaluation joint authority input binding changed")


def decorate_goal_output_provider(provider: Any) -> Any:
    """Keep the existing transport/identity; supply only the registered candidate source.

    The snapshot runner must wrap this returned leaf in its usual observer, not
    place this decorator outside an opaque observed Provider.
    """
    if not isinstance(provider, OllamaStructuredInferenceAdapter):
        return provider
    original = provider.assemble_instruction_text

    def assemble(ref: PromptReference, projection: Mapping[str, object]) -> str:
        if ref.prompt_id != EVALUATION_SLOT:
            return original(ref, projection)
        registry = _active_registry.get()
        if registry is None or registry.prompt_ref != ref:
            raise ValueError("evaluation Prompt has no invocation-local authority")
        return assemble_prompt(
            ref, projection, registry=cast(Any, registry), execution_scope=EVALUATION
        )

    return replace(provider, assemble_instruction_text=assemble)


class ConnectedGoalOutputCandidate(GoalOutputModalityAuthorityCandidate):
    """Reuse v4 semantics while retaining actual Product dispatch and repair owners."""

    def __init__(self, *, run_id: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not isinstance(self._delegate, StructuredInferenceRuntimeRouter):
            raise TypeError("connected candidate requires the actual Product inference router")
        if self._delegate.runtime_policy.sampling_seed != self._sampling_seed:
            raise ValueError("candidate seed differs from the actual Product runtime")
        self._run_id = run_id
        self._context: dict[str, object] | None = None
        self._closed = False
        manifest = self._delegate.prompt_manifest_path
        self._product_registry = PromptRegistry(
            manifest,
            None if manifest is None else manifest.parent / "prompt_runtime_input_contract_v1.json",
        )

    @property
    def binding(self) -> dict[str, object]:
        return {
            **super().binding,
            "candidate_id": "production-graph-goal-output-v4-connected-v1",
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "input_version": INPUT_VERSION,
            "output_version": OUTPUT_VERSION,
            "requested_work_owner": "UNCHANGED_PRODUCT",
            "joint_sampling_temperature": 0.0,
            "repair_owner": "UNCHANGED_PRODUCT_ROUTER",
        }

    def close(self) -> None:
        self._closed = True
        self._context = None
        self._goal_output = None

    def _require_run(self) -> None:
        router = cast(StructuredInferenceRuntimeRouter, self._delegate)
        if self._closed or router.run_context_provider() != self._run_id:
            raise ValueError("joint authority is outside its physical Run invocation")

    def infer(
        self,
        requested_mode: Any,
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        self._require_run()
        if requested_mode != "LOCAL_GPU":
            raise ValueError("connected candidate is local-only")
        if prompt_ref.prompt_id == GOAL_SLOT:
            if self._context is not None:
                raise ValueError("joint Goal authority cannot be regenerated in this invocation")
            self._product_registry.input_contract.validate_projection(GOAL_SLOT, input_projection)
            self._context = deepcopy(dict(input_projection))
            return self._infer_goal_output_authority(
                requested_mode=requested_mode,
                prompt_ref=prompt_ref,
                input_projection=input_projection,
            )
        if prompt_ref.prompt_id == OUTPUT_SLOT:
            return self._consume_output(input_projection)
        # Work decomposition, Source, prohibition, status, and relation stay untouched.
        return self._delegate.infer(requested_mode, prompt_ref, input_projection, output_schema_ref)

    def _consume_output(self, projection: Mapping[str, object]) -> StructuredInferenceResultV1:
        if self._context is None or self._goal_output is None:
            raise ValueError("Output consumer has no completed joint Goal authority")
        base = projection
        if "base_projection" in projection:
            if set(projection) != {"base_projection", "candidate_output", "failure_record"}:
                raise ValueError("invalid Output revision envelope")
            base = cast(Mapping[str, object], projection["base_projection"])
        context = {
            key: value
            for key, value in base.items()
            if key not in {"goal_candidate", "output_candidates", "effect_prohibitions"}
        }
        expected_goal = {key: deepcopy(self._goal_output[key]) for key in _GOAL_FIELDS}
        if (
            context != self._context
            or base.get("goal_candidate") != expected_goal
            or base.get("output_candidates") != list(self._output_candidates)
        ):
            raise ValueError(
                "Output consumer differs from the joint request/work/selected/Goal binding"
            )
        validated = output_ops.validate_output_responsibility_candidate(
            {"output_responsibilities": deepcopy(self._goal_output["requested_outputs"])},
            output_candidates=self._output_candidates,
            effect_prohibitions=cast(Any, {"effect_prohibitions": base["effect_prohibitions"]}),
            work_unit_ids=_work_unit_ids(self._context),
        )
        self.cached_response_count += 1
        self.events.append(
            {
                "operation": "OUTPUT_AUTHORITY_HANDOFF",
                "run_id": self._run_id,
                "input_sha256": object_hash(projection),
                "joint_authority_sha256": object_hash(self._goal_output),
                "validated_output": deepcopy(validated),
                "provider_dispatches": 0,
            }
        )
        return _cached_result(model_id=self._model_id, structured_output=dict(validated))

    def _invoke_candidate(
        self,
        *,
        requested_mode: Any,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        schema: OutputSchemaDefinition,
        instruction: str,
    ) -> tuple[dict[str, object], StructuredInferenceResultV1, list[dict[str, object]]]:
        self._require_run()
        ref = replace(
            prompt_ref,
            input_schema_version=INPUT_VERSION,
            output_schema_version=OUTPUT_VERSION,
        )
        if ref.prompt_id != EVALUATION_SLOT or schema.schema_version != OUTPUT_VERSION:
            raise ValueError("unexpected connected authority contract")
        registry = _EvaluationRegistry(
            prompt_ref=ref,
            instruction=instruction,
            expected_input=prompt_input,
            product_registry=self._product_registry,
        )
        router = cast(StructuredInferenceRuntimeRouter, self._delegate)
        if not isinstance(router.schema_repairer, PromptRepairSchemaRepairer):
            raise TypeError("existing bounded Product schema repair owner is required")
        joint_router = replace(
            router,
            runtime_policy=replace(router.runtime_policy, sampling_temperature=0.0),
            schema_repairer=replace(
                router.schema_repairer, prompt_loader=registry.resolve, execution_scope=EVALUATION
            ),
        )
        token = _active_registry.set(registry)
        try:
            result = joint_router.infer(requested_mode, ref, prompt_input, schema)
        finally:
            _active_registry.reset(token)
        if result.model != self._model_id:
            raise ValueError("joint authority model differs from its registered candidate")
        raw = deepcopy(dict(result.structured_output))
        return (
            raw,
            result,
            [
                {
                    "attempt": "PRODUCT_ROUTER_VALIDATED_RETURN",
                    "structured_output": deepcopy(raw),
                    "first_and_repair_observation": "EXISTING_PROVIDER_OBSERVER",
                }
            ],
        )


@contextmanager
def goal_output_node_candidate(
    *, tool_catalog: Any, model_id: str, sampling_seed: int, observations: list[dict[str, object]]
) -> Iterator[None]:
    """Wrap only fresh physical RU invocations; confirmation/resume stay Product-owned."""
    original = ru_graph.identify_goal_node

    def invoke(state: Any, **kwargs: Any) -> Any:
        projected = project_identify_goal_input(state)
        if (
            state.get("goal_candidate") is not None
            or state.get("request_intent") is not None
            or "confirmation_response" in projected
            or "request_reconsideration" in projected
        ):
            return original(state, **kwargs)
        candidate = ConnectedGoalOutputCandidate(
            run_id=projected["request"].run_id,
            delegate=kwargs["llm_runtime"],
            tool_catalog=tool_catalog,
            model_id=model_id,
            sampling_seed=sampling_seed,
        )
        try:
            return original(state, **{**kwargs, "llm_runtime": candidate})
        finally:
            observations.append(
                {
                    "run_id": projected["request"].run_id,
                    "binding": candidate.binding,
                    "events": deepcopy(candidate.events),
                    "cached_response_count": candidate.cached_response_count,
                    "cache_lifetime": "ONE_PHYSICAL_IDENTIFY_GOAL_INVOCATION",
                }
            )
            candidate.close()

    with patch.object(ru_graph, "identify_goal_node", invoke):
        yield
