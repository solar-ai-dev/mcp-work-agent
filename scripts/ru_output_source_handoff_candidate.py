"""Inactive v20: validated v4 Output authority is read-only context for Source."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from evaluation.request_semantic_authority_candidate import (
    GoalOutputModalityAuthorityCandidate,
    _work_unit_ids,
)
from scripts.ru_observation import object_hash, observe_local_calls

from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    _runtime_policy_for_prompt,
)
from google_work_agent.application.agents.request_understanding import (
    identify_effect_prohibitions as prohibition_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_output_responsibilities as output_ops,
)
from google_work_agent.application.agents.request_understanding import (
    identify_source_dependencies as source_ops,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import RuntimePolicy

GOAL_PROMPT_ID = "request_understanding.identify_goal"
PROHIBITION_PROMPT_ID = "request_understanding.identify_effect_prohibitions"
SOURCE_PROMPT_ID = "request_understanding.identify_source_dependencies"
EVALUATION_SOURCE_PROMPT_ID = "evaluation.request_understanding.source_with_output_authority"
EVALUATION_INPUT_VERSION = "evaluation-source-output-handoff-v20"
_AUTHORITY_FIELD = "confirmed_output_authority"
_CONTEXT_FIELDS = (
    "user_request",
    "selected_resource_refs",
    "requested_work",
    "run_reference_time",
    "confirmation_response",
    "request_reconsideration",
)
_GOAL_FIELDS = ("goal", "completion_conditions", "constraints", "analysis_requirement")
_HANDOFF_INSTRUCTION = (
    "Evaluation input contract: confirmed_output_authority는 앞선 Goal/Output owner의 "
    "동일 요청·WorkUnit에 대한 검증된 결과 명세다. Source owner는 이를 읽기 전용으로 "
    "소비하며 Output 의미를 다시 선택하거나 변경하지 않는다. 이 명세는 승인이나 실제 "
    "외부 실행 결과가 아니며, 기존 사실의 Source 필요 여부는 같은 사용자 원문으로 판단한다."
)


def _base(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if "base_projection" not in value:
        return value
    if set(value) != {"base_projection", "candidate_output", "failure_record"}:
        raise ValueError("Source semantic revision requires the existing exact repair envelope")
    if not isinstance(value["base_projection"], Mapping):
        raise ValueError("Source base projection must be an object")
    return value["base_projection"]


def _context(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value[key]) for key in _CONTEXT_FIELDS if key in value}


def _projection(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(raw[key]) for key in _GOAL_FIELDS}


class _SourcePolicyClient:
    """Keep the reused candidate repair transport on the existing Source temperature."""

    def __init__(self, delegate: Any, temperature: float | None) -> None:
        self._delegate = delegate
        self._temperature = temperature

    def invoke_structured(self, **kwargs: Any) -> Any:
        return self._delegate.invoke_structured(
            **{**kwargs, "sampling_temperature": self._temperature}
        )


def _replay_records(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Link recorded atomic calls to actual joint outputs, never to Dataset Gold."""
    records: dict[str, dict[str, Any]] = {}
    for case in payload["cases"]:
        goal: dict[str, Any] | None = None
        prohibition: dict[str, Any] | None = None
        for atomic in case.get("atomic", []):
            prompt_id = atomic["prompt_id"]
            if prompt_id == GOAL_PROMPT_ID:
                goal, prohibition = None, None
                if "structured_output" not in atomic:
                    continue
                matches = {
                    object_hash(event["raw_output"]): event["raw_output"]
                    for event in case.get("semantic_candidate_events", [])
                    if event["operation"] == "GOAL_OUTPUT_AUTHORITY"
                    and event.get("attempt") == atomic.get("attempt")
                    and _projection(event["raw_output"]) == atomic["structured_output"]
                    and event.get("projected_goal_output") == atomic["structured_output"]
                }
                if len(matches) != 1:
                    raise ValueError("frozen Goal requires one unambiguous recorded joint Output")
                goal = {
                    "context": _context(_base(atomic["input"])),
                    "raw_output": deepcopy(next(iter(matches.values()))),
                    "sequence": atomic["sequence"],
                }
            elif prompt_id == PROHIBITION_PROMPT_ID and "structured_output" in atomic:
                prohibition = {
                    "context": _context(_base(atomic["input"])),
                    "goal_candidate": deepcopy(_base(atomic["input"])["goal_candidate"]),
                    "raw_output": deepcopy(atomic["structured_output"]),
                    "sequence": atomic["sequence"],
                }
            elif prompt_id == SOURCE_PROMPT_ID:
                base = _base(atomic["input"])
                if goal is None or prohibition is None:
                    raise ValueError(
                        "frozen Source is missing preceding Goal/Output or prohibitions"
                    )
                context = _context(base)
                if goal["context"] != context or prohibition["context"] != context:
                    raise ValueError(
                        "frozen authorities must share Source request/work/identity/time"
                    )
                if prohibition["goal_candidate"] != _projection(goal["raw_output"]):
                    raise ValueError("frozen prohibitions must refer to the same Goal result")
                if not goal["sequence"] < prohibition["sequence"] < atomic["sequence"]:
                    raise ValueError("frozen authorities must precede the Source operation")
                key = object_hash(base)
                record = {
                    "source_input": deepcopy(base),
                    "goal_output": deepcopy(goal["raw_output"]),
                    "prohibitions": deepcopy(prohibition["raw_output"]),
                    "origin_case_ids": [case["case_id"]],
                }
                if key in records:
                    previous = records[key]
                    if any(
                        previous[field] != record[field]
                        for field in ("source_input", "goal_output", "prohibitions")
                    ):
                        raise ValueError("identical frozen Source input has ambiguous authority")
                    if case["case_id"] not in previous["origin_case_ids"]:
                        previous["origin_case_ids"].append(case["case_id"])
                else:
                    records[key] = record
    if not records:
        raise ValueError("authority replay contains no linked Source records")
    return records


class OutputSourceHandoffCandidate(GoalOutputModalityAuthorityCandidate):
    """Preserve v4's owners/call count and add one validated, non-executable handoff."""

    def __init__(self, *, authority_replay_path: Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._registry = PromptRegistry()
        self._authority_replay_sha256: str | None = None
        self._frozen_authorities: dict[str, dict[str, Any]] = {}
        if authority_replay_path is not None:
            payload = authority_replay_path.read_bytes()
            self._authority_replay_sha256 = hashlib.sha256(payload).hexdigest()
            self._frozen_authorities = _replay_records(json.loads(payload))
        self._goal_context: dict[str, Any] | None = None
        self._prohibition_cache: dict[str, Any] | None = None
        self._source_runtime_policy = _runtime_policy_for_prompt(
            RuntimePolicy(sampling_temperature=0.0, sampling_seed=self._sampling_seed),
            self._registry.lookup_for_evaluation(SOURCE_PROMPT_ID),
        )

    @property
    def source_sampling(self) -> dict[str, Any]:
        return {
            "authority": "existing Product _runtime_policy_for_prompt",
            "product_prompt_id": SOURCE_PROMPT_ID,
            "temperature": self._source_runtime_policy.sampling_temperature,
            "seed": self._sampling_seed,
            "timeout_seconds": 180,
        }

    @property
    def input_contract(self) -> dict[str, Any]:
        entry = self._registry.input_contract.entry(SOURCE_PROMPT_ID)
        return {
            "schema_version": EVALUATION_INPUT_VERSION,
            "prompt_id": EVALUATION_SOURCE_PROMPT_ID,
            "base_product_prompt_id": SOURCE_PROMPT_ID,
            "base_product_input_schema_version": entry.input_schema_version,
            "required_root_fields": [*entry.required_root_fields, _AUTHORITY_FIELD],
            "optional_root_fields": list(entry.optional_root_fields),
            "authority_fields": ["requested_result_mode", "output_responsibilities"],
            "output_contract": "unchanged caller Source output schema",
        }

    @property
    def binding(self) -> dict[str, object]:
        return {
            **super().binding,
            "candidate_id": "ru-output-source-handoff-v20",
            "source_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "authority_replay_sha256": self._authority_replay_sha256,
            "source_input_contract": self.input_contract,
            "source_input_contract_sha256": object_hash(self.input_contract),
            "source_base_instruction_sha256": hashlib.sha256(
                self._registry.source_text(SOURCE_PROMPT_ID).encode()
            ).hexdigest(),
            "handoff_instruction_sha256": hashlib.sha256(_HANDOFF_INSTRUCTION.encode()).hexdigest(),
            "instruction_boundary": "unchanged Product assembly + evaluation handoff definition",
            "source_repair_limit": 1,
            "source_sampling": self.source_sampling,
            "source_sampling_sha256": object_hash(self.source_sampling),
        }

    def reset_case(self) -> None:
        super().reset_case()
        self._goal_context = None
        self._prohibition_cache = None

    def infer(
        self, requested_mode: Any, prompt_ref: Any, input_projection: Any, output_schema_ref: Any
    ) -> Any:
        prompt_id = prompt_ref.prompt_id
        if prompt_id == SOURCE_PROMPT_ID:
            return self._infer_source(
                requested_mode, prompt_ref, input_projection, output_schema_ref
            )
        if prompt_id in {GOAL_PROMPT_ID, "request_understanding.identify_requested_work"}:
            self._goal_context = None
            self._prohibition_cache = None
            self._goal_output = None
        result = super().infer(requested_mode, prompt_ref, input_projection, output_schema_ref)
        if prompt_id == GOAL_PROMPT_ID:
            self._goal_context = _context(_base(input_projection))
        elif prompt_id == PROHIBITION_PROMPT_ID:
            base = _base(input_projection)
            if (
                self._goal_output is None
                or self._goal_context != _context(base)
                or base["goal_candidate"] != _projection(self._goal_output)
            ):
                raise ValueError(
                    "live prohibitions require this invocation's Goal/Output authority"
                )
            self._prohibition_cache = {
                "context": _context(base),
                "raw_output": deepcopy(result.structured_output),
            }
        return result

    def _authority(self, base: Mapping[str, Any]) -> dict[str, Any]:
        if self._goal_output is not None or self._goal_context is not None:
            if self._goal_context != _context(base) or self._prohibition_cache is None:
                raise ValueError(
                    "live Source is missing same-request authority; no replay fallback"
                )
            if self._prohibition_cache["context"] != _context(base):
                raise ValueError("live prohibition context changed")
            return {
                "goal_output": deepcopy(self._goal_output),
                "prohibitions": deepcopy(self._prohibition_cache["raw_output"]),
                "origin": "LIVE_V4_CACHE",
            }
        frozen = self._frozen_authorities.get(object_hash(base))
        if frozen is None or frozen["source_input"] != base:
            raise ValueError("Source replay requires an identical frozen owner input and authority")
        return {**deepcopy(frozen), "origin": "FROZEN_V4_RAW"}

    def _validate_authority(
        self, record: Mapping[str, Any], base: Mapping[str, Any]
    ) -> dict[str, Any]:
        work_ids = _work_unit_ids(base)
        schema = self._build_goal_output_schema(
            work_unit_ids=work_ids, output_candidates=self._output_candidates
        )
        errors = validate_output_schema(record["goal_output"], schema.json_schema)
        if errors:
            raise ValueError(f"upstream joint Output is not schema valid: {'; '.join(errors)}")
        prohibitions = prohibition_ops.validate_effect_prohibition_candidate(
            record["prohibitions"],
            effect_candidates=self._effect_candidates,
            work_unit_ids=work_ids,
        )
        outputs = output_ops.validate_output_responsibility_candidate(
            {"output_responsibilities": record["goal_output"]["requested_outputs"]},
            output_candidates=self._output_candidates,
            effect_prohibitions=prohibitions,
            work_unit_ids=work_ids,
        )
        return {
            "requested_result_mode": record["goal_output"]["requested_result_mode"],
            "output_responsibilities": deepcopy(outputs["output_responsibilities"]),
        }

    def _infer_source(self, mode: Any, prompt: Any, projection: Any, schema: Any) -> Any:
        event: dict[str, Any] = {
            "operation": "SOURCE_OUTPUT_AUTHORITY_HANDOFF",
            "attempt": "REVISION" if "base_projection" in projection else "FIRST",
            "original_input": deepcopy(projection),
            "original_input_sha256": object_hash(projection),
            "authority_validation": "PENDING",
            "transport_attempts": [],
        }
        self.events.append(event)
        try:
            base = _base(projection)
            # Validate the unchanged Product input before declaring a separate eval input.
            self._registry.input_contract.validate_projection(SOURCE_PROMPT_ID, base)
            record = self._authority(base)
            event.update(
                authority_origin=record["origin"],
                authority_replay_sha256=self._authority_replay_sha256,
                origin_case_ids=record.get("origin_case_ids", []),
                cached_goal_output=deepcopy(record["goal_output"]),
                cached_prohibitions=deepcopy(record["prohibitions"]),
                authority_sha256=object_hash(
                    {"goal_output": record["goal_output"], "prohibitions": record["prohibitions"]}
                ),
                source_base_input_sha256=object_hash(base),
            )
            authority = self._validate_authority(record, base)
            event["authority_validation"] = "VALID"
            candidate_base = {**deepcopy(base), _AUTHORITY_FIELD: authority}
            expected = set(base) | {_AUTHORITY_FIELD}
            allowed = set(self.input_contract["required_root_fields"]) | set(
                self.input_contract["optional_root_fields"]
            )
            if set(candidate_base) != expected or not set(candidate_base) <= allowed:
                raise ValueError("evaluation Source input does not match its closed root contract")
            candidate_input = candidate_base
            if "base_projection" in projection:
                candidate_input = {**deepcopy(projection), "base_projection": candidate_base}
            baseline_instruction = assemble_prompt(
                prompt, projection, registry=self._registry, execution_scope=EVALUATION
            )
            instruction = baseline_instruction + "\n" + _HANDOFF_INSTRUCTION
            evaluation_prompt = replace(
                prompt,
                prompt_id=EVALUATION_SOURCE_PROMPT_ID,
                prompt_version="v20",
                input_schema_version=EVALUATION_INPUT_VERSION,
                content_hash=hashlib.sha256(instruction.encode()).hexdigest(),
            )
            event.update(
                input=deepcopy(candidate_input),
                input_sha256=object_hash(candidate_input),
                source_schema_sha256=object_hash(schema.json_schema),
                baseline_assembled_instruction_sha256=hashlib.sha256(
                    baseline_instruction.encode()
                ).hexdigest(),
                instruction_sha256=evaluation_prompt.content_hash,
                evaluation_input_contract_sha256=object_hash(self.input_contract),
                source_sampling=deepcopy(self.source_sampling),
                source_sampling_sha256=object_hash(self.source_sampling),
            )
            with (
                patch.object(
                    self,
                    "_client",
                    _SourcePolicyClient(
                        self._client, self._source_runtime_policy.sampling_temperature
                    ),
                ),
                observe_local_calls(event["transport_attempts"]),
            ):
                raw, result, attempts = self._invoke_candidate(
                    requested_mode=mode,
                    prompt_ref=evaluation_prompt,
                    prompt_input=candidate_input,
                    schema=schema,
                    instruction=instruction,
                )
            event.update(raw_output=deepcopy(raw), provider_attempts=deepcopy(attempts))
            source_ops.validate_source_dependency_candidate(
                raw, source_candidates=base["source_candidates"], work_unit_ids=_work_unit_ids(base)
            )
            event["validated_source_output"] = deepcopy(raw)
            return result
        except Exception as error:
            if event["authority_validation"] == "PENDING":
                event["authority_validation"] = "REJECTED"
            event.update(error_type=type(error).__name__, error=str(error)[:500])
            raise
        finally:
            for index, attempt in enumerate(event["transport_attempts"]):
                attempt["attempt"] = "FIRST" if index == 0 else "SCHEMA_REPAIR"
