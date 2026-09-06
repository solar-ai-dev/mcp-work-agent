"""Production Graph/Router/Local LLM diagnostic against shared synthetic READ corpus.

No Browser, live account or external WRITE. Gold stays in the evaluator after execution;
only the natural-language request, clock and shared Provider corpus enter the Product.
This DEVELOPMENT_SMOKE diagnostic is not release Prompt activation evidence.
"""

from __future__ import annotations

import argparse
import json
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
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.adapters.system.system_clock import SystemClockAdapter
from google_work_agent.api.app import create_app
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1, JsonValue
from google_work_agent.ports.connector.oauth_credential_port import OAuthConnectionMetadata

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "evaluation/datasets/retrieval/query_strategy"


def measure(case_id: str, product_sha: str, output: Path) -> dict[str, Any]:
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
                messages=messages,
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
    with (
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
        infer = runtime.infer

        def observed_infer(*args: Any, **kwargs: Any) -> Any:
            result = infer(*args, **kwargs)
            inference_calls.append(
                {
                    "prompt": args[1].prompt_id,
                    "model": result.model,
                    "actual_runtime": result.actual_runtime,
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
                        "preferred_local_model_id": "qwen3.5:9b",
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
    observed["resolved_identities"] = retrieval.get("selected_person_identities", {})
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
        run_id=run_id,
        runtime_root=str(runtime_root),
        graph_path=recorder.path,
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
    write_result(output, result)
    return result


if __name__ == "__main__":
    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = measure(args.case_id, args.product_sha, args.output)
    print(json.dumps({"run_id": report["run_id"], "grade": report["grade"]}), flush=True)
    raise SystemExit(0 if report["metrics"]["passed"] else 2)
