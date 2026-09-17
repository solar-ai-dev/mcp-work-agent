from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    REQUEST_RESOURCE_TYPES,
    SOURCE_STATUS_VALUES_BY_RESOURCE,
    WRITE_EFFECT_RESOURCE_TYPES,
)

ROOT = Path(__file__).parents[2]
AGENT_DATASET_ROOT = ROOT / "evaluation" / "development_datasets" / "agent"
V1_DATASET_PATH = AGENT_DATASET_ROOT / "ru_quality_dev_v1.jsonl"
V1_MANIFEST_PATH = AGENT_DATASET_ROOT / "dataset-manifest-ru-quality-dev-v1.json"
DATASET_PATH = AGENT_DATASET_ROOT / "ru_quality_dev_v2.jsonl"
MANIFEST_PATH = AGENT_DATASET_ROOT / "dataset-manifest-ru-quality-dev-v2.json"
CANONICAL_PATH = ROOT / "evaluation" / "datasets" / "e2e" / "canonical_cases_v8.jsonl"

FAMILIES = {
    "AMBIGUITY_CONFIRMATION",
    "READ_VS_WRITE",
    "CREATE_VS_UPDATE",
    "SOURCE_OUTPUT_RESPONSIBILITY",
    "SELECTED_RESOURCE_HANDLING",
    "EFFECT_PROHIBITION",
    "MULTI_SOURCE_RESPONSIBILITY",
    "SOURCE_OVER_SELECTION",
}
DIFFICULTIES = {"EASY", "COMPOSITE", "HARD"}
EFFECTS = {"READ", *WRITE_EFFECT_RESOURCE_TYPES}
CONSTRAINT_KINDS = {
    "PERSON",
    "EMAIL",
    "DATE",
    "TIME",
    "RESOURCE",
    "SCOPE",
    "USER_REQUIREMENT",
}
NORMALIZED_CONSTRAINT_FIELDS = {
    "search_terms",
    "business_concepts",
    "required_information",
    "person",
    "sender",
    "recipient",
    "subject",
    "period",
    "status",
    "coverage_requirement",
    "date",
    "description",
    "due",
    "notes",
    "repository",
    "scheduled_date",
    "title",
    "draft_id",
}
CONSTRAINT_FIELD_KINDS = {
    "search_terms": "USER_REQUIREMENT",
    "business_concepts": "USER_REQUIREMENT",
    "required_information": "USER_REQUIREMENT",
    "person": "PERSON",
    "sender": "PERSON",
    "recipient": "PERSON",
    "subject": "RESOURCE",
    "period": "DATE",
    "status": "SCOPE",
    "coverage_requirement": "SCOPE",
    "date": "DATE",
    "description": "RESOURCE",
    "due": "DATE",
    "notes": "RESOURCE",
    "repository": "RESOURCE",
    "scheduled_date": "DATE",
    "title": "RESOURCE",
    "draft_id": "RESOURCE",
}
CASE_FIELDS = {
    "schema_version",
    "case_id",
    "suite",
    "semantic_family",
    "difficulty",
    "user_request",
    "entry_mode",
    "selected_resource_refs",
    "fixture_conditions",
    "expected_typed_semantic_outcome",
    "forbidden_semantic_outcome",
    "target_ru_responsibility",
    "tags",
    "rationale",
    "pass_criteria",
    "representative_failures",
    "allowed_semantic_variations",
}


def _cases(path: Path = DATASET_PATH) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _normalized_sha256(path: Path) -> str:
    content = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalized_request(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z가-힣]+", " ", value.casefold())).strip()


def test_ru_quality_dev_v2_has_exact_distribution_and_required_fields() -> None:
    cases = _cases()

    assert len(cases) == 24
    assert len({case["case_id"] for case in cases}) == 24
    assert Counter(case["semantic_family"] for case in cases) == {
        family: 3 for family in FAMILIES
    }
    assert Counter(case["difficulty"] for case in cases) == {
        "EASY": 8,
        "COMPOSITE": 8,
        "HARD": 8,
    }
    for family in FAMILIES:
        assert {
            case["difficulty"]
            for case in cases
            if case["semantic_family"] == family
        } == DIFFICULTIES
    for case in cases:
        assert set(case) == CASE_FIELDS
        assert case["schema_version"] == 1
        assert case["suite"] == "RU"
        assert case["semantic_family"] in FAMILIES
        assert case["difficulty"] in DIFFICULTIES
        assert re.fullmatch(r"RU-[A-H]-00[1-3]", str(case["case_id"]))
        for field in (
            "user_request",
            "rationale",
        ):
            assert isinstance(case[field], str) and str(case[field]).strip()
        for field in (
            "target_ru_responsibility",
            "tags",
            "pass_criteria",
            "representative_failures",
            "allowed_semantic_variations",
        ):
            assert isinstance(case[field], list) and case[field]


def test_ru_quality_dev_v2_gold_maps_to_current_request_intent_contract() -> None:
    for case in _cases():
        expected = case["expected_typed_semantic_outcome"]
        assert set(expected) == {
            "goal_semantics",
            "requested_effect_hints",
            "requested_resource_hints",
            "resource_responsibilities",
            "analysis_requirement",
            "ambiguity",
            "constraints",
        }
        effects = expected["requested_effect_hints"]
        resource_hints = expected["requested_resource_hints"]
        responsibilities = expected["resource_responsibilities"]
        assert effects and len(effects) == len(set(effects))
        assert set(effects) <= EFFECTS
        assert resource_hints and len(resource_hints) == len(set(resource_hints))
        assert set(resource_hints) <= set(REQUEST_RESOURCE_TYPES)

        sources = responsibilities["source_reads"]
        outputs = responsibilities["outputs"]
        source_types = [source["resource_type"] for source in sources]
        assert len(source_types) == len(set(source_types))
        for source in sources:
            assert set(source) == {"resource_type", "required_information_semantics"}
            assert source["resource_type"] in REQUEST_RESOURCE_TYPES
            assert source["required_information_semantics"]
        output_pairs = {(output["resource_type"], output["effect"]) for output in outputs}
        assert len(output_pairs) == len(outputs)
        for resource_type, effect in output_pairs:
            assert effect in WRITE_EFFECT_RESOURCE_TYPES
            assert resource_type in WRITE_EFFECT_RESOURCE_TYPES[effect]
            if effect in {"UPDATE", "DELETE"}:
                assert resource_type in source_types

        derived_effects = ({"READ"} if sources else set()) | {
            output["effect"] for output in outputs
        }
        derived_resources = set(source_types) | {output["resource_type"] for output in outputs}
        assert set(effects) == derived_effects
        assert set(resource_hints) == derived_resources
        assert expected["analysis_requirement"] in {"NONE", "REQUIRED"}

        ambiguity = expected["ambiguity"]
        assert set(ambiguity) == {"requires_confirmation", "reason_codes", "missing_fields"}
        if ambiguity["requires_confirmation"]:
            assert ambiguity["reason_codes"] and ambiguity["missing_fields"]
        else:
            assert ambiguity["reason_codes"] == []
            assert ambiguity["missing_fields"] == []

        for constraint in expected["constraints"]:
            assert {"kind", "field", "value_semantics"} <= set(constraint) <= {
                "kind",
                "field",
                "value_semantics",
                "source_resource_type",
            }
            assert constraint["kind"] in CONSTRAINT_KINDS
            assert constraint["field"] in NORMALIZED_CONSTRAINT_FIELDS
            assert constraint["kind"] == CONSTRAINT_FIELD_KINDS[constraint["field"]]
            assert constraint["value_semantics"]
            if constraint["field"] == "status":
                source_resource_type = constraint["source_resource_type"]
                assert source_resource_type in resource_hints
                assert set(constraint["value_semantics"]) <= SOURCE_STATUS_VALUES_BY_RESOURCE[
                    source_resource_type
                ]


def test_ru_d_002_requires_follow_up_analysis() -> None:
    cases = {case["case_id"]: case for case in _cases()}

    assert cases["RU-D-002"]["expected_typed_semantic_outcome"][
        "analysis_requirement"
    ] == "REQUIRED"


def test_ambiguity_gold_distinguishes_searchable_from_user_owned_target() -> None:
    cases = {case["case_id"]: case for case in _cases()}

    assert cases["RU-A-001"]["expected_typed_semantic_outcome"]["ambiguity"] == {
        "requires_confirmation": False,
        "reason_codes": [],
        "missing_fields": [],
    }
    assert cases["RU-A-002"]["expected_typed_semantic_outcome"]["ambiguity"] == {
        "requires_confirmation": False,
        "reason_codes": [],
        "missing_fields": [],
    }
    assert cases["RU-A-003"]["expected_typed_semantic_outcome"]["ambiguity"] == {
        "requires_confirmation": True,
        "reason_codes": ["REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION"],
        "missing_fields": ["target_resource"],
    }


def test_ru_quality_dev_v2_forbidden_gold_is_consistent() -> None:
    for case in _cases():
        expected = case["expected_typed_semantic_outcome"]
        forbidden = case["forbidden_semantic_outcome"]
        assert set(forbidden) == {
            "requested_effect_hints",
            "requested_resource_hints",
            "resource_responsibilities",
            "ambiguity_requires_confirmation",
            "semantic_failures",
        }
        assert not set(expected["requested_effect_hints"]) & set(
            forbidden["requested_effect_hints"]
        )
        assert not set(expected["requested_resource_hints"]) & set(
            forbidden["requested_resource_hints"]
        )
        assert set(forbidden["requested_effect_hints"]) <= EFFECTS
        assert set(forbidden["requested_resource_hints"]) <= set(REQUEST_RESOURCE_TYPES)
        assert forbidden["ambiguity_requires_confirmation"] is not expected["ambiguity"][
            "requires_confirmation"
        ]
        assert forbidden["semantic_failures"]
        expected_outputs = {
            (item["resource_type"], item["effect"])
            for item in expected["resource_responsibilities"]["outputs"]
        }
        forbidden_outputs = {
            (item["resource_type"], item["effect"])
            for item in forbidden["resource_responsibilities"]["outputs"]
        }
        assert set(forbidden["resource_responsibilities"]["source_reads"]) <= set(
            REQUEST_RESOURCE_TYPES
        )
        assert all(
            effect in WRITE_EFFECT_RESOURCE_TYPES
            and resource_type in WRITE_EFFECT_RESOURCE_TYPES[effect]
            for resource_type, effect in forbidden_outputs
        )
        assert not expected_outputs & forbidden_outputs


def test_selected_resource_cases_use_only_minimal_synthetic_refs() -> None:
    for case in _cases():
        selected = case["selected_resource_refs"]
        if case["entry_mode"] == "RESOURCE_SELECTED":
            assert selected
        else:
            assert case["entry_mode"] == "AGENT_SEARCH"
            assert selected == []
        assert case["fixture_conditions"] == []
        for resource in selected:
            assert set(resource) == {
                "resource_ref_id",
                "connector_id",
                "resource_type",
                "resource_id",
                "parent_resource_id",
            }
            assert resource["connector_id"] == "google_workspace"
            assert str(resource["resource_ref_id"]).startswith("synthetic-")
            assert str(resource["resource_id"]).startswith("synthetic-")
            assert resource["resource_type"].upper() in case[
                "expected_typed_semantic_outcome"
            ]["requested_resource_hints"]


def test_ru_quality_dev_v2_requests_are_unique_and_not_canonical_copies() -> None:
    cases = _cases()
    requests = [_normalized_request(str(case["user_request"])) for case in cases]
    canonical_requests = {
        _normalized_request(str(case["canonical_user_prompt"]))
        for case in _cases(CANONICAL_PATH)
    }

    assert len(set(requests)) == 24
    assert not set(requests) & canonical_requests
    for index, left in enumerate(requests):
        for right in requests[index + 1 :]:
            assert SequenceMatcher(None, left, right).ratio() < 0.9
    for request in requests:
        assert max(
            SequenceMatcher(None, request, canonical).ratio()
            for canonical in canonical_requests
        ) < 0.95


def test_ru_quality_dev_v2_manifest_is_bound_and_has_no_execution_results() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["dataset_id"] == "ru_quality_dev"
    assert manifest["dataset_version"] == "v2"
    assert manifest["suite"] == "RU"
    assert manifest["purpose"] == "development / tuning"
    assert manifest["baseline_code_sha"] == "3f748207665f666cecbd221dded1efaaec764ce4"
    assert manifest["contract_baseline"] == {
        "name": "canonical92",
        "source_sha": "8b342b21faab469069ca3f3eef75fa4c9664b73b",
        "execution_merge_sha": "3f748207665f666cecbd221dded1efaaec764ce4",
    }
    assert manifest["grader"] == "ru-quality-dev-grader-v2"
    assert manifest["intended_model"] == "qwen3.5:9b"
    assert manifest["intended_runtime"] == "LOCAL_GPU"
    assert manifest["case_count"] == 24
    assert manifest["dataset_sha256"] == _normalized_sha256(DATASET_PATH)
    assert manifest["canonical_relation"]["relationship"] == (
        "INDEPENDENT_DEVELOPMENT_DATASET"
    )
    assert manifest["execution"] == {
        "baseline_runs": 0,
        "model_runs": 0,
        "batch_runs": 0,
        "product_e2e_runs": 0,
        "pass_rate_reported": False,
    }


def test_historical_v1_dataset_and_manifest_remain_frozen() -> None:
    manifest = json.loads(V1_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert _normalized_sha256(V1_DATASET_PATH) == (
        "0b6766ef1949b94994f55a6115046b697d0e2e0e4a0bdd01495bc38ee51aa947"
    )
    assert manifest["dataset_version"] == "v1"
    assert manifest["dataset_path"] == "ru_quality_dev_v1.jsonl"
    assert manifest["dataset_sha256"] == _normalized_sha256(V1_DATASET_PATH)


def test_ru_quality_dev_v2_is_outside_canonical_dataset_root() -> None:
    canonical_root = ROOT / "evaluation" / "datasets"

    assert canonical_root not in DATASET_PATH.parents
    assert not (canonical_root / "agent").exists()
    assert canonical_root / "e2e" / "canonical_cases_v8.jsonl" == CANONICAL_PATH
