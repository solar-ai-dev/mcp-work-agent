"""Live Ollama + production Retrieval LangGraph measurement with synthetic READ fixtures.

This is NOT product E2E: Connector, lifecycle and confirmation persistence are fixtures.
No external account is read or written. Product prompts are loaded unchanged from the manifest.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Mapping
from datetime import datetime
from functools import partial
from typing import Any, cast
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from google_work_agent.adapters.langgraph.main.state import GraphState, initial_graph_state
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.retrieval.graph import RetrievalSubgraph
from google_work_agent.adapters.llm.ollama.structured_inference import (
    OllamaStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import (
    PromptRepairSchemaRepairer,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import RunScopedEvidenceStore
from google_work_agent.adapters.system.memory.run_retrieval_cache import InMemoryRunRetrievalCache
from google_work_agent.application.agents.planning.compose_answer import (
    answer_draft_output_schema,
    compose_answer,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerOutlineV1,
)
from google_work_agent.application.agents.planning.outline_answer import (
    answer_outline_output_schema,
    outline_answer,
)
from google_work_agent.application.agents.request_understanding import (
    preserve_vague_read_semantics,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    load_prompt_reference,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    account_provider_dispatch,
    bind_provider_dispatch_budget,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1, JsonValue
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    RuntimePolicy,
    StructuredLLMProvider,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


class MeasurementInference:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.leaf = OllamaStructuredInferenceAdapter(
            "ollama",
            OllamaHTTPClient(),
            "http://127.0.0.1:11434",
            "qwen3.5:9b",
            assemble_instruction_text=partial(assemble_prompt, execution_scope=DEVELOPMENT_SMOKE),
        )

    def infer(
        self, requested_mode: Any, prompt_ref: Any, input_projection: Any, output_schema_ref: Any
    ) -> StructuredInferenceResultV1:
        result = self.invoke_structured(
            prompt_ref=prompt_ref,
            prompt_input=input_projection,
            output_schema=output_schema_ref,
            runtime_policy=RuntimePolicy(),
            api_key=None,
        )
        try:
            content = (
                json.loads(result.content) if isinstance(result.content, str) else result.content
            )
        except ValueError:
            content = result.content
        errors = validate_output_schema(content, output_schema_ref.json_schema)
        if errors:
            content = PromptRepairSchemaRepairer(execution_scope=DEVELOPMENT_SMOKE).repair(
                provider=cast(StructuredLLMProvider, self), prompt_ref=prompt_ref,
                prompt_input=input_projection, failed_output=content,
                output_schema=output_schema_ref, runtime_policy=RuntimePolicy(), api_key=None,
                attempt_no=1, max_attempts=1, failure_reason_code="OUTPUT_SCHEMA_INVALID",
                validator_errors=tuple(errors),
            )
            errors = validate_output_schema(content, output_schema_ref.json_schema)
        if errors:
            raise ValueError(f"{prompt_ref.prompt_id}: {errors}")
        return StructuredInferenceResultV1(
            1, cast(dict[str, object], content), "ollama", result.model, "LOCAL_GPU",
            result.input_tokens or 0, result.output_tokens or 0, result.latency_ms, None,
        )

    def invoke_structured(self, **kwargs: Any) -> Any:
        account_provider_dispatch()
        result = self.leaf.invoke_structured(**kwargs)
        prompt_ref = kwargs["prompt_ref"]
        try:
            content = (
                json.loads(result.content) if isinstance(result.content, str) else result.content
            )
        except ValueError:
            content = result.content
        errors = validate_output_schema(content, kwargs["output_schema"].json_schema)
        self.calls.append(
            {
                "prompt": prompt_ref.prompt_id,
                "version": prompt_ref.prompt_version,
                "hash": prompt_ref.content_hash,
                "actual_model": result.model,
                "runtime_provider": "ollama",
                "requested_mode": "LOCAL_GPU",
                "inference_class": "ROUTER_BYPASSED_LEAF_MEASUREMENT",
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "schema_errors": errors,
            }
        )
        return result


class FixtureConnector:
    def __init__(
        self, *, empty: bool = False, fail_detail: bool = False, person: str | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_detail = fail_detail
        self.items = (
            []
            if empty
            else [
                self.item(
                    "august-announcement",
                    "한마음 체육대회 안내",
                    "2026년 9월 3일 오전 10시에 체육대회를 개최합니다. 장소는 강당입니다.",
                    "2026-08-25T09:00:00+09:00",
                ),
                self.item(
                    "newsletter-period",
                    "주간 행사 소식",
                    "이 뉴스레터의 집계 기간은 2026년 9월 1일부터 9월 7일까지입니다. "
                    "이번 호에는 확정된 행사 정보가 없습니다.",
                    "2026-09-02T09:00:00+09:00",
                ),
                self.item(
                    "later-event",
                    "개발자 간담회 안내",
                    "간담회는 2026년 9월 15일 오후 2시에 열립니다.",
                    "2026-09-03T09:00:00+09:00",
                ),
                self.item(
                    "yearless-event",
                    "공동 연수 안내",
                    "연수는 9월 4일 오전 11시입니다. 원문에는 연도가 기재되지 않았습니다.",
                    "2026-08-26T09:00:00+09:00",
                ),
            ]
        )
        if person is not None:
            self.items = []
            identities = [("김하늘 대리", "first@example.test")]
            if person == "person_multiple":
                identities.append(("김바다 대리", "second@example.test"))
            for index, (name, email) in enumerate(identities):
                item = self.item(str(index), "검토 안내", "검토 결과를 확인해 주세요.",
                                 "2026-09-02T09:00:00+09:00")
                item["payload"].update(sender_name=name, sender_email=email)
                self.items.append(item)
                alias = self.item(f"{index}-email", "추가 확인", "추가 검토가 끝났습니다.",
                                  "2026-09-03T09:00:00+09:00")
                alias["payload"].update(sender_name="", sender_email=email)
                self.items.append(alias)

    @staticmethod
    def item(identity: str, subject: str, body: str, received: str) -> dict[str, Any]:
        return {
            "resource_type": "gmail_thread",
            "resource_id": identity,
            "parent_id": None,
            "version": "fixture-v1",
            "related_resource_ids": [],
            "payload": {
                "subject": subject,
                "body": body,
                "sender_name": "검증 담당",
                "sender_email": "fixture@example.test",
                "received_at": received,
            },
        }

    def execute_read(self, binding: Any, arguments: dict[str, Any]) -> ConnectorReadResultV1:
        self.calls.append(
            {"connector_id": binding.connector_id, "tool": binding.tool_id, "arguments": arguments}
        )
        if binding.tool_id == "gmail_get_thread":
            if self.fail_detail:
                raise ConnectorOperationFailure(
                    ConnectorFailureCode.PERMISSION_DENIED, "FIXTURE_DETAIL_ACCESS_REMOVED",
                )
            item = next(
                item for item in self.items if item["resource_id"] == arguments["thread_id"]
            )
            output: dict[str, Any] = {"item": item}
        else:
            query = arguments.get("query", "")
            items = list(self.items)
            for operator, stamp in re.findall(r"(after|before):(\d+)", query):
                items = [
                    item
                    for item in items
                    if (
                        datetime.fromisoformat(item["payload"]["received_at"]).timestamp()
                        >= int(stamp)
                        if operator == "after"
                        else datetime.fromisoformat(item["payload"]["received_at"]).timestamp()
                        < int(stamp)
                    )
                ]
            alternatives = re.search(r"\{([^}]+)\}", query)
            def source_text(item: dict[str, Any]) -> str:
                return " ".join(str(value) for value in item["payload"].values())

            if alternatives:
                terms = re.findall(r'"([^"]+)"', alternatives[1])
                if terms:
                    items = [
                        item for item in items if any(term in source_text(item) for term in terms)
                    ]
            remainder = re.sub(r"\{[^}]+\}", "", query)
            for term in re.findall(r'"([^"]+)"', remainder):
                items = [item for item in items if term in source_text(item)]
            emails = re.findall(r'(?:from|to|cc|bcc):"?([^\s"}]+)', query)
            if emails:
                items = [item for item in items if item["payload"]["sender_email"] in emails]
            for term in re.sub(r'"[^"]+"', "", remainder).split():
                if ":" not in term:
                    items = [item for item in items if term in source_text(item)]
            output = {"items": items}
        return ConnectorReadResultV1(
            1,
            binding.tool_id,
            "synthetic-read",
            cast(dict[str, JsonValue], output),
            None,
            len(output.get("items", [output.get("item")])),
        )


def measure(scenario: str) -> dict[str, Any]:
    request_text = (
        "9월 첫째주에 온 메일 찾아줘"
        if scenario in {"receipt", "budget"} else "9월 첫째주 일정 찾아줘"
    )
    if scenario.startswith("person_"):
        request_text = "김대리 메일 찾아줘"
    run_id = str(uuid4())
    now = int(datetime.fromisoformat("2026-09-06T12:00:00+09:00").timestamp() * 1000)
    budget = build_default_run_budget(started_at_ms=now)
    if scenario == "budget":
        budget["detail_fetches_used"] = budget["max_detail_fetches"]
        budget["llm_calls_used"] = budget["llm_call_limit"] - 5
    started = time.monotonic()

    def clock_ms() -> int:
        return now + int((time.monotonic() - started) * 1000)
    request = WorkflowStartRequest(
        run_id=run_id,
        conversation_id=run_id,
        workflow_key=run_id,
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text=request_text,
        selected_resource_ids=(),
        run_budget=budget,
        correlation=WorkflowCorrelationContext(run_id, None, "1"),
    )
    state = initial_graph_state(
        request,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        graph_version="measurement",
        initial_target="context_retriever",
    )
    candidate = preserve_vague_read_semantics.preserve_vague_read_semantics(
        {
            "goal": request_text,
            "completion_conditions": ["근거에 맞는 조회 답변"],
            "constraints": [],
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "analysis_requirement": "NONE",
        },
        request_text=request_text,
        entry_mode="AGENT_SEARCH",
    )
    state["request_intent"] = {
        **candidate,
        "schema_version": 2,
        "meta": {"artifact_id": "intent", "revision": 1, "based_on": []},
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    meta = {
        "artifact_id": "routes",
        "revision": 1,
        "based_on": [{"artifact_id": "intent", "revision": 1}],
    }
    state["tool_route_plan"] = cast(ToolRoutePlanV2, {
        "schema_version": 2,
        "tool_registry_version": "measurement",
        "input_plan": {
            "schema_version": 1,
            "meta": meta,
            "input_routes": [
                {
                    "route_id": "gmail",
                    "resource_type": "GMAIL_THREAD",
                    "connector_id": "google_workspace",
                    "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
                    "required": True,
                    "reason_codes": ["USER_REQUEST"],
                }
            ],
        },
        "output_plan": {
            "schema_version": 1,
            "meta": {**meta, "artifact_id": "output"},
            "output_mode": "ANSWER",
        },
    })
    inference, connector, store = (
        MeasurementInference(),
        FixtureConnector(
            empty=scenario == "empty", fail_detail=scenario == "partial_failure",
            person=scenario if scenario.startswith("person_") else None,
        ),
        RunScopedEvidenceStore(),
    )
    graph = RetrievalSubgraph(
        llm_runtime=inference,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=lambda: str(uuid4()),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda *args: None,
        should_stop_for_cancel=lambda _: False,
        merge_decision=lambda state, update, decision: {
            **state,
            **update,
            **decision["state_update"],
            "__target__": decision["target"],
        },
        evidence_store=store,
        connector_reader=connector,
        tool_catalog=load_development_tool_registry(),
        read_result_cache=InMemoryRunRetrievalCache(),
        confirm_inline=lambda state: (interrupt(state["user_interrupt"]), None),
        now_ms=clock_ms,
        timezone_provider=lambda: "Asia/Seoul",
    ).build()
    wrapper = StateGraph(GraphState)
    wrapper.add_node("retrieval", graph)
    wrapper.add_edge(START, "retrieval")
    wrapper.add_edge("retrieval", END)
    compiled = wrapper.compile(checkpointer=InMemorySaver())
    report: dict[str, Any] = {
        "scenario": scenario,
        "run_id": run_id,
        "verification_kind": "LIVE_OLLAMA_PRODUCTION_RETRIEVAL_GRAPH_FIXTURE_CONNECTOR",
        "product_e2e": False,
        "request": request_text,
        "seeded_llm_calls": budget["llm_calls_used"],
        "seeded_detail_fetches": budget["detail_fetches_used"],
    }
    start = time.monotonic()
    try:
        with provider_dispatch_execution_scope(run_id=run_id, now_ms=clock_ms):
            config: Any = {"recursion_limit": 100, "configurable": {"thread_id": run_id}}
            result = compiled.invoke(state, config=config)
            if result.get("__interrupt__"):
                report["confirmation"] = result["__interrupt__"][0].value
                if scenario == "person_multiple":
                    result = compiled.invoke(Command(resume={
                        "schema_version": 1, "response_kind": "OPTION",
                        "selected_option": "second@example.test", "free_text": None,
                    }), config=config)
            retrieved = result.get("retrieval_result")
            report["retrieval_result"] = retrieved
            if retrieved is not None:
                evidence = store.resolve(run_id=run_id, evidence_refs=retrieved["evidence_refs"])
                report["evidence"] = evidence
                bind_provider_dispatch_budget(result["retry_budget"])

                def invoke(
                    prompt_id: str, prompt_input: Mapping[str, object]
                ) -> Mapping[str, object]:
                    refs = retrieved["evidence_refs"]
                    schema = (
                        answer_outline_output_schema(refs, confirmation_allowed=False)
                        if prompt_id.endswith("outline_answer")
                        else answer_draft_output_schema(refs)
                    )
                    return inference.infer(
                        "LOCAL_GPU",
                        load_prompt_reference(prompt_id, execution_scope=DEVELOPMENT_SMOKE),
                        prompt_input,
                        schema,
                    ).structured_output

                intent = state["request_intent"]
                assert intent is not None
                outline = outline_answer(
                    user_request=request_text,
                    request_intent=intent,
                    work_analysis=None,
                    evidence=evidence,
                    invoke=invoke,
                    retrieval_result=retrieved,
                )
                report["answer"] = compose_answer(
                    user_request=request_text,
                    request_intent=intent,
                    answer_outline=cast(AnswerOutlineV1, outline),
                    work_analysis=None,
                    evidence=evidence,
                    invoke=invoke,
                    retrieval_result=retrieved,
                )
            report["budget"] = result["retry_budget"]
            report["graph_completed"] = not compiled.get_state(config).next
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "detail": str(error)}
    report.update(
        {
            "elapsed_seconds": round(time.monotonic() - start, 2),
            "llm_calls": inference.calls,
            "connector_calls": connector.calls,
        }
    )
    report["checks"] = grade(report)
    report["measurement_status"] = "PASS" if all(report["checks"].values()) else "FAIL"
    return report


def grade(report: dict[str, Any]) -> dict[str, bool]:
    """Fixture oracles check source identity and factual limits, not Run completion alone."""
    result = report.get("retrieval_result") or {}
    evidence = report.get("evidence", [])
    answer = report.get("answer", {}).get("answer", "")
    calls = report["connector_calls"]
    checks = {
        "no_runtime_error": "error" not in report,
        "graph_completed": report.get("graph_completed") is True,
        "answer_present": bool(answer),
        "actual_model": bool(report["llm_calls"])
        and all(call["actual_model"] == "qwen3.5:9b" for call in report["llm_calls"]),
        "no_repeated_read": len(calls) == len({json.dumps(call, sort_keys=True) for call in calls}),
        "citations_for_visible_evidence": not evidence
        or bool(report.get("answer", {}).get("evidence_refs")),
        "no_invented_weekday_or_receipt_conversion": not re.search(
            r"\([월화수목금토일]\)|오후\s*9\s*시",
            answer,
        ),
        "actual_llm_count_matches_budget": (report.get("budget") or {}).get("llm_calls_used")
            == report["seeded_llm_calls"] + len(report["llm_calls"]),
    }
    resources = {item["resource_handle"] for item in evidence}
    scenario = report["scenario"]
    if scenario == "event":
        checks.update({
            "august_received_event_discovered": "gmail_thread:august-announcement" in resources,
            "outside_event_excluded": "gmail_thread:later-event" not in resources,
            "newsletter_not_event": all(
                item["reason_codes"] == ["CONTEXT"] for item in evidence
                if item["resource_handle"] == "gmail_thread:newsletter-period"
            ),
            "yearless_date_preserved": bool(result.get("unresolved_event_dates"))
                and "9월 4일" in answer
                and not re.search(r"2026\s*년\s*9\s*월\s*4\s*일", answer),
            "uncertainty_partial": result.get("coverage") == "PARTIAL" and "부분 결과" in answer,
        })
    elif scenario in {"receipt", "budget"}:
        expected = {
            "gmail_thread:newsletter-period", "gmail_thread:later-event",
        }
        checks["receipt_axis_not_event_axis"] = (
            resources == expected
            if scenario == "receipt"
            else bool(resources) and resources <= expected
        )
        if scenario == "budget":
            checks["budget_partial_with_evidence"] = (
                result.get("coverage") == "PARTIAL" and bool(evidence) and "부분 결과" in answer
            )
            checks["exhausted_detail_not_dispatched"] = all(
                call["tool"] != "gmail_get_thread" for call in calls
            )
    elif scenario.startswith("person_"):
        chosen = "second@example.test" if scenario == "person_multiple" else "first@example.test"
        checks["identity_followup"] = any(
            chosen in call["arguments"].get("query", "") for call in calls
        )
        checks["typed_candidate_provenance"] = bool(result.get("person_candidates")) and all(
            item["source_segment_ids"] for item in result.get("person_candidates", [])
        )
        checks["email_only_evidence_linked"] = any(
            item["resource_handle"].endswith("-email") for item in evidence
        )
        if scenario == "person_multiple":
            checks["same_run_selection"] = (
                bool(report.get("confirmation"))
                and result.get("selected_person_identities") == {"김대리": chosen}
            )
            checks["answer_respects_selected_identity"] = (
                "first@example.test" not in answer and "김하늘" not in answer
                and (chosen in answer or "김바다" in answer)
            )
    elif scenario == "partial_failure":
        checks["failed_read_keeps_partial_evidence"] = (
            result.get("coverage") == "PARTIAL" and bool(evidence) and "부분 결과" in answer
            and any(item["failure_kind"] == "SCOPE" for item in result.get("source_statuses", []))
        )
    else:
        checks["empty_not_failure"] = not evidence and "찾지 못" in answer and all(
            item["failure_kind"] is None for item in result.get("source_statuses", [])
        )
    return checks


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario", choices=["event", "receipt", "empty", "budget", "partial_failure",
                               "person_unique", "person_multiple"],
        required=True,
    )
    arguments = parser.parse_args()
    report = measure(arguments.scenario)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["measurement_status"] == "PASS" else 1)
