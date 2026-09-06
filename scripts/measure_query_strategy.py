"""Production Graph/Router/Local LLM diagnostic against shared synthetic READ corpus.

No Browser, live account or external WRITE. Gold stays in the evaluator after execution;
only the natural-language request, clock and shared Provider corpus enter the Product.
This DEVELOPMENT_SMOKE diagnostic is not release Prompt activation evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

from evaluation.dataset import file_sha256, load_case
from evaluation.grader import grade_case
from fastapi.testclient import TestClient
from tests.support.fakes.retrieval_corpus import RetrievalCorpus
from tests.support.graph_path_recorder import GraphPathRecorder
from tests.support.langgraph_product_driver import API_HEADERS, create_conversation
from tests.support.production_runtime import build_test_production_container

from evaluation.runner import build_result, normalize_snapshot, write_result
from google_work_agent.adapters.connectors.runtime.mcp_connector_read import McpConnectorReadAdapter
from google_work_agent.adapters.connectors.runtime.mcp_connector_write import (
    McpConnectorWriteAdapter,
)
from google_work_agent.adapters.connectors.runtime.mcp_oauth_credential import (
    McpOAuthCredentialAdapter,
)
from google_work_agent.adapters.langgraph.main.graph import WorkflowGraphComposition
from google_work_agent.adapters.llm.ollama import transport as ollama_transport
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.system.system_clock import SystemClockAdapter
from google_work_agent.api.app import create_app
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1, JsonValue
from google_work_agent.ports.connector.oauth_credential_port import OAuthConnectionMetadata
from google_work_agent.ports.llm.structured_inference_contracts import LLMInvocationError

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "evaluation/datasets/retrieval/query_strategy"
SUPPORTED_LOCAL_MODELS = ("qwen3.5:9b", "qwen3.5:4b")


def measure(
    case_id: str, product_sha: str, output: Path, *, fixed_sampling: bool = False,
    enable_thinking: bool = False, model_id: str = "qwen3.5:9b",
) -> dict[str, Any]:
    if model_id not in SUPPORTED_LOCAL_MODELS:
        raise ValueError(f"unsupported local model: {model_id}")
    current_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if current_sha != product_sha:
        raise ValueError("product-sha must identify the current checkout")
    production_diff = subprocess.check_output(["git", "diff", "HEAD", "--", "src"], cwd=ROOT)
    case = load_case(case_id, DATA / "cases.jsonl")
    manifest = json.loads((DATA / "corpus_manifest.json").read_text(encoding="utf-8"))
    corpus_paths = [ROOT / p for p in manifest["splits"][case["split"]]]
    corpus = RetrievalCorpus(corpus_paths, page_size=manifest["page_size"])
    provider_calls: list[dict[str, Any]] = []
    inference_calls: list[dict[str, Any]] = []
    recorder = GraphPathRecorder()
    runtime_root = Path(tempfile.mkdtemp(prefix="gwa-query-strategy-"))
    fixed_ms = int(datetime.fromisoformat(manifest["reference_time"]).timestamp() * 1000)
    start = time.monotonic()
    secret = uuid4().hex

    def item(thread: dict[str, Any], *, detail: bool) -> dict[str, Any]:
        messages = thread.get("messages", [])
        last = messages[-1] if messages else {}
        payload = {"subject": thread["subject"], "participants": thread["participants"]}
        if detail:
            payload.update(
                body="\n\n".join(m["body"] for m in messages),
                sender_email=last.get("sender", ""),
                sender_name=last.get("sender_name", ""),
                received_at=last.get("sent_at"),
                message_count=len(messages),
                messages=[
                    {
                        "message_id": message["message_id"],
                        "thread_id": thread["thread_id"],
                        "sender_name": message.get("sender_name", ""),
                        "sender_email": message["sender"],
                        "recipients": [*message.get("to", []), *message.get("cc", [])],
                        "received_at": message["sent_at"],
                        "subject": thread["subject"],
                        "body": message["body"],
                        "body_truncated": False,
                    }
                    for message in messages
                ],
            )
        return {
            "resource_type": "gmail_thread",
            "resource_id": thread["thread_id"],
            "parent_id": None,
            "version": "shared-corpus-v1",
            "related_resource_ids": [],
            "payload": payload,
        }

    def read(_self: Any, binding: Any, arguments: dict[str, Any]) -> ConnectorReadResultV1:
        call = {
            "connector_id": binding.connector_id,
            "tool": binding.tool_id,
            "arguments": deepcopy(arguments),
            "status": "FAILURE",
            "result_refs": [],
        }
        provider_calls.append(call)
        try:
            if binding.connector_id != "google_workspace" or binding.effect != "READ":
                raise ValueError("unsupported corpus binding")
            if binding.tool_id == "gmail_search_threads":
                result = corpus.search(arguments.get("query", ""), arguments.get("page_token"))
                rows = [item(t, detail=False) for t in result["threads"]]
                payload = {"items": rows, "next_page_token": result["next_page_token"]}
                call["operation"] = "NEXT_PAGE" if arguments.get("page_token") else "SEARCH"
                continuation = result["next_page_token"]
            elif binding.tool_id == "gmail_get_thread":
                row = item(corpus.detail(arguments["thread_id"]), detail=True)
                rows, payload, continuation = [row], {"item": row}, None
                call["operation"] = "DETAIL"
            else:
                raise ValueError("unsupported corpus tool")
            call.update(status="SUCCESS", result_refs=[r["resource_id"] for r in rows])
            return ConnectorReadResultV1(
                1,
                binding.tool_id,
                uuid4().hex,
                cast(dict[str, JsonValue], payload),
                continuation,
                len(rows),
            )
        except (ValueError, KeyError) as error:
            call["failure_code"] = "UNSUPPORTED_FIXTURE_QUERY_OR_TOOL"
            raise ConnectorOperationFailure(
                ConnectorFailureCode.INVALID_ARGUMENT, str(error)
            ) from error

    def connected(_self: Any, connector_id: str) -> OAuthConnectionMetadata:
        return OAuthConnectionMetadata(
            1, connector_id, "synthetic-corpus-account", "corpus@example.test", "CONNECTED", (), ()
        )

    def deny_write(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("external WRITE forbidden in retrieval diagnostic")

    build_graph = WorkflowGraphComposition.build
    post_json = ollama_transport._post_json

    def measured_post_json(**kwargs: Any) -> Any:
        if enable_thinking and kwargs.get("path") == "/api/generate":
            kwargs["payload"] = {**kwargs["payload"], "think": True}
        return post_json(**kwargs)

    with (
        patch.object(ollama_transport, "_post_json", measured_post_json),
        patch.object(McpConnectorReadAdapter, "execute_read", read),
        patch.object(McpConnectorWriteAdapter, "execute_write", deny_write),
        patch.object(McpOAuthCredentialAdapter, "get_connection_status", connected),
        patch.object(
            SystemClockAdapter,
            "now_ms",
            lambda _: fixed_ms + int((time.monotonic() - start) * 1000),
        ),
        patch.object(
            WorkflowGraphComposition,
            "build",
            lambda self: build_graph(self).with_config(callbacks=[recorder]),
        ),
    ):
        container = build_test_production_container(
            runtime_root=runtime_root,
            bootstrap_secret=secret,
            mcp_module_name="tests.fakes.google_workspace_mcp_server",
            keyring_store=SessionMemorySecretStore(),
        )
        container = replace(container, client_address_resolver=lambda _: "127.0.0.1")
        runtime = container.structured_inference_port
        assert runtime is not None
        if fixed_sampling:
            assert isinstance(runtime, StructuredInferenceRuntimeRouter)
            runtime.runtime_policy = replace(
                runtime.runtime_policy, sampling_temperature=0.0, sampling_seed=0,
            )
        local_model_profile = runtime.runtime_selection.local_model_profile
        if local_model_profile is None:
            raise RuntimeError("Local model profile is required for query strategy measurement")
        infer = runtime.infer

        def observed_infer(*args: Any, **kwargs: Any) -> Any:
            try:
                result = infer(*args, **kwargs)
            except LLMInvocationError as error:
                # This runner accepts synthetic corpus only; retain bounded validator diagnostics.
                failure = {
                    "prompt": args[1].prompt_id,
                    "prompt_version": args[1].prompt_version,
                    "prompt_hash": args[1].content_hash,
                    "error_code": error.code.value,
                    "error_detail": str(error)[:4000],
                }
                inference_calls.append(failure)
                print(json.dumps(failure, ensure_ascii=False), flush=True)
                raise
            inference_calls.append(
                {
                    "prompt": args[1].prompt_id,
                    "prompt_version": args[1].prompt_version,
                    "prompt_hash": args[1].content_hash,
                    "model": result.model,
                    "actual_runtime": result.actual_runtime,
                    "inference_class": local_model_profile.inference_class_for_prompt(
                        args[1].prompt_id
                    ),
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "latency_ms": result.latency_ms,
                    "input": deepcopy(args[2]),
                    "output": deepcopy(result.structured_output),
                }
            )
            print(json.dumps({"prompt": args[1].prompt_id, "model": result.model}), flush=True)
            return result

        with (
            patch.object(runtime, "infer", observed_infer),
            TestClient(create_app(container), base_url="http://127.0.0.1:8000") as client,
        ):
            client.headers.update({**API_HEADERS, "X-API-Contract-Version": "1"})
            response = client.post(
                "/api/v1/session/bootstrap",
                json={
                    "schema_version": 1,
                    "bootstrap_secret": secret,
                    "frontend_api_contract_version": "1",
                },
            )
            assert response.status_code == 200, response.text
            response = client.put(
                "/api/v1/settings",
                json={
                    "schema_version": 1,
                    "command_id": uuid4().hex,
                    "settings_patch": {
                        "schema_version": 1,
                        "preferred_local_model_id": model_id,
                        "preferred_llm_mode": "LOCAL_GPU",
                        "external_llm_consent": False,
                    },
                },
            )
            assert response.status_code == 200, response.text
            conversation_id = create_conversation(client, "shared-query-corpus")
            response = client.post(
                "/api/v1/runs",
                json={
                    "api_contract_version": "1",
                    "command_id": uuid4().hex,
                    "conversation_id": conversation_id,
                    "request_text": case["canonical_user_prompt"],
                    "entry_mode": case["entry_mode"],
                    "selected_resource_handles": [],
                    "requested_mode": "LOCAL_GPU",
                },
            )
            assert response.status_code == 202, response.text
            run_id = response.json()["run_id"]
            deadline = time.monotonic() + 600
            snapshot: dict[str, Any] = {}
            while time.monotonic() < deadline:
                snapshot = client.get(f"/api/v1/runs/{run_id}").json()
                if snapshot["run"]["status"] in {
                    "COMPLETED",
                    "BLOCKED",
                    "FAILED",
                    "CANCELLED",
                    "WAITING_CONFIRMATION",
                    "WAITING_APPROVAL",
                    "RECOVERY_REQUIRED",
                    "REAUTH_REQUIRED",
                }:
                    break
                time.sleep(0.25)
            else:
                raise TimeoutError(f"query diagnostic did not settle: {run_id}")
    observed: dict[str, Any] = normalize_snapshot(snapshot)
    observed.update(
        provider_calls=provider_calls,
        query_trajectory=[],
        semantic_constraints=[],
        resolved_identities={},
        terminal_state=snapshot["run"]["status"],
    )
    artifacts: dict[str, Any] = {}
    attempts: dict[str, Any] = {}
    attempt_plans: dict[str, Any] = {}
    for step in sorted(recorder.path, key=lambda row: cast(int, row.get("completed_sequence", 0))):
        for key, typed in cast(dict[str, Any], step.get("typed_results", {})).items():
            artifacts[key] = typed["value"]
            if key in {"query_attempts", "__context_query_attempts__"}:
                for attempt in typed["value"]:
                    if attempt["query_attempt_id"] not in attempts:
                        attempt_plans[attempt["query_attempt_id"]] = deepcopy(
                            artifacts.get("query_plan", {})
                        )
                    attempts[attempt["query_attempt_id"]] = attempt
    observed["semantic_constraints"] = artifacts.get("request_intent", {}).get("constraints", [])
    retrieval = artifacts.get("retrieval_result", {})
    observed["resolved_identities"] = retrieval.get(
        "selected_person_identities", artifacts.get("selected_person_identities", {}),
    )
    if observed["terminal_state"] == "WAITING_CONFIRMATION":
        drafts = artifacts.get("evidence_drafts", [])
        observed["evidence_resource_refs"] = sorted({item["resource_handle"] for item in drafts})
        observed["evidence_ids"] = [item["evidence_id"] for item in drafts]
    observed["pending_interrupt"] = snapshot.get("pending_interrupt")
    observed["person_candidates"] = artifacts.get("person_candidates", [])
    for attempt in attempts.values():
        planned: dict[str, Any] = next(
            (
                q
                for q in attempt_plans[attempt["query_attempt_id"]].get("route_queries", [])
                if q["route_id"] == attempt["route_id"]
                and q["operation"] == attempt["operation_kind"]
            ),
            {},
        )
        observed["query_trajectory"].append(
            {
                "operation": attempt["operation_kind"],
                "constraints": attempt["normalized_intent_constraints"],
                "provider_query": attempt["query_spec"]["canonical_arguments"].get("query", ""),
                "reason_codes": planned.get("reason_codes", []),
                "required_information": attempt_plans[attempt["query_attempt_id"]].get(
                    "required_information", []
                ),
                "observation_refs": [attempt["previous_query_hash"]]
                if attempt["previous_query_hash"]
                else [],
                "query_attempt_id": attempt["query_attempt_id"],
                "stop_reason": attempt["stop_reason"],
            }
        )
    result = build_result(
        case_id=case_id,
        dataset_path=DATA / "cases.jsonl",
        product_sha=product_sha,
        experiment_name="query-strategy-baseline",
        candidate_id="production-development-smoke",
        requested_mode="LOCAL_GPU",
        observed=observed,
        grade=grade_case(case, observed),
    )
    result.update(
        execution_kind="PRODUCTION_GRAPH_LOCAL_LLM_SYNTHETIC_READ",
        sampling_conditions={
            "kind": "EVALUATION_FIXED" if fixed_sampling else "PRODUCT_DEFAULT",
            "temperature": 0.0 if fixed_sampling else None,
            "seed": 0 if fixed_sampling else None,
        },
        thinking_conditions={
            "kind": "EVALUATION_ENABLED" if enable_thinking else "PRODUCT_DEFAULT",
            "enabled": enable_thinking,
        },
        selected_local_model_id=model_id,
        run_id=run_id,
        runtime_root=str(runtime_root),
        graph_path=recorder.path,
        production_diff_sha256=hashlib.sha256(production_diff).hexdigest(),
        production_worktree_modified=bool(production_diff),
        llm_calls=inference_calls,
        corpus_hashes={str(p.relative_to(ROOT)): file_sha256(p) for p in corpus_paths},
        request_intent=artifacts.get("request_intent"),
        retrieval_result=retrieval,
        diagnostic_code_hashes={
            str(p.relative_to(ROOT)): file_sha256(p)
            for p in (
                Path(__file__),
                ROOT / "tests/support/fakes/retrieval_corpus.py",
                ROOT / "tests/support/graph_path_recorder.py",
            )
        },
    )
    if production_diff != subprocess.check_output(["git", "diff", "HEAD", "--", "src"], cwd=ROOT):
        raise RuntimeError(
            "Product source changed during measurement; rerun with a stable checkout"
        )
    write_result(output, result)
    return result


if __name__ == "__main__":
    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixed-sampling", action="store_true",
                        help="Evaluation-only temperature=0/seed=0; not a Product default change")
    parser.add_argument("--enable-thinking", action="store_true",
                        help="Evaluation-only Ollama think=true; reasoning text is not recorded")
    parser.add_argument(
        "--model-id",
        choices=SUPPORTED_LOCAL_MODELS,
        default="qwen3.5:9b",
        help="Installed supported Local model selected through the production Settings path",
    )
    args = parser.parse_args()
    report = measure(
        args.case_id, args.product_sha, args.output, fixed_sampling=args.fixed_sampling,
        enable_thinking=args.enable_thinking, model_id=args.model_id,
    )
    print(json.dumps({"run_id": report["run_id"], "grade": report["grade"]}), flush=True)
    raise SystemExit(0 if report["metrics"]["passed"] else 2)
