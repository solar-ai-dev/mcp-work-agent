"""088: inactive, invocation-local answer choice through the actual Product router.

The separate evaluation registry uses the real assembler, so its common context
suffix differs from 087's direct transport experiment. Historical model scores
are not evidence for this new wire. Product registry and activation stay intact.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from typing import Any, cast

from scripts.answer_fact_selection_candidate import bind_fact_selection_schema
from scripts.answer_rendering_choice_candidate import (
    bind_answer_rendering_choice_schema,
    materialize_answer_rendering_choice,
)
from scripts.evaluate_answer_mode_first import mode_first_wire
from scripts.evaluate_answer_rendering_choice import ROLE
from scripts.production_goal_output_candidate import _has_pending_confirmation, _product_router
from scripts.ru_observation import object_hash

from google_work_agent.adapters.langgraph.main.state import request_from_state
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import PlanningSubgraph
from google_work_agent.adapters.langgraph.subgraphs.planning.state import PlanningLocalState
from google_work_agent.adapters.llm.ollama.structured_inference import (
    OllamaStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import (
    PromptRepairSchemaRepairer,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)

COMPOSE_SLOT = "planning.compose_answer"
EVALUATION_SLOT = "evaluation.planning.choose_answer_rendering"
INPUT_VERSION = "evaluation-answer-choice-connected-input-v1"
OUTPUT_VERSION = "evaluation-answer-choice-connected-output-v1"


class _EvaluationRegistry:
    """Explicit evaluation artifact resolver, never a relaxed Product manifest loader."""

    def __init__(
        self,
        *,
        product_registry: PromptRegistry,
        product_ref: PromptReference,
        projection: Mapping[str, object],
    ) -> None:
        if product_registry.lookup_for_evaluation(COMPOSE_SLOT) != product_ref:
            raise ValueError("Product compose PromptRef differs from its registered artifact")
        self.product_registry = product_registry
        self.expected_input = deepcopy(dict(projection))
        self.instruction = ROLE
        self.prompt_ref = replace(
            product_ref,
            prompt_id=EVALUATION_SLOT,
            prompt_version="evaluation-answer-choice-connected-v088",
            content_hash=hashlib.sha256(ROLE.encode("utf-8")).hexdigest(),
            input_schema_version=INPUT_VERSION,
            output_schema_version=OUTPUT_VERSION,
        )
        self.input_contract = self
        self.manifest = {
            "execution_scope": EVALUATION,
            "activation_status": "INACTIVE_EVALUATION_ONLY",
            "prompt_ref": asdict(self.prompt_ref),
            "product_input_contract_slot": COMPOSE_SLOT,
            "expected_input_sha256": object_hash(self.expected_input),
            "assembly": "ACTUAL_ASSEMBLE_PROMPT_NOT_087_WIRE",
        }
        self.validate_projection(EVALUATION_SLOT, projection)

    def lookup_for_evaluation(self, prompt_id: str) -> PromptReference:
        if prompt_id != EVALUATION_SLOT:
            raise LookupError("unregistered answer-choice evaluation Prompt")
        if hashlib.sha256(self.instruction.encode("utf-8")).hexdigest() != (
            self.prompt_ref.content_hash
        ):
            raise ValueError("evaluation answer-choice source hash differs")
        return self.prompt_ref

    def source_text(self, prompt_id: str) -> str:
        self.lookup_for_evaluation(prompt_id)
        return self.instruction

    def resolve(self, prompt_id: str, *_args: object, **_kwargs: object) -> PromptReference:
        return self.lookup_for_evaluation(prompt_id)

    def validate_projection(self, prompt_id: str, projection: Mapping[str, object]) -> None:
        self.lookup_for_evaluation(prompt_id)
        self.product_registry.input_contract.validate_projection(COMPOSE_SLOT, projection)
        if dict(projection) != self.expected_input:
            raise ValueError("evaluation answer-choice input binding changed")


@dataclass
class _Invocation:
    owner: object
    run_id: str
    events: list[dict[str, object]] = field(default_factory=list)
    last_prompt_ref: PromptReference | None = None
    closed: bool = False


_active_registry: ContextVar[_EvaluationRegistry | None] = ContextVar(
    "evaluation_answer_choice_registry", default=None
)
_active_invocation: ContextVar[_Invocation | None] = ContextVar(
    "evaluation_answer_choice_invocation", default=None
)


def decorate_answer_choice_provider(provider: Any) -> Any:
    """Decorate the actual Ollama leaf inside the caller's existing wire observer."""
    if not isinstance(provider, OllamaStructuredInferenceAdapter):
        return provider
    original = provider.assemble_instruction_text

    def assemble(ref: PromptReference, projection: Mapping[str, object]) -> str:
        if ref.prompt_id != EVALUATION_SLOT:
            return original(ref, projection)
        registry = _active_registry.get()
        if registry is None or registry.prompt_ref != ref:
            raise ValueError("answer-choice Prompt has no invocation-local registry")
        return assemble_prompt(
            ref, projection, registry=cast(Any, registry), execution_scope=EVALUATION
        )

    return replace(provider, assemble_instruction_text=assemble)


class AnswerChoicePlanningSubgraph(PlanningSubgraph):
    """Keep the Product graph/consumer; replace only eligible compose inference."""

    def __init__(
        self,
        *,
        observations: list[dict[str, object]] | None = None,
        **kwargs: Any,
    ) -> None:
        if kwargs.get("prompt_execution_scope") != EVALUATION:
            raise ValueError("088 Planning caller must explicitly use EVALUATION scope")
        super().__init__(**kwargs)
        if self._llm_runtime is None or self._dependencies is not None:
            raise ValueError("088 requires the actual Product inference runtime")
        self.observations = observations if observations is not None else []

    def _compose_answer_node(self, state: PlanningLocalState) -> PlanningLocalState:
        invocation = _Invocation(self, state["run_id"])
        token = _active_invocation.set(invocation)
        try:
            return super()._compose_answer_node(state)
        finally:
            invocation.closed = True
            self.observations.append(
                {
                    "run_id": invocation.run_id,
                    "scope": "ONE_PHYSICAL_COMPOSE_INVOCATION",
                    "events": deepcopy(invocation.events),
                    "trace_prompt_ref": (
                        asdict(invocation.last_prompt_ref) if invocation.last_prompt_ref else None
                    ),
                }
            )
            _active_invocation.reset(token)

    def _semantic_invoker(self, state: PlanningLocalState) -> PlanningSemanticInvoker:
        original = super()._semantic_invoker(state)
        invocation = _active_invocation.get()

        def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
            if prompt_id != COMPOSE_SLOT or invocation is None:
                return original(prompt_id, prompt_input)
            if invocation.closed or invocation.owner is not self:
                raise ValueError("answer-choice callable escaped its physical invocation")
            reason: str | None = None
            if "base_projection" in prompt_input:
                reason = "EXISTING_SEMANTIC_REPAIR"
            elif _has_pending_confirmation(self._llm_runtime, invocation.run_id):
                reason = "EXISTING_CONFIRMATION"
            if reason is None:
                evidence = prompt_input.get("evidence")
                if not isinstance(evidence, list) or not all(
                    isinstance(item, Mapping) for item in evidence
                ):
                    raise ValueError("compose Evidence projection is invalid")
                projected, snapshots = self._project_evidence_and_source_snapshots(
                    state, cast(list[Mapping[str, object]], evidence)
                )
                if projected != evidence:
                    raise ValueError("compose Evidence differs from the Product projection")
                if bind_fact_selection_schema(prompt_input, source_snapshots=snapshots) is None:
                    reason = "NO_FACT_CAPABILITY_NOT_AUTHORIZATION"
            if reason is not None:
                invocation.last_prompt_ref = self._prompt_refs[COMPOSE_SLOT]
                invocation.events.append(
                    {
                        "operation": "PRODUCT_DELEGATE",
                        "reason": reason,
                        "run_id": invocation.run_id,
                        "input_sha256": object_hash(prompt_input),
                    }
                )
                return original(prompt_id, prompt_input)
            return self._invoke_choice(
                state, prompt_input, deepcopy(snapshots), invocation=invocation
            )

        return invoke

    def _invoke_choice(
        self,
        state: PlanningLocalState,
        projection: Mapping[str, object],
        snapshots: Mapping[str, Mapping[str, object]],
        *,
        invocation: _Invocation,
    ) -> Mapping[str, object]:
        router = _product_router(self._llm_runtime)
        if invocation.closed or router.run_context_provider() != invocation.run_id:
            raise ValueError("answer-choice Run differs from the actual dispatch context")
        requested_mode = request_from_state(cast(Any, state)).requested_mode
        if requested_mode != "LOCAL_GPU":
            raise ValueError("088 candidate is local-only")
        if not isinstance(router.schema_repairer, PromptRepairSchemaRepairer):
            raise TypeError("existing Product bounded schema repair owner is required")
        manifest = router.prompt_manifest_path
        product_registry = PromptRegistry(
            manifest,
            None if manifest is None else manifest.parent / "prompt_runtime_input_contract_v1.json",
        )
        registry = _EvaluationRegistry(
            product_registry=product_registry,
            product_ref=self._prompt_refs[COMPOSE_SLOT],
            projection=projection,
        )
        schema = OutputSchemaDefinition(
            schema_version=OUTPUT_VERSION,
            json_schema=mode_first_wire(
                {
                    "format": bind_answer_rendering_choice_schema(
                        projection, source_snapshots=snapshots
                    )
                }
            )["format"],
        )
        invocation.last_prompt_ref = registry.prompt_ref
        event: dict[str, object] = {
            "operation": "CHOICE_DISPATCH",
            "run_id": invocation.run_id,
            "input_sha256": object_hash(projection),
            "schema_sha256": object_hash(schema.json_schema),
            "prompt_ref": asdict(registry.prompt_ref),
            "manifest": registry.manifest,
            "snapshot_binding_sha256": object_hash(snapshots),
            "first_and_repair_observation": "EXISTING_PROVIDER_OBSERVER",
        }
        invocation.events.append(event)
        evaluation_router = replace(
            router,
            schema_repairer=replace(
                router.schema_repairer, prompt_loader=registry.resolve, execution_scope=EVALUATION
            ),
        )
        token = _active_registry.set(registry)
        try:
            result = evaluation_router.infer(
                requested_mode, registry.prompt_ref, projection, schema
            )
            event["router_validated_output"] = deepcopy(result.structured_output)
            draft = materialize_answer_rendering_choice(
                result.structured_output, prompt_input=projection, source_snapshots=snapshots
            )
            if draft is None:
                raise ValueError("empty fact selection has no draft; no automatic fallback")
            event["materialized_draft"] = deepcopy(draft)
            return cast(Mapping[str, object], draft)
        except Exception as error:
            event["error_type"] = type(error).__name__
            raise
        finally:
            _active_registry.reset(token)

    def _trace(
        self,
        state: PlanningLocalState,
        node: str,
        prompt_ref: PromptReference | None,
        *,
        first: bool = False,
        llm_call_increment: int = 1,
    ) -> dict[str, object]:
        invocation = _active_invocation.get()
        if node == "compose_answer" and invocation is not None and invocation.owner is self:
            prompt_ref = invocation.last_prompt_ref or prompt_ref
        return super()._trace(
            state, node, prompt_ref, first=first, llm_call_increment=llm_call_increment
        )


__all__ = ["AnswerChoicePlanningSubgraph", "decorate_answer_choice_provider"]
