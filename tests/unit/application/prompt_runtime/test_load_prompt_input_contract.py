from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    REQUIRED_PROMPT_SLOT_IDS,
    PromptRuntimeInputContractError,
)
from google_work_agent.application.prompt_runtime.load_prompt_input_contract import (
    default_prompt_input_contract_path,
    load_prompt_input_contract,
)


def _payload() -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(default_prompt_input_contract_path().read_text(encoding="utf-8")),
    )


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "prompt_runtime_input_contract_v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_prompt__input_contract_closes__exact_slot_set() -> None:
    contract = load_prompt_input_contract()

    assert contract.schema_version == 1
    assert contract.slot_ids == REQUIRED_PROMPT_SLOT_IDS


def test_goal_contract__retired_output_version__fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    entries = cast(list[dict[str, object]], payload["entries"])
    entry = next(
        item for item in entries if item["prompt_slot_id"] == "request_understanding.identify_goal"
    )
    assert entry["output_schema_version"] == 14
    entry["output_schema_version"] = 1
    with pytest.raises(PromptRuntimeInputContractError, match="schema version"):
        load_prompt_input_contract(_write(tmp_path, payload))


def test_sufficiency_contract__matches_the__live_typed_projection() -> None:
    contract = load_prompt_input_contract()

    contract.validate_projection(
        "retrieval.assess_sufficiency",
        {
            "request_intent": {},
            "selected_evidence": [],
            "temporal_constraints": [],
            "source_statuses": [],
            "budget_state": {
                "additional_rounds_used": 0,
                "additional_rounds_remaining": 2,
            },
        },
    )


def test_select_evidence_contract__matches_the__live_typed_projection() -> None:
    contract = load_prompt_input_contract()

    projection: dict[str, object] = {
        "request_intent": {},
        "ranked_segments": [],
        "temporal_constraints": [],
        "sufficiency_feedback": [],
    }
    contract.validate_projection("retrieval.select_evidence", projection)

    with pytest.raises(PromptRuntimeInputContractError, match="unknown Product Prompt fields"):
        contract.validate_projection(
            "retrieval.select_evidence",
            {**projection, "confirmation_response": {}},
        )


def test_resource_responsibility_contract__requires_preceding_goal_candidate() -> None:
    contract = load_prompt_input_contract()

    contract.validate_projection(
        "request_understanding.identify_resource_responsibilities",
        {
            "user_request": "request",
            "selected_resource_refs": [],
            "goal_candidate": {},
            "resource_candidates": [],
        },
    )
    with pytest.raises(PromptRuntimeInputContractError, match="missing required"):
        contract.validate_projection(
            "request_understanding.identify_resource_responsibilities",
            {
                "user_request": "request",
                "selected_resource_refs": [],
            },
        )


def test_source_status_contract__requires_fixed_source_and_output_roles() -> None:
    contract = load_prompt_input_contract()

    contract.validate_projection(
        "request_understanding.identify_source_status",
        {
            "user_request": "request",
            "selected_resource_refs": [],
            "goal_candidate": {},
            "source_reads": [],
            "outputs": [],
            "allowed_status_values": [],
        },
    )
    with pytest.raises(PromptRuntimeInputContractError, match="missing required"):
        contract.validate_projection(
            "request_understanding.identify_source_status",
            {
                "user_request": "request",
                "selected_resource_refs": [],
                "goal_candidate": {},
                "source_reads": [],
                "outputs": [],
            },
        )


def test_compose_arguments_contract__accepts_current__request_intent_projection() -> None:
    contract = load_prompt_input_contract()

    contract.validate_projection(
        "planning.compose_arguments_per_output_route",
        {
            "output_route": {},
            "action_objective": {},
            "tool_schema": {},
            "request_intent": {},
            "work_analysis": {},
            "evidence": [],
            "run_reference_time": {
                "captured_at": "2026-09-10T10:00:00+09:00",
                "timezone": "Asia/Seoul",
            },
        },
    )


def test_work_analysis_contracts__accept_current__observation_projections() -> None:
    contract = load_prompt_input_contract()

    contract.validate_projection(
        "work_analysis.detect_duplicate_conflict_candidates",
        {
            "work_facts": [],
            "entity_relations": [],
            "evidence": [],
        },
    )


def test_action_objective_contract__matches_the__live_typed_projection() -> None:
    contract = load_prompt_input_contract()

    projection: dict[str, object] = {
        "user_request": "request",
        "request_intent": {},
        "output_route": {},
        "evidence": [],
        "work_analysis": {},
    }
    contract.validate_projection(
        "planning.draft_action_objective_per_output_route", projection
    )

    with pytest.raises(PromptRuntimeInputContractError, match="unknown Product Prompt fields"):
        contract.validate_projection(
            "planning.draft_action_objective_per_output_route",
            {**projection, "confirmation_response": {}},
        )
    contract.validate_projection(
        "work_analysis.assess_requested_task_satisfaction",
        {
            "request_intent": {},
            "work_facts": [],
            "evidence": [],
            "source_state": {"source_statuses": []},
        },
    )
    contract.validate_projection(
        "work_analysis.assess_action_necessity",
        {
            "request_intent": {},
            "output_routes": [],
            "work_facts": [],
            "evidence": [],
            "source_statuses": [],
            "task_review_candidates": [],
            "duplicate_conflict_assessment": {},
        },
    )
    contract.validate_projection(
        "work_analysis.assess_information_gaps",
        {
            "request_intent": {},
            "work_facts": [],
            "evidence": [],
            "source_statuses": [],
            "route_action_necessities": [],
        },
    )
    contract.validate_projection(
        "work_analysis.assess_operational_risks",
        {
            "request_intent": {},
            "work_facts": [],
            "validated_relations": [],
            "evidence": [],
            "source_statuses": [],
        },
    )


def test_load_prompt__input_contract__rejects_schema_version(tmp_path: Path) -> None:
    payload = _payload()
    payload["schema_version"] = 2

    with pytest.raises(PromptRuntimeInputContractError, match="schema version"):
        load_prompt_input_contract(_write(tmp_path, payload))


def test_load_prompt_input__contract_rejects_missing__unknown_and_duplicate_slots(
    tmp_path: Path,
) -> None:
    payload = _payload()
    entries = cast(list[dict[str, object]], payload["entries"])
    removed = entries.pop()
    with pytest.raises(PromptRuntimeInputContractError, match="slot set mismatch"):
        load_prompt_input_contract(_write(tmp_path, payload))

    entries.append(removed)
    entries.append({**removed, "prompt_slot_id": "unknown.slot"})
    with pytest.raises(PromptRuntimeInputContractError, match="slot set mismatch"):
        load_prompt_input_contract(_write(tmp_path, payload))

    entries.pop()
    entries.append(dict(removed))
    with pytest.raises(PromptRuntimeInputContractError, match="duplicate"):
        load_prompt_input_contract(_write(tmp_path, payload))


def test_load_prompt__input_contract_rejects__duplicate_json_field(tmp_path: Path) -> None:
    path = tmp_path / "prompt_runtime_input_contract_v1.json"
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")

    with pytest.raises(PromptRuntimeInputContractError, match="duplicate JSON field"):
        load_prompt_input_contract(path)
