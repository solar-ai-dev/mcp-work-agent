"""External LLM boundary fake for real production LangGraph E2E certification."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from google_work_agent.ports.llm.structured_inference_contracts import (
    AvailabilityState,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    ProbeResult,
    PromptReference,
    ProviderResponsePayload,
)


@dataclass
class LangGraphE2EGeminiTransport:
    """Deterministic provider responses; all Product orchestration stays real."""

    invocations: list[dict[str, object]] = field(default_factory=list)
    crash_prompt_id: str | None = None
    crash_scenario: str | None = None
    task_payload: dict[str, object] | None = None
    calendar_payload: dict[str, object] | None = None
    gmail_arguments: dict[str, object] | None = None
    github_arguments: dict[str, object] | None = None
    github_tool_id: str = "github_create_issue"
    task_modification_patch: dict[str, object] | None = None
    scenario_override: str | None = None
    terminal_response_error: bool = False
    _scenario_prompt_counts: dict[tuple[str, str], int] = field(default_factory=dict)

    def probe(self, *, api_key: str, timeout_seconds: int) -> ProbeResult:
        self.invocations.append(
            {
                "kind": "probe",
                "api_key_length": len(api_key),
                "timeout_seconds": timeout_seconds,
            }
        )
        return ProbeResult(availability=AvailabilityState.AVAILABLE)

    def invoke_structured(
        self,
        *,
        model_id: str,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        timeout_seconds: int,
        api_key: str,
        instruction_text: str,
        sampling_temperature: float | None = None,
    ) -> ProviderResponsePayload:
        del instruction_text, sampling_temperature
        prompt_id = prompt_ref.prompt_id
        scenario = self.scenario_override or _scenario(prompt_input)
        key = (scenario, prompt_id)
        self._scenario_prompt_counts[key] = self._scenario_prompt_counts.get(key, 0) + 1
        self.invocations.append(
            {
                "kind": "invoke",
                "model_id": model_id,
                "prompt_id": prompt_id,
                "scenario": scenario,
                "prompt_input": dict(prompt_input),
                "timeout_seconds": timeout_seconds,
                "api_key_length": len(api_key),
            }
        )
        if prompt_id == self.crash_prompt_id and (
            self.crash_scenario is None or scenario == self.crash_scenario
        ):
            # Simulate abrupt process loss at an external boundary. BaseException
            # intentionally bypasses Product failure/recovery translation, just
            # as an actual process termination would.
            raise SystemExit("simulated E2E process loss")
        if prompt_id == "run.compose_terminal_response" and self.terminal_response_error:
            raise LLMInvocationError(
                LLMErrorCode.PROVIDER_TIMEOUT,
                "simulated terminal response timeout",
                retryable=True,
            )
        output = _respond(
            prompt_id,
            prompt_input,
            scenario=scenario,
            call_no=self._scenario_prompt_counts[key],
        )
        if (
            prompt_id == "planning.compose_arguments_per_output_route"
            and "modification" in _base_projection(prompt_input)
        ):
            output["arguments"] = {"payload": dict(self.task_modification_patch or {})}
        if self.task_payload is not None:
            base = _base_projection(prompt_input)
            if (
                prompt_id == "request_understanding.identify_goal"
                and scenario != "MAIL_TASK_CREATE"
            ):
                output["constraints"] = [
                    {"kind": "RESOURCE", "field": name, "value": value}
                    for name, value in self.task_payload.items()
                    if value != ""
                ]
            if prompt_id == "planning.compose_arguments_per_output_route":
                route = cast(Mapping[str, object], base["output_route"])
                if route["resource_type"] == "TASK" and "modification" not in base:
                    output["arguments"] = {"payload": dict(self.task_payload)}
        if self.calendar_payload is not None:
            base = _base_projection(prompt_input)
            if (
                prompt_id == "request_understanding.identify_goal"
                and scenario != "MAIL_CALENDAR_CREATE"
            ):
                output["constraints"] = [
                    {"kind": "RESOURCE", "field": name, "value": value}
                    for name, value in self.calendar_payload.items()
                    if value != ""
                ]
            if prompt_id == "planning.compose_arguments_per_output_route":
                output["arguments"] = {"payload": dict(self.calendar_payload)}
            if prompt_id == "retrieval.plan_query":
                queries = []
                for route in cast(list[Mapping[str, object]], base["input_routes"]):
                    query = _route_query(route)
                    if "calendar_query_freebusy" in cast(list[str], route["allowed_read_tool_ids"]):
                        query["operation"] = "FREEBUSY"
                    if str(route["resource_type"]).startswith("CALENDAR"):
                        spec = cast(dict[str, object], query["search_spec"])
                        constraints = cast(dict[str, object], spec["constraints"])
                        constraints["temporal_range"] = {
                            "kind": "TEMPORAL_RANGE",
                            "axis": (
                                "AVAILABILITY_WINDOW"
                                if query["operation"] == "FREEBUSY"
                                else "EVENT_TIME"
                            ),
                            "start_local": str(self.calendar_payload["start"])[:19],
                            "end_local": str(self.calendar_payload["end"])[:19],
                            "timezone": "Asia/Seoul",
                        }
                    queries.append(query)
                output["route_queries"] = queries
        if (
            self.gmail_arguments is not None
            and prompt_id == "planning.compose_arguments_per_output_route"
        ):
            output["arguments"] = dict(self.gmail_arguments)
        if self.github_arguments is not None:
            if prompt_id == "request_understanding.identify_goal":
                repository = self.github_arguments.get("repository")
                output["constraints"] = (
                    [{"kind": "RESOURCE", "field": "repository", "value": repository}]
                    if repository
                    else []
                )
            if prompt_id == "planning.compose_arguments_per_output_route":
                output["arguments"] = dict(self.github_arguments)
            if prompt_id == "tool_routing.select_tool_if_needed":
                output["selected_tool_id"] = self.github_tool_id
        if prompt_id == "request_understanding.identify_goal":
            _match_goal_constraints_to_schema(output, output_schema)
        return ProviderResponsePayload(
            content=json.dumps(output, sort_keys=True),
            model=model_id,
            provider_request_id=f"e2e-{len(self.invocations)}",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )


def _match_goal_constraints_to_schema(
    output: dict[str, object], output_schema: OutputSchemaDefinition
) -> None:
    properties = output_schema.json_schema.get("properties")
    if not isinstance(properties, Mapping):
        return
    constraints_schema = properties.get("constraints")
    if not isinstance(constraints_schema, Mapping) or constraints_schema.get("type") != "object":
        return
    allowed_slots = constraints_schema.get("properties")
    if not isinstance(allowed_slots, Mapping):
        return
    constraints = output.get("constraints")
    if not isinstance(constraints, list):
        return
    slots: dict[str, object] = {
        str(field): ("NOT_COLLECTION" if field == "coverage_requirement" else [])
        for field in allowed_slots
        if field != "additional_constraints"
    }
    additional_constraints: list[dict[str, object]] = []
    for constraint in constraints:
        if not isinstance(constraint, Mapping):
            continue
        field = constraint.get("field")
        value = constraint.get("value")
        if not isinstance(field, str):
            continue
        if field not in slots:
            additional_constraints.append({"field": field, "value": value})
            continue
        values = value if isinstance(value, list) else [value]
        normalized = [item for item in values if isinstance(item, str) and item]
        if normalized:
            slots[field] = normalized
    slots["additional_constraints"] = additional_constraints
    output["constraints"] = slots


def _respond(
    prompt_id: str,
    prompt_input: Mapping[str, object],
    *,
    scenario: str,
    call_no: int,
) -> dict[str, object]:
    base = _base_projection(prompt_input)
    if prompt_id == "request_understanding.identify_goal":
        request_text = str(base["user_request"])
        return {
            "goal": request_text,
            "completion_conditions": ["E2E terminal outcome"],
            "constraints": [],
            "analysis_requirement": "REQUIRED" if scenario == "ANALYTICAL_READ" else "NONE",
        }
    if prompt_id == "request_understanding.identify_effect_prohibitions":
        return {
            "effect_prohibitions": [
                {
                    "effect": candidate["effect"],
                    "prohibition": "NOT_FORBIDDEN",
                }
                for candidate in cast(Sequence[Mapping[str, object]], base["effect_candidates"])
            ]
        }
    if prompt_id == "request_understanding.identify_source_dependencies":
        return _goal_source_dependency_decisions(base, scenario)
    if prompt_id == "request_understanding.identify_output_responsibilities":
        return _goal_output_responsibility_decisions(base, scenario)
    if prompt_id == "request_understanding.identify_source_status":
        return {"statuses": []}
    if prompt_id == "request_understanding.detect_ambiguity":
        needs_confirmation = scenario in {
            "RESTART_RESUME",
            "CALENDAR_CONFIRMATION",
            "GMAIL_CONFIRMATION",
            "UNRESOLVED_TARGET_CONFIRMATION",
        } and not isinstance(base.get("confirmation_response"), Mapping)
        return {
            "missing_information_owner": "USER" if needs_confirmation else "NONE",
            "missing_fields": [
                "attendee"
                if scenario == "CALENDAR_CONFIRMATION"
                else (
                    "target_resource" if scenario == "UNRESOLVED_TARGET_CONFIRMATION" else "target"
                )
            ]
            if needs_confirmation
            else [],
        }
    if prompt_id == "tool_routing.determine_io_resources":
        inputs, outputs, effects = _route_semantics(scenario)
        return {
            "schema_version": 1,
            "input_resource_types": inputs,
            "output_resource_types": outputs,
            "output_effects": effects,
            "disposition": "NO_TOOL_NEEDED" if not inputs and not outputs else "ROUTE_READY",
        }
    if prompt_id == "tool_routing.select_tool_if_needed":
        route = cast(Mapping[str, object], base["route_candidate"])
        candidates = cast(list[Mapping[str, str]], base["registered_candidates"])
        selected = _select_tool(
            str(route["resource_type"]),
            str(route["effect"]),
            [item["tool_id"] for item in candidates],
        )
        return {
            "schema_version": 1,
            "route_id": str(route["route_id"]),
            "selected_tool_id": selected,
        }
    if prompt_id == "retrieval.plan_query":
        routes = cast(list[Mapping[str, object]], base["input_routes"])
        searchable_routes = [
            route
            for route in routes
            if _has_search_tool(route)
            or "calendar_query_freebusy" in cast(list[str], route["allowed_read_tool_ids"])
        ]
        is_followup = "current_round_no" in base
        planned_routes = (
            [route for route in searchable_routes if _supports_semantic_expansion(route)]
            if is_followup
            else searchable_routes
        )
        route_queries = [_route_query(route, is_followup=is_followup) for route in planned_routes]
        if not is_followup:
            for route, query in zip(planned_routes, route_queries, strict=True):
                if "calendar_query_freebusy" in cast(list[str], route["allowed_read_tool_ids"]):
                    query["operation"] = "FREEBUSY"
                    spec = cast(dict[str, object], query["search_spec"])
                    constraints = cast(dict[str, object], spec["constraints"])
                    constraints["temporal_range"] = {
                        "kind": "TEMPORAL_RANGE",
                        "axis": "AVAILABILITY_WINDOW",
                        "start_local": "2026-09-03T09:00:00",
                        "end_local": "2026-09-03T10:00:00",
                        "timezone": "Asia/Seoul",
                    }
        return {
            "schema_version": 3,
            "route_queries": route_queries,
        }
    if prompt_id == "retrieval.select_evidence":
        ranked = cast(list[Mapping[str, object]], base.get("ranked_segments", []))
        selected_segment_ids = [str(item["segment_id"]) for item in ranked]
        return {
            "schema_version": 3,
            "segment_assessments": {
                segment_id: {
                    "role": "SUPPORTS",
                    "relevance_reason": "E2E source evidence",
                }
                for segment_id in selected_segment_ids
            },
        }
    if prompt_id == "retrieval.assess_sufficiency":
        return {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
    if prompt_id == "work_analysis.extract_work_facts":
        task_refs = _task_evidence_refs(base)
        if scenario == "TASK_DUPLICATE_REEVALUATION" and call_no == 1:
            return {"fact_candidates": []}
        if task_refs:
            return {
                "fact_candidates": [
                    {
                        "kind": "TASK",
                        "subject": "Existing E2E task",
                        "value": "E2E task",
                        "derivation": "EXPLICIT",
                        "evidence_refs": [task_refs[0]],
                    }
                ]
            }
        return {"fact_candidates": []}
    if prompt_id in {
        "work_analysis.resolve_entity_relations",
        "work_analysis.resolve_temporal_dependencies",
    }:
        return {"relation_candidates": []}
    if prompt_id == "work_analysis.detect_duplicate_conflict_candidates":
        return {"relation_candidates": []}
    if prompt_id == "work_analysis.assess_requested_task_satisfaction":
        source_state = cast(Mapping[str, object], base["source_state"])
        task_candidates = cast(
            list[Mapping[str, object]], source_state.get("task_review_candidates", [])
        )
        if scenario == "TASK_DUPLICATE_NO_ACTION":
            facts = cast(list[Mapping[str, object]], base["work_facts"])
            fact = facts[0]
            refs = cast(list[str], fact["evidence_refs"])
            return {
                "requested_work_status": "SATISFIED",
                "requested_work_reason": "The current Task already fulfils the request",
                "matched_fact_ids": [str(fact["fact_id"])],
                "matched_candidate_refs": [str(item["candidate_ref"]) for item in task_candidates],
                "evidence_refs": refs,
            }
        return {
            "requested_work_status": "NOT_SATISFIED",
            "requested_work_reason": "Observed tasks do not satisfy the request",
            "matched_fact_ids": [],
            "matched_candidate_refs": [],
            "evidence_refs": [],
        }
    if prompt_id == "work_analysis.assess_action_necessity":
        routes = cast(list[Mapping[str, object]], base["output_routes"])
        duplicate_assessment = cast(
            Mapping[str, object], base.get("duplicate_conflict_assessment", {})
        )
        duplicate_satisfied = duplicate_assessment.get("requested_work_status") == "SATISFIED"
        evidence_refs = (
            list(cast(list[str], duplicate_assessment.get("evidence_refs", [])))
            if duplicate_satisfied
            else []
        )
        candidate_refs = (
            list(cast(list[str], duplicate_assessment.get("matched_candidate_refs", [])))
            if duplicate_satisfied
            else []
        )
        return {
            "route_assessments": [
                {
                    "route_id": str(route["route_id"]),
                    "status": "NOT_REQUIRED" if duplicate_satisfied else "REQUIRED",
                    "reason": (
                        "THE_REQUESTED_EXTERNAL_EFFECT_IS_ALREADY_SATISFIED"
                        if duplicate_satisfied
                        else "THE_REQUESTED_EXTERNAL_EFFECT_IS_NOT_YET_SATISFIED"
                    ),
                    "evidence_refs": evidence_refs,
                    "candidate_refs": candidate_refs,
                }
                for route in routes
            ]
        }
    if prompt_id == "work_analysis.assess_information_gaps":
        return {
            "disposition": "COMPLETE",
            "ambiguities": [],
            "retrieval_needs": [],
            "evidence_refs": [],
        }
    if prompt_id == "work_analysis.assess_operational_risks":
        return {
            "risks": [],
            "evidence_refs": [],
        }
    if prompt_id == "planning.outline_answer":
        refs = _evidence_refs(base)
        return {"sections": ["E2E result"], "evidence_refs": refs}
    if prompt_id == "planning.compose_answer":
        outline = cast(Mapping[str, object], base["answer_outline"])
        return {
            "schema_version": 2,
            "answer": _answer_for(scenario),
            "evidence_refs": list(cast(list[str], outline["evidence_refs"])),
        }
    if prompt_id == "planning.draft_action_objective_per_output_route":
        route = cast(Mapping[str, object], base["output_route"])
        output = {
            "schema_version": 1,
            "objective": f"E2E {scenario}",
            "scope_constraints": ["Use only the frozen output route"],
            "evidence_refs": _evidence_refs(base),
        }
        if (
            route.get("resource_type") == "GMAIL_MESSAGE"
            and route.get("effect") == "SEND"
            and route.get("selected_tool_id") == "gmail_send"
        ):
            output["target_semantics"] = "GMAIL_MESSAGE"
        return output
    if prompt_id == "planning.compose_arguments_per_output_route":
        route = cast(Mapping[str, object], base["output_route"])
        return {
            "schema_version": 1,
            "route_id": str(route["route_id"]),
            "arguments": _arguments(str(route["resource_type"]), scenario),
            "evidence_refs": _evidence_refs(base),
        }
    if prompt_id == "run.compose_terminal_response":
        result_kind = base.get("result_kind")
        return {
            "answer": (
                "검증된 실행 결과를 반영했습니다."
                if result_kind == "SUCCESS"
                else "완료된 항목과 실행되지 않은 항목을 구분해 반영했습니다."
            )
        }
    if prompt_id.startswith("review.inspect_"):
        findings: list[dict[str, object]] = []
        if (
            scenario in {"REVIEW_BACK_EDGE", "EVIDENCE_BACK_EDGE"}
            and prompt_id == "review.inspect_action_scope_and_route"
            and call_no == 1
        ):
            action_ids, route_ids = _action_and_route_ids(base)
            finding_kind = "EVIDENCE_GAP" if scenario == "EVIDENCE_BACK_EDGE" else "ISSUE"
            findings.append(
                {
                    "dimension": prompt_id,
                    "code": "E2E_ACTION_REVISION",
                    "finding_kind": finding_kind,
                    "description": "승인 전 계획 수정과 해당 검토 항목의 재검사가 필요합니다.",
                    "evidence_refs": [],
                    "affected_action_ids": action_ids,
                    "affected_route_ids": route_ids,
                    "required_information": (
                        ["Additional deterministic E2E evidence"]
                        if finding_kind == "EVIDENCE_GAP"
                        else []
                    ),
                }
            )
        return {"schema_version": 1, "dimension": prompt_id, "findings": findings}
    if prompt_id == "review.recheck_affected_dimensions":
        dimensions = cast(list[str], base["affected_dimensions"])
        transition = base.get("proposal_transition")
        historical = (
            transition.get("historical_review_issues")
            if isinstance(transition, Mapping)
            else None
        )
        return {
            "schema_version": 2,
            "affected_dimensions": dimensions,
            "issue_assessments": [
                {"issue_index": index, "state": "RESOLVED", "current_reason": "fixture resolved"}
                for index in range(len(historical) if isinstance(historical, list) else 0)
            ],
            "findings": [],
        }
    raise AssertionError(f"unhandled E2E Product Prompt: {prompt_id}")


def _base_projection(prompt_input: Mapping[str, object]) -> Mapping[str, object]:
    value = prompt_input.get("base_projection")
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else prompt_input


def _scenario(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, default=str).upper()
    for scenario in (
        "GITHUB_CREATE",
        "GITHUB_UPDATE",
        "GITHUB_CLOSE",
        "GITHUB_REOPEN",
        "GITHUB_READ",
        "GMAIL_DRAFT_CREATE",
        "GMAIL_DRAFT_UPDATE",
        "GMAIL_SEND",
        "GMAIL_REPLY",
        "GMAIL_CONFIRMATION",
        "MAIL_CALENDAR_CREATE",
        "CALENDAR_CONFIRMATION",
        "MAIL_TASK_CREATE",
        "TASK_DUPLICATE_NO_ACTION",
        "TASK_DUPLICATE_REEVALUATION",
        "TASK_NONDUPLICATE_PREVIEW",
        "EVIDENCE_BACK_EDGE",
        "ANALYTICAL_READ",
        "RETRIEVAL_CACHE_LOSS",
        "UNKNOWN_RESULT_RECOVERY",
        "VERIFICATION_MISMATCH",
        "CONTEXT_ADJUSTMENT",
        "PARTIAL_APPROVAL",
        "CALENDAR_WRITE",
        "PROCESS_RESTART",
        "RESPONSE_LOSS",
        "MCP_FAILURE",
        "REVIEW_BACK_EDGE",
        "RESTART_RESUME",
        "UNKNOWN_RESULT",
        "APPROVED_WRITE",
        "FAILED_RETRY",
        "ANSWER_ONLY",
        "CALENDAR_READ",
        "TASKS_READ",
        "GMAIL_READ",
        "REJECTION",
        "RECOVERY",
        "REAUTH",
        "CANCEL",
    ):
        if scenario in serialized:
            return scenario
    return "ANSWER_ONLY"


def _answer_for(scenario: str) -> str:
    return {
        "ANSWER_ONLY": "현재 요청을 처리할 준비가 되어 있습니다.",
        "GMAIL_READ": "선택한 메일의 핵심 내용은 deterministic Gmail evidence입니다.",
        "TASKS_READ": "확인한 태스크의 핵심 내용은 E2E task입니다.",
        "CALENDAR_READ": "확인한 일정의 핵심 내용은 E2E event입니다.",
        "TASK_DUPLICATE_NO_ACTION": "같은 할 일이 이미 있어 새로 만들지 않았습니다.",
    }.get(scenario, f"E2E 결과를 정리했습니다: {scenario}")


def _effect_for(scenario: str) -> str:
    if scenario in {"GITHUB_UPDATE", "GITHUB_CLOSE", "GITHUB_REOPEN"}:
        return "UPDATE"
    if scenario in {"GMAIL_SEND", "GMAIL_REPLY", "GMAIL_CONFIRMATION"}:
        return "SEND"
    if scenario == "GMAIL_DRAFT_UPDATE":
        return "UPDATE"
    if scenario == "ANSWER_ONLY":
        return "READ"
    if scenario.endswith("_READ"):
        return "READ"
    return "CREATE"


def _goal_resource_responsibilities(scenario: str) -> dict[str, object]:
    inputs, outputs, effects = _route_semantics(scenario)
    aliases = {
        "EMAIL": "GMAIL_THREAD",
        "ISSUE": "GITHUB_ISSUE",
        "TASK": "TASK",
        "CALENDAR": "CALENDAR_EVENT",
    }
    source_types = list(dict.fromkeys(aliases[item] for item in inputs))
    if scenario in {"GMAIL_DRAFT_CREATE", "GMAIL_SEND", "GMAIL_CONFIRMATION"}:
        source_types = []
    elif scenario == "GMAIL_DRAFT_UPDATE":
        source_types = ["GMAIL_DRAFT"]
    output_types = [aliases[item] for item in outputs]
    if scenario == "GMAIL_DRAFT_CREATE" or scenario == "GMAIL_DRAFT_UPDATE":
        output_types = ["GMAIL_DRAFT"]
    elif scenario in {"GMAIL_SEND", "GMAIL_REPLY", "GMAIL_CONFIRMATION"}:
        output_types = ["GMAIL_MESSAGE"]
    return {
        "source_reads": [
            {"resource_type": resource_type, "required_information": []}
            for resource_type in source_types
        ],
        "outputs": [
            {"resource_type": resource_type, "effect": effect}
            for resource_type, effect in zip(output_types, effects, strict=True)
        ],
    }


def _goal_source_dependency_decisions(
    projection: Mapping[str, object], scenario: str
) -> dict[str, object]:
    responsibilities = _goal_resource_responsibilities(scenario)
    source_reads = {
        str(item["resource_type"]): list(cast(list[str], item["required_information"]))
        for item in cast(list[Mapping[str, object]], responsibilities["source_reads"])
    }
    candidates = cast(list[Mapping[str, object]], projection["source_candidates"])
    decisions: list[dict[str, object]] = []
    for candidate in candidates:
        resource_type = str(candidate["resource_type"])
        required_information = source_reads.get(resource_type)
        if required_information is not None:
            if not required_information:
                owned_fact_kinds = cast(list[object], candidate["owned_fact_kinds"])
                required_information = [str(owned_fact_kinds[0])]
            decisions.append(
                {
                    "resource_type": resource_type,
                    "dependency": "SOURCE_REQUIRED",
                    "required_information": required_information,
                    "target_scope": _e2e_target_scope(
                        scenario,
                        resource_type=resource_type,
                        projection=projection,
                    ),
                }
            )
        else:
            decisions.append({"resource_type": resource_type, "dependency": "SOURCE_NOT_REQUIRED"})
    return {"source_dependencies": decisions}


def _e2e_target_scope(
    scenario: str,
    *,
    resource_type: str,
    projection: Mapping[str, object],
) -> str:
    selected = cast(list[Mapping[str, object]], projection.get("selected_resource_refs", []))
    if any(str(item.get("resource_type", "")).upper() in resource_type for item in selected):
        return "SINGULAR"
    if scenario in {
        "GITHUB_UPDATE",
        "GITHUB_CLOSE",
        "GITHUB_REOPEN",
        "GMAIL_DRAFT_UPDATE",
        "GMAIL_REPLY",
        "UNRESOLVED_TARGET_CONFIRMATION",
    }:
        return "SINGULAR"
    return "CRITERIA"


def _goal_output_responsibility_decisions(
    projection: Mapping[str, object], scenario: str
) -> dict[str, object]:
    responsibilities = _goal_resource_responsibilities(scenario)
    outputs = {
        str(item["resource_type"]): str(item["effect"])
        for item in cast(list[Mapping[str, object]], responsibilities["outputs"])
    }
    candidates = cast(list[Mapping[str, object]], projection["output_candidates"])
    return {
        "output_responsibilities": [
            {
                "resource_type": candidate["resource_type"],
                "effect": outputs[str(candidate["resource_type"])],
            }
            for candidate in candidates
            if str(candidate["resource_type"]) in outputs
        ]
    }


def _route_semantics(scenario: str) -> tuple[list[str], list[str], list[str]]:
    if scenario.startswith("GITHUB_"):
        return (
            (["ISSUE"], [], [])
            if scenario == "GITHUB_READ"
            else (
                [] if scenario == "GITHUB_CREATE" else ["ISSUE"],
                ["ISSUE"],
                [_effect_for(scenario)],
            )
        )
    if scenario in {
        "GMAIL_DRAFT_CREATE",
        "GMAIL_DRAFT_UPDATE",
        "GMAIL_SEND",
        "GMAIL_REPLY",
        "GMAIL_CONFIRMATION",
    }:
        return ["EMAIL"], ["EMAIL"], [_effect_for(scenario)]
    if scenario == "MAIL_CALENDAR_CREATE":
        return ["EMAIL"], ["CALENDAR"], ["CREATE"]
    if scenario == "ANSWER_ONLY":
        return [], [], []
    if scenario in {"GMAIL_READ", "ANALYTICAL_READ"}:
        return ["EMAIL"], [], []
    if scenario == "TASKS_READ":
        return ["TASK"], [], []
    if scenario == "CALENDAR_READ":
        return ["CALENDAR"], [], []
    if scenario == "UNRESOLVED_TARGET_CONFIRMATION":
        return ["CALENDAR"], [], []
    if scenario == "PARTIAL_APPROVAL":
        return ["TASK", "CALENDAR"], ["TASK", "CALENDAR"], ["CREATE", "CREATE"]
    if scenario in {"EVIDENCE_BACK_EDGE", "CONTEXT_ADJUSTMENT", "MAIL_TASK_CREATE"}:
        return ["EMAIL"], ["TASK"], ["CREATE"]
    if scenario in {"CALENDAR_WRITE", "CALENDAR_CONFIRMATION", "VERIFICATION_MISMATCH", "RECOVERY"}:
        return ["CALENDAR"], ["CALENDAR"], ["CREATE"]
    return ["TASK"], ["TASK"], ["CREATE"]


def _select_tool(resource_type: str, effect: str, candidates: list[str]) -> str:
    preferences = {
        ("EMAIL", "READ"): "gmail_search_threads",
        ("TASK", "READ"): "tasks_list_tasks",
        ("CALENDAR", "READ"): "calendar_list_events",
    }
    preferred = preferences.get((resource_type, effect))
    if preferred in candidates:
        return cast(str, preferred)
    return candidates[0]


def _route_query(route: Mapping[str, object], *, is_followup: bool = False) -> dict[str, object]:
    resource_type = str(route["resource_type"])
    if resource_type == "EMAIL":
        supported_kinds = cast(list[str], route.get("supported_constraint_kinds", []))
        constraint: dict[str, object]
        if is_followup and "CONCEPT" in supported_kinds:
            constraint = {
                "kind": "CONCEPT",
                "concept": "additional deterministic evidence",
                "manifestations": ["E2E follow-up"],
            }
        else:
            constraint = {
                "kind": "KEYWORD",
                "terms": ["E2E follow-up" if is_followup else "E2E"],
                "match_mode": "ANY",
            }
    else:
        container_refs = cast(list[str], route.get("container_refs", []))
        if not container_refs:
            raise AssertionError(f"{resource_type} E2E route did not receive a validated container")
        constraint = {"kind": "CONTAINER_REF", "container_refs": [container_refs[0]]}
    constraint_slots = {str(constraint["kind"]).lower(): constraint}
    return {
        "route_id": str(route["route_id"]),
        "operation": "SEARCH",
        "reason_codes": ["USER_REQUEST"],
        "search_spec": (
            {
                "mode": "CHANGED",
                "constraint_delta": {
                    "upsert_constraints": constraint_slots,
                    "remove_constraint_kinds": [],
                },
            }
            if is_followup
            else {"mode": "INITIAL", "constraints": constraint_slots}
        ),
        "detail_candidate_ref": None,
    }


def _has_search_tool(route: Mapping[str, object]) -> bool:
    tools = cast(list[str], route.get("allowed_read_tool_ids", []))
    return any("search" in tool or "list" in tool for tool in tools)


def _supports_semantic_expansion(route: Mapping[str, object]) -> bool:
    kinds = route.get("supported_constraint_kinds", [])
    return isinstance(kinds, list) and bool({"CONCEPT", "KEYWORD"}.intersection(kinds))


def _evidence_refs(prompt_input: Mapping[str, object]) -> list[str]:
    evidence = cast(list[Mapping[str, object]], prompt_input.get("evidence", []))
    return [
        str(ref)
        for item in evidence
        for ref in (item.get("evidence_ref") or item.get("evidence_id") or item.get("id"),)
        if isinstance(ref, str) and ref
    ]


def _task_evidence_refs(prompt_input: Mapping[str, object]) -> list[str]:
    evidence = cast(list[Mapping[str, object]], prompt_input.get("evidence", []))
    return [
        str(ref)
        for item in evidence
        if str(item.get("resource_handle", "")).startswith("task:")
        for ref in (item.get("evidence_ref") or item.get("evidence_id") or item.get("id"),)
        if isinstance(ref, str) and ref
    ]


def _arguments(resource_type: str, scenario: str) -> dict[str, object]:
    payload: dict[str, object] = {"title": f"E2E {scenario}"}
    if resource_type == "CALENDAR_EVENT":
        payload.update(
            {
                "start": "2026-09-03T09:00:00+09:00",
                "end": "2026-09-03T10:00:00+09:00",
            }
        )
    return {"payload": payload}


def _action_and_route_ids(prompt_input: Mapping[str, object]) -> tuple[list[str], list[str]]:
    planning = cast(Mapping[str, object], prompt_input.get("planning_result", {}))
    actions = cast(list[Mapping[str, object]], planning.get("actions", []))
    return (
        [str(item["action_id"]) for item in actions if item.get("action_id")],
        [str(item["route_id"]) for item in actions if item.get("route_id")],
    )


__all__ = ["LangGraphE2EGeminiTransport"]
