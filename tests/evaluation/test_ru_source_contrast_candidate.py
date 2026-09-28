"""V44 frozen example admission and envelope invariants, with no model calls."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import ru_source_contrast_candidate as candidate

from google_work_agent.application.agents.request_understanding.contracts.source_dependency_decision import (  # noqa: E501
    SourceDependencyCandidateV1,
)
from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_candidates,
    build_source_dependency_output_schema,
    validate_source_dependency_candidate,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)


@pytest.fixture
def catalog() -> list[SourceDependencyCandidateV1]:
    return list(build_source_dependency_candidates(load_development_tool_registry()))


@pytest.fixture
def product_payload(catalog: list[SourceDependencyCandidateV1]) -> dict[str, Any]:
    request = "선택한 자료의 내용을 알려줘."
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(candidate.PROMPT_ID)
    projection = {
        "user_request": request,
        "selected_resource_refs": [],
        "run_reference_time": {"now_utc": "2026-09-28T00:00:00Z"},
        "goal_candidate": {"goal": request},
        "source_candidates": catalog,
        "requested_work": {
            "work_units": [
                {
                    "unit_id": "live-work",
                    "request_provenance": [
                        {
                            "source": "USER_REQUEST",
                            "start_offset": 0,
                            "end_offset": len(request),
                            "source_text": request,
                        }
                    ],
                }
            ],
            "work_relations": [],
        },
    }
    schema = build_source_dependency_output_schema(catalog, work_unit_ids=["live-work"])
    return {
        "model": "fake-no-http",
        "system": assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION),
        "prompt": json.dumps(
            {
                "prompt_ref": {
                    "prompt_id": ref.prompt_id,
                    "prompt_version": ref.prompt_version,
                    "content_hash": ref.content_hash,
                },
                "input": projection,
                "output_schema": schema.json_schema,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "format": deepcopy(schema.json_schema),
        "stream": False,
        "think": False,
        "options": {"num_ctx": 16_384, "temperature": 0.05, "seed": 20260923},
    }


def test_frozen_examples_validate_as_complete_product_decisions(
    catalog: list[SourceDependencyCandidateV1],
) -> None:
    examples = candidate.load_examples(catalog)
    assert len(examples) == 3
    positives = []
    for example in examples:
        decisions = example["output"]["source_dependencies"]
        assert len(decisions) == len(catalog)
        assert {row["resource_type"] for row in decisions} == {
            item["resource_type"] for item in catalog
        }
        assert (
            validate_source_dependency_candidate(
                example["output"], source_candidates=catalog, work_unit_ids=["work-1"]
            )
            == example["output"]
        )
        positives.append(
            {
                row["resource_type"]: row
                for row in decisions
                if row["dependency"] == "SOURCE_REQUIRED"
            }
        )
    assert positives[0] == {}
    assert set(positives[1]) == {"GMAIL_DRAFT"}
    assert positives[1]["GMAIL_DRAFT"]["target_scope"] == "SINGULAR"
    assert set(positives[2]) == {"TASK", "CALENDAR_EVENT"}
    assert all(row["target_scope"] == "CRITERIA" for row in positives[2].values())
    assert all(
        example["input"]["selected_resource_refs"] == [] for example in (examples[0], examples[2])
    )
    assert examples[1]["input"]["selected_resource_refs"][0]["resource_type"] == "gmail_draft"


def test_payload_keeps_exact_role_context_input_schema_and_runtime(
    product_payload: dict[str, Any], catalog: list[SourceDependencyCandidateV1]
) -> None:
    before = deepcopy(product_payload)
    original_body = json.loads(before["prompt"])
    result = candidate.build_payload(product_payload)
    assert product_payload == before
    assert {key for key in result if result[key] != before[key]} == {"system", "prompt"}
    body = json.loads(result["prompt"])
    assert body["input"] == original_body["input"]
    assert body["output_schema"] == original_body["output_schema"] == result["format"]
    assert {key: value for key, value in body.items() if key != "prompt_ref"} == {
        key: value for key, value in original_body.items() if key != "prompt_ref"
    }
    role = PromptRegistry().source_text(candidate.PROMPT_ID).rstrip()
    context = before["system"][len(role) :]
    assert result["system"].startswith(role + "\n\n# 입력·출력 예시\n")
    assert result["system"].endswith(context)
    candidate_role = result["system"][: -len(context)]
    assert (
        json.dumps(
            candidate.load_examples(catalog),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        in candidate_role
    )
    assert body["prompt_ref"] == {
        "prompt_id": candidate.PROMPT_ID,
        "prompt_version": "evaluation-v44-contrast",
        "content_hash": hashlib.sha256(candidate_role.encode("utf-8")).hexdigest(),
    }
    assert "presence_penalty" not in result["options"]
    result["options"]["temperature"] = 1
    result["format"].clear()
    assert product_payload == before


@pytest.mark.parametrize("drift", ["ref", "system", "schema", "format", "revision", "candidate"])
def test_payload_rejects_changed_or_repair_authority(
    product_payload: dict[str, Any], drift: str
) -> None:
    body = json.loads(product_payload["prompt"])
    if drift == "ref":
        body["prompt_ref"]["content_hash"] = "other"
    elif drift == "system":
        product_payload["system"] += "changed"
    elif drift == "schema":
        body["output_schema"] = {}
    elif drift == "format":
        product_payload["format"] = {}
    elif drift == "revision":
        body["input"]["base_projection"] = {}
    else:
        body["input"]["candidate_output"] = {}
    product_payload["prompt"] = json.dumps(body)
    with pytest.raises(ValueError):
        candidate.build_payload(product_payload)


@pytest.mark.parametrize("drift", ["missing", "duplicate", "work", "provenance", "empty_fact"])
def test_example_validation_never_defaults_or_repairs_authored_decisions(
    catalog: list[SourceDependencyCandidateV1],
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = json.loads(candidate.EXAMPLES_PATH.read_text(encoding="utf-8"))
    example = document["examples"][1]
    decisions = example["output"]["source_dependencies"]
    positive = next(row for row in decisions if row["dependency"] == "SOURCE_REQUIRED")
    if drift == "missing":
        decisions.pop()
    elif drift == "duplicate":
        decisions[-1] = deepcopy(decisions[0])
    elif drift == "work":
        positive["work_unit_ids"] = ["unknown"]
    elif drift == "provenance":
        unit = example["input"]["requested_work"]["work_units"][0]
        unit["request_provenance"][0]["source_text"] = "not request"
    else:
        positive["required_information"] = []
    path = tmp_path / "examples.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(candidate, "EXAMPLES_PATH", path)
    with pytest.raises(ValueError):
        candidate.load_examples(catalog)
    assert json.loads(path.read_text(encoding="utf-8")) == document


def test_examples_cannot_be_silently_adapted_to_a_different_catalog(
    catalog: list[SourceDependencyCandidateV1],
) -> None:
    with pytest.raises(ValueError):
        candidate.load_examples(catalog[:-1])


def test_examples_remain_separate_from_live_work_ids_and_are_not_a_model_result(
    product_payload: dict[str, Any], catalog: list[SourceDependencyCandidateV1]
) -> None:
    result = candidate.build_payload(product_payload)
    body = json.loads(result["prompt"])
    assert "examples" not in body["input"]
    assert body["input"]["requested_work"]["work_units"][0]["unit_id"] == "live-work"
    with pytest.raises(ValueError):
        validate_source_dependency_candidate(
            candidate.load_examples(catalog)[1]["output"],
            source_candidates=catalog,
            work_unit_ids=["live-work"],
        )
