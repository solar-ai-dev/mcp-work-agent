from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from evaluation.client import ProductApiClient

# isort: split
from evaluation.runner import main, run_case, write_result


class _ProductApiStub:
    def create_conversation(self, *, command_id: str, title: str) -> dict[str, object]:
        assert command_id and title
        return {"conversation_id": "conversation-1"}

    def start_run(self, **payload: object) -> dict[str, object]:
        assert payload["conversation_id"] == "conversation-1"
        assert set(payload) == {
            "command_id",
            "conversation_id",
            "request_text",
            "entry_mode",
            "selected_resource_handles",
            "requested_mode",
        }
        return {"run_id": "run-1"}

    def wait_for_observable_result(self, run_id: str) -> dict[str, object]:
        assert run_id == "run-1"
        return {
            "run": {"status": "COMPLETED"},
            "messages": [
                {
                    "role": "ASSISTANT",
                    "content": "The requested resource is ready.",
                }
            ],
            "actions": [],
            "approvals": [],
            "verification_summary": {},
            "context_preview": {"resource_refs": ["resource:RES-1"]},
            "pending_interrupt": None,
        }


def test_runner_load__invoke_grade__serialize_chain(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.jsonl"
    case = {
        "case_id": "CASE-1",
        "canonical_user_prompt": "Find the resource",
        "entry_mode": "AGENT_SEARCH",
        "selected_resource_handles": [],
        "requested_outcome": "ANSWER",
        "required_evidence_ids": [],
        "required_resource_ids": ["RES-1"],
        "forbidden_actions": [],
        "allowed_actions": [],
        "approval_expectation": {"required": False},
        "verification_expectation": {"required": False},
        "expected_interactions": [],
        "expected_tool_trajectory": [],
        "end_state_gold": {
            "terminal_expectation": "COMPLETED",
            "expected_mutations": [],
            "forbidden_mutations": [{"scope": "ALL", "rule": "UNCHANGED"}],
        },
    }
    dataset.write_text(json.dumps(case) + "\n", encoding="utf-8")

    result = run_case(
        cast(ProductApiClient, _ProductApiStub()),
        case=case,
        dataset_path=dataset,
        product_sha="a" * 40,
        experiment_name="smoke",
        candidate_id="baseline",
        requested_mode="AUTO",
    )
    output = tmp_path / "results" / "case-1.json"
    write_result(output, result)

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["metrics"] == {"hard_gate_passed": True, "passed": True}
    assert saved["dataset"]["sha256"]
    assert saved["grader_sha256"]
    assert saved["product_sha"] == "a" * 40


def test_runner__external_observation__is_not_a_product_execution(
    tmp_path: Path, monkeypatch
) -> None:
    def no_network(*args, **kwargs):
        raise AssertionError("offline grading must not create a Product client")

    monkeypatch.setattr("evaluation.runner.ProductApiClient", no_network)
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "case_id": "OBS-1",
                "requested_outcome": "ANSWER",
                "end_state_gold": {"terminal_expectation": "COMPLETED"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    observation = tmp_path / "observation.json"
    observation.write_text(
        json.dumps({"final_answer": "", "terminal_state": "COMPLETED"}), encoding="utf-8"
    )
    output = tmp_path / "result.json"
    status = main(
        [
            "--case-id",
            "OBS-1",
            "--dataset",
            str(dataset),
            "--product-sha",
            "a" * 40,
            "--experiment-name",
            "offline",
            "--candidate-id",
            "baseline",
            "--observation",
            str(observation),
            "--output",
            str(output),
        ]
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert status == 2
    assert result["execution_kind"] == "EXTERNAL_OBSERVATION_ONLY"
    assert len(result["observation_sha256"]) == 64
    assert result["metrics"]["passed"] is False
