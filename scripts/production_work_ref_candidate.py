"""Inactive request-local Work span references at the existing semantic owner boundary."""

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
    _request_tokens,
    _requested_work_ref_schema,
)
from scripts.production_goal_output_candidate import (
    ConnectedGoalOutputCandidate,
    _has_pending_confirmation,
    _product_router,
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
from google_work_agent.application.agents.request_understanding import identify_goal as goal_owner
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestedWorkDefinitionV1,
)
from google_work_agent.application.agents.request_understanding.contracts.work_unit_binding import (
    validate_requested_work_definition,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference

WORK_SLOT = "request_understanding.identify_requested_work"
EVALUATION_SLOT = "evaluation.request_understanding.identify_requested_work_refs"
INPUT_VERSION = "evaluation-work-ref-connected-input-v1"
OUTPUT_VERSION = "evaluation-work-ref-connected-output-v1"
_SPAN_INSTRUCTION = (
    "- 각 `request_spans`에는 그 업무 결과를 정의하는 현재 사용자 원문의 연속 문자열을 "
    "글자 그대로 둔다."
)
_REF_INSTRUCTION = (
    "- 각 `ranges`에는 그 업무 결과를 정의하는 원문의 연속 구간을 "
    "`request_tokens`의 `start_token_id`와 `end_token_id`로 선택한다. 양 끝 토큰을 포함한다."
)
_active_registry: ContextVar[_EvaluationRegistry | None] = ContextVar(
    "evaluation_work_ref_registry", default=None
)
_active_owner: ContextVar[ConnectedWorkRefCandidate | None] = ContextVar(
    "evaluation_work_ref_owner", default=None
)


def materialize_work_definition(value: object, *, user_request: str) -> RequestedWorkDefinitionV1:
    """Bind closed positions directly; never re-find a generated string occurrence."""
    tokens = _request_tokens(user_request)
    schema = _requested_work_ref_schema([str(token["token_id"]) for token in tokens])
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError("invalid Work refs: " + "; ".join(errors))
    by_id = {token["token_id"]: token for token in tokens}
    occupied: list[tuple[int, int]] = []
    positioned: list[tuple[int, int, list[dict[str, object]]]] = []
    for index, unit in enumerate(cast(dict[str, Any], value)["work_units"]):
        provenance: list[dict[str, object]] = []
        for selected in unit["ranges"]:
            start = cast(int, by_id[selected["start_token_id"]]["start_offset"])
            end = cast(int, by_id[selected["end_token_id"]]["end_offset"])
            if end <= start:
                raise ValueError("Work token range is reversed")
            if any(start < prior_end and prior_start < end for prior_start, prior_end in occupied):
                raise ValueError("Work token ranges overlap")
            occupied.append((start, end))
            provenance.append(
                {
                    "source": "USER_REQUEST",
                    "start_offset": start,
                    "end_offset": end,
                    "source_text": user_request[start:end],
                }
            )
        positioned.append(
            (min(cast(int, item["start_offset"]) for item in provenance), index, provenance)
        )
    positioned.sort(key=lambda item: (item[0], item[1]))
    return validate_requested_work_definition(
        {
            "work_units": [
                {"unit_id": f"work-{index}", "request_provenance": provenance}
                for index, (_, _, provenance) in enumerate(positioned, start=1)
            ],
            "work_relations": [],
        },
        user_request=user_request,
    )


class _EvaluationRegistry:
    def __init__(self, owner: ConnectedWorkRefCandidate, projection: Mapping[str, object]) -> None:
        self.owner = owner
        self.expected_input = deepcopy(dict(projection))
        self.input_contract = self

    def lookup_for_evaluation(self, prompt_id: str) -> PromptReference:
        if prompt_id != EVALUATION_SLOT:
            raise LookupError("unregistered evaluation Work Prompt")
        return self.owner.prompt_ref

    def source_text(self, prompt_id: str) -> str:
        self.lookup_for_evaluation(prompt_id)
        return self.owner.instruction

    def resolve(self, prompt_id: str, *_args: object, **_kwargs: object) -> PromptReference:
        return self.lookup_for_evaluation(prompt_id)

    def validate_projection(self, prompt_id: str, projection: Mapping[str, object]) -> None:
        self.lookup_for_evaluation(prompt_id)
        self.owner.product_registry.input_contract.validate_projection(
            WORK_SLOT, {key: value for key, value in projection.items() if key != "request_tokens"}
        )
        if dict(projection) != self.expected_input:
            raise ValueError("evaluation Work source/token binding changed")


def decorate_work_ref_provider(provider: Any) -> Any:
    """Compose at the actual Ollama leaf, inside its existing wire observer."""
    if not isinstance(provider, OllamaStructuredInferenceAdapter):
        return provider
    original = provider.assemble_instruction_text

    def assemble(ref: PromptReference, projection: Mapping[str, object]) -> str:
        if ref.prompt_id != EVALUATION_SLOT:
            return original(ref, projection)
        registry = _active_registry.get()
        if registry is None or registry.owner.prompt_ref != ref:
            raise ValueError("evaluation Work Prompt has no invocation-local authority")
        return assemble_prompt(
            ref, projection, registry=cast(Any, registry), execution_scope=EVALUATION
        )

    return replace(provider, assemble_instruction_text=assemble)


class ConnectedWorkRefCandidate:
    def __init__(self, *, delegate: Any, run_id: str) -> None:
        # Only the known invocation-local bridge can surround the Product router.
        self.delegate = (
            delegate._delegate if isinstance(delegate, ConnectedGoalOutputCandidate) else delegate
        )
        self.router = _product_router(self.delegate)
        self.run_id = run_id
        self.closed = False
        self.called = False
        self.events: list[dict[str, object]] = []
        manifest = self.router.prompt_manifest_path
        self.product_registry = PromptRegistry(
            manifest,
            None if manifest is None else manifest.parent / "prompt_runtime_input_contract_v1.json",
        )
        self.product_ref = self.product_registry.lookup_for_evaluation(WORK_SLOT)
        source = self.product_registry.source_text(WORK_SLOT)
        if source.count(_SPAN_INSTRUCTION) != 1:
            raise ValueError("Product Work boundary instruction differs from the candidate basis")
        self.instruction = source.replace(_SPAN_INSTRUCTION, _REF_INSTRUCTION)
        self.prompt_ref = replace(
            self.product_ref,
            prompt_id=EVALUATION_SLOT,
            prompt_version="evaluation-work-ref-v34",
            content_hash=hashlib.sha256(self.instruction.encode()).hexdigest(),
            input_schema_version=INPUT_VERSION,
            output_schema_version=OUTPUT_VERSION,
        )

    @property
    def binding(self) -> dict[str, object]:
        return {
            "candidate_id": "production-work-ref-connected-v34",
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "baseline_prompt_hash": self.product_ref.content_hash,
            "candidate_prompt_hash": self.prompt_ref.content_hash,
            "input_version": INPUT_VERSION,
            "output_version": OUTPUT_VERSION,
            "runtime_policy": "UNCHANGED_PRODUCT_WORK_POLICY",
            "repair_owner": "UNCHANGED_PRODUCT_ROUTER",
            "work_output": "EXISTING_REQUESTED_WORK_DEFINITION_V1",
        }

    def close(self) -> None:
        self.closed = True

    def identify(
        self,
        *,
        llm_runtime: Any,
        requested_mode: str,
        prompt_ref: PromptReference,
        user_request: str,
        candidate_output: object | None = None,
        failure_record: Mapping[str, object] | None = None,
    ) -> RequestedWorkDefinitionV1:
        actual_router = (
            llm_runtime._router
            if isinstance(llm_runtime, ConnectedGoalOutputCandidate)
            else _product_router(llm_runtime)
        )
        if (
            self.closed
            or self.called
            or self.router.run_context_provider() != self.run_id
            or actual_router is not self.router
            or requested_mode != "LOCAL_GPU"
            or _has_pending_confirmation(self.delegate, self.run_id)
        ):
            raise ValueError("Work candidate is outside its fresh physical Run invocation")
        if (
            prompt_ref != self.product_ref
            or candidate_output is not None
            or failure_record is not None
        ):
            raise ValueError("Work candidate supports only its fixed initial Product owner call")
        tokens = _request_tokens(user_request)
        schema = replace(
            _requested_work_ref_schema([str(token["token_id"]) for token in tokens]),
            schema_version=OUTPUT_VERSION,
        )
        projection = {
            "user_request": user_request,
            "request_tokens": [
                {"token_id": token["token_id"], "text": token["text"]} for token in tokens
            ],
        }
        registry = _EvaluationRegistry(self, projection)
        registry.validate_projection(EVALUATION_SLOT, projection)
        if not isinstance(self.router.schema_repairer, PromptRepairSchemaRepairer):
            raise TypeError("existing Product bounded schema repair owner is required")
        router = replace(
            self.router,
            schema_repairer=replace(
                self.router.schema_repairer,
                prompt_loader=registry.resolve,
                execution_scope=EVALUATION,
            ),
        )
        self.called = True
        event: dict[str, object] = {
            "operation": "REQUESTED_WORK_REF",
            "input_sha256": object_hash(projection),
            "schema_sha256": object_hash(schema.json_schema),
            "first_and_repair_observation": "EXISTING_PROVIDER_OBSERVER",
        }
        self.events.append(event)
        token = _active_registry.set(registry)
        try:
            result = router.infer("LOCAL_GPU", self.prompt_ref, projection, schema)
            event["router_validated_output"] = deepcopy(result.structured_output)
            work = materialize_work_definition(result.structured_output, user_request=user_request)
            event["materialized_work_definition"] = deepcopy(work)
            return work
        except Exception as error:
            event["failure_type"] = type(error).__name__
            raise
        finally:
            _active_registry.reset(token)


@contextmanager
def work_ref_node_candidate(*, observations: list[dict[str, object]]) -> Iterator[None]:
    """Replace the supporting Work operation only within a fresh physical RU invocation."""
    original_node, original_owner = ru_graph.identify_goal_node, goal_owner.identify_requested_work

    def identify(**kwargs: Any) -> RequestedWorkDefinitionV1:
        candidate = _active_owner.get()
        return original_owner(**kwargs) if candidate is None else candidate.identify(**kwargs)

    def invoke(state: Any, **kwargs: Any) -> Any:
        projected = project_identify_goal_input(state)
        run_id = projected["request"].run_id
        if (
            state.get("goal_candidate") is not None
            or state.get("request_intent") is not None
            or "confirmation_response" in projected
            or "request_reconsideration" in projected
            or _has_pending_confirmation(kwargs["llm_runtime"], run_id)
        ):
            return original_node(state, **kwargs)
        candidate = ConnectedWorkRefCandidate(delegate=kwargs["llm_runtime"], run_id=run_id)
        token = _active_owner.set(candidate)
        try:
            return original_node(state, **kwargs)
        finally:
            _active_owner.reset(token)
            observations.append(
                {
                    "run_id": run_id,
                    "binding": candidate.binding,
                    "events": deepcopy(candidate.events),
                }
            )
            candidate.close()

    with (
        patch.object(goal_owner, "identify_requested_work", identify),
        patch.object(ru_graph, "identify_goal_node", invoke),
    ):
        yield
