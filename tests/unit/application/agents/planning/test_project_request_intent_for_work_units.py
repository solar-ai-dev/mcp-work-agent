from __future__ import annotations

from google_work_agent.application.agents.planning.project_request_intent_for_work_units import (
    evidence_refs_for_work_units,
    project_request_intent_for_work_units,
)


def test_route_local_projection__selected_work__keeps_owned_semantics() -> None:
    intent = {
        "goal": "Create two independent Issues from one shared email read.",
        "constraints": [
            {"kind": "SCOPE", "field": "team", "value": "A", "work_unit_ids": ["work-1"]},
            {"kind": "SCOPE", "field": "team", "value": "B", "work_unit_ids": ["work-2"]},
        ],
        "effect_prohibitions": [],
        "resource_responsibilities": {
            "source_reads": [
                {
                    "resource_type": "GMAIL_THREAD",
                    "required_information": ["shared facts"],
                    "target_scope": "CRITERIA",
                    "work_unit_ids": ["work-1", "work-2"],
                }
            ],
            "outputs": [
                {
                    "resource_type": "GITHUB_ISSUE",
                    "effect": "CREATE",
                    "work_unit_ids": ["work-1"],
                },
                {
                    "resource_type": "GITHUB_ISSUE",
                    "effect": "CREATE",
                    "work_unit_ids": ["work-2"],
                },
            ],
        },
        "requested_work": {
            "work_units": [
                {"unit_id": "work-1", "request_provenance": []},
                {"unit_id": "work-2", "request_provenance": []},
            ],
            "work_relations": [],
        },
    }

    projected = project_request_intent_for_work_units(intent, work_unit_ids=["work-2"])

    assert projected["constraints"] == [
        {"kind": "SCOPE", "field": "team", "value": "B", "work_unit_ids": ["work-2"]}
    ]
    responsibilities = projected["resource_responsibilities"]
    assert responsibilities["source_reads"][0]["work_unit_ids"] == ["work-2"]
    assert responsibilities["outputs"] == [
        {
            "resource_type": "GITHUB_ISSUE",
            "effect": "CREATE",
            "work_unit_ids": ["work-2"],
        }
    ]
    assert projected["requested_effect_hints"] == ["READ", "CREATE"]


def test_evidence_projection__work_unit_binding__does_not_duplicate_evidence() -> None:
    retrieval = {
        "evidence_refs": ["e-shared"],
        "evidence_by_work_unit": [
            {"work_unit_id": "work-1", "evidence_refs": ["e-shared"]},
            {"work_unit_id": "work-2", "evidence_refs": ["e-shared"]},
        ],
    }

    assert evidence_refs_for_work_units(retrieval, work_unit_ids=["work-2"]) == {"e-shared"}
