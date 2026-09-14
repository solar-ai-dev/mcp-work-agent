from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from evaluation.dataset_v8 import load_cases
from evaluation.grader_v8 import grade_case_v8
from evaluation.public_client_v8 import PublicProductClientV8, PublicRunObservationTimeout
from evaluation.public_runner_v8 import execute_public_case


class _PublicClient:
    def __init__(self) -> None:
        self.run_input: dict[str, Any] | None = None
        self.bindings: list[dict[str, Any]] = []

    def resolve_selection_handles(self, bindings: list[dict[str, Any]]) -> list[str]:
        self.bindings = bindings
        return [f"public-handle-{index}" for index, _ in enumerate(bindings)]

    def create_conversation(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {"conversation_id": "conversation"}

    def start_run(self, **kwargs: Any) -> dict[str, Any]:
        self.run_input = kwargs
        return {"run_id": "run"}

    def wait_for_observation(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return {
            "run": {"run_id": "run", "status": "COMPLETED"},
            "messages": [{"role": "assistant", "content": "확인했습니다."}],
            "actions": [],
            "terminal_result_kind": "SUCCESS",
        }


def test_case_execution_input__never_contains_gold() -> None:
    payload = load_cases()["CASE-CORE-001"].execution_input()

    assert "evaluation_gold" not in payload


def test_case_google_resource_scope__comes_from_provider_fixture() -> None:
    scope = load_cases()["CASE-CORE-033"].google_resource_scope()

    assert len(scope["calendar_ids"]) == 1
    assert len(scope["tasklist_ids"]) == 1
    assert all(scope.values())


def test_public_runner__uses_public_selection_handle_only() -> None:
    case = load_cases()["CASE-CORE-001"]
    client = _PublicClient()

    result = execute_public_case(client, case.execution_input(), auto_approve=False)

    assert result.selection_handle_count == 1
    assert client.bindings == case.raw["selected_resource_bindings"]
    assert client.run_input is not None
    assert client.run_input["selected_resource_handles"] == ["public-handle-0"]
    assert case.raw["selected_resource_bindings"][0]["resource_id"] not in str(client.run_input)


def test_public_runner__rejects_gold_leakage() -> None:
    payload = load_cases()["CASE-CORE-001"].execution_input()
    payload["evaluation_gold"] = {"forbidden": True}

    with pytest.raises(ValueError, match="Gold"):
        execute_public_case(_PublicClient(), payload, auto_approve=False)


def test_v8_grader__keeps_deterministic_and_semantic_authorities_separate() -> None:
    case = load_cases()["CASE-CORE-001"].raw
    observation = {
        "public_status": "COMPLETED",
        "terminal_result_kind": "SUCCESS",
        "connector_calls": [],
    }

    missing_review = grade_case_v8(case=case, observation=observation, semantic_review=None)
    passed = grade_case_v8(
        case=case,
        observation=observation,
        semantic_review={
            "required_semantics_satisfied": True,
            "forbidden_semantics_observed": False,
            "brief_reason": "public evidence satisfies the natural-language contract",
        },
    )

    assert missing_review.verdict == "INVALID_HARNESS"
    assert passed.verdict == "PASS"


def test_v8_grader__safety_failure_overrides_semantic_pass() -> None:
    case = load_cases()["CASE-CORE-001"].raw
    grade = grade_case_v8(
        case=case,
        observation={
            "public_status": "COMPLETED",
            "terminal_result_kind": "SUCCESS",
            "connector_calls": [
                {
                    "kind": "CONNECTOR_WRITE",
                    "before_approval": True,
                    "effect_count": 1,
                }
            ],
        },
        semantic_review={
            "required_semantics_satisfied": True,
            "forbidden_semantics_observed": False,
            "brief_reason": "irrelevant to deterministic safety",
        },
    )

    assert grade.verdict == "SAFETY_FAIL"


def test_public_client__timeout_preserves_last_public_snapshot() -> None:
    client = PublicProductClientV8("http://127.0.0.1:1")
    client.get_run = lambda run_id: {  # type: ignore[method-assign]
        "run": {"run_id": run_id, "status": "RETRIEVING"},
        "messages": [],
        "actions": [],
    }

    with pytest.raises(PublicRunObservationTimeout) as caught:
        client.wait_for_observation("run-1", timeout_seconds=0.001, auto_approve=False)

    assert caught.value.run_id == "run-1"
    assert caught.value.snapshot["run"]["status"] == "RETRIEVING"


def test_public_client__selection_scan_uses_safe_type_specific_windows() -> None:
    gmail = PublicProductClientV8("http://127.0.0.1:1")
    gmail_paths: list[str] = []

    def gmail_request(
        method: str, path: str, payload: dict[str, object] | None = None
    ) -> dict[str, Any]:
        del method, payload
        gmail_paths.append(path)
        return {
            "items": [{"resource_id": "thread-1", "selection_handle": "gmail-handle"}],
            "next_page_token": None,
        }

    gmail._request = gmail_request  # type: ignore[method-assign]
    assert gmail.resolve_selection_handles(
        [{"resource_type": "gmail_thread", "resource_id": "thread-1"}]
    ) == ["gmail-handle"]
    assert parse_qs(urlparse(gmail_paths[0]).query)["page_size"] == ["20"]

    calendar = PublicProductClientV8("http://127.0.0.1:1")
    calendar_paths: list[str] = []

    def calendar_request(
        method: str, path: str, payload: dict[str, object] | None = None
    ) -> dict[str, Any]:
        del method, payload
        calendar_paths.append(path)
        return {
            "items": [{"resource_id": "event-1", "selection_handle": "event-handle"}],
            "next_page_token": None,
        }

    calendar._request = calendar_request  # type: ignore[method-assign]
    assert calendar.resolve_selection_handles(
        [
            {
                "resource_type": "calendar_event",
                "resource_id": "event-1",
                "parent_id": "calendar-1",
            }
        ]
    ) == ["event-handle"]
    calendar_query = parse_qs(urlparse(calendar_paths[0]).query)
    assert calendar_query["calendar_id"] == ["calendar-1"]
    assert calendar_query["page_size"] == ["100"]
    assert "time_min" in calendar_query
    assert "time_max" in calendar_query
