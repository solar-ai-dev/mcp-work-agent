from __future__ import annotations

from collections.abc import Sequence

from evaluation.harness.connected_work_candidate import (
    EvidenceProjectionV1,
    IntermediateWorkProductV1,
    PlannedActionSpecificationV1,
    RequestedWorkUnitV1,
    compile_connected_work_candidate,
)
from scripts.evaluate_connected_work_candidate import _assemble_work_definition_v4


def test_compiled_candidate_materializes_and_binds_same_run_product() -> None:
    observed: dict[str, object] = {}

    def define(_request: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "common_condition_refs": [],
            "work_units": [
                {
                    "unit_id": "work-1",
                    "objective": "메일 근거를 요약한다",
                    "operation": "SUMMARIZE",
                    "input_bindings": [
                        {
                            "kind": "RESOURCE",
                            "resource_type": "GMAIL_THREAD",
                            "required_information": ["현재 진행 상황"],
                        }
                    ],
                    "condition_refs": [],
                    "output": {
                        "kind": "INTERMEDIATE_WORK_PRODUCT",
                        "product_ref": "product:summary",
                        "product_kind": "SUMMARY",
                    },
                },
                {
                    "unit_id": "work-2",
                    "objective": "요약을 근거로 이슈 작성안을 준비한다",
                    "operation": "PREPARE_ACTION",
                    "input_bindings": [{"kind": "WORK_PRODUCT", "product_ref": "product:summary"}],
                    "condition_refs": [],
                    "output": {
                        "kind": "EXTERNAL_ACTION_SPECIFICATION",
                        "specification_ref": "spec:issue",
                        "resource_type": "GITHUB_ISSUE",
                        "effect": "CREATE",
                    },
                },
            ],
            "relations": [
                {
                    "relation_id": "relation-1",
                    "kind": "CONSUMES_WORK_PRODUCT",
                    "source_unit_id": "work-1",
                    "target_unit_id": "work-2",
                    "artifact_ref": "product:summary",
                }
            ],
        }

    def materialize(
        unit: RequestedWorkUnitV1,
        evidence: Sequence[EvidenceProjectionV1],
        _products: Sequence[IntermediateWorkProductV1],
        _conditions: Sequence[object],
    ) -> dict[str, object]:
        observed["materialize_unit"] = unit["unit_id"]
        observed["evidence_refs"] = [item["evidence_ref"] for item in evidence]
        return {
            "schema_version": 1,
            "product_ref": "product:summary",
            "producer_work_unit_id": "work-1",
            "producer_boundary": "INTERMEDIATE_WORK_PRODUCT_MATERIALIZER",
            "product_kind": "SUMMARY",
            "content": "출고가 이틀 지연됐고 새 납품일은 미확정이다.",
            "evidence_refs": ["evidence:mail"],
            "consumed_product_refs": [],
        }

    def consume(
        unit: RequestedWorkUnitV1,
        evidence: Sequence[EvidenceProjectionV1],
        products: Sequence[IntermediateWorkProductV1],
        specifications: Sequence[PlannedActionSpecificationV1],
        _conditions: Sequence[object],
    ) -> dict[str, object]:
        observed["consumer_unit"] = unit["unit_id"]
        observed["consumer_evidence"] = list(evidence)
        observed["consumer_products"] = [dict(item) for item in products]
        observed["consumer_specifications"] = list(specifications)
        return {
            "schema_version": 1,
            "specification_ref": "spec:issue",
            "producer_work_unit_id": "work-2",
            "resource_type": "GITHUB_ISSUE",
            "effect": "CREATE",
            "status": "PLANNED_NOT_EXECUTED",
            "content": {"title": "Kestrel 지연", "body": products[0]["content"]},
            "consumed_product_refs": [products[0]["product_ref"]],
            "consumed_specification_refs": [],
        }

    graph = compile_connected_work_candidate(
        define_work=define,
        materialize_product=materialize,
        consume_work=consume,
    )
    result = graph.invoke(
        {
            "user_request": "메일을 확인해 요약하고 그 요약으로 이슈를 작성해줘.",
            "evidence": [
                {
                    "evidence_ref": "evidence:mail",
                    "resource_type": "GMAIL_THREAD",
                    "content": "출고가 이틀 지연됐고 새 납품일은 아직 정해지지 않았다.",
                }
            ],
        }
    )

    assert observed["materialize_unit"] == "work-1"
    assert observed["evidence_refs"] == ["evidence:mail"]
    assert observed["consumer_unit"] == "work-2"
    assert observed["consumer_evidence"] == []
    assert observed["consumer_products"] == result["intermediate_work_products"]
    assert result["intermediate_work_products"][0]["producer_boundary"] == (
        "INTERMEDIATE_WORK_PRODUCT_MATERIALIZER"
    )
    assert result["planned_action_specifications"][0]["content"]["body"] == (
        "출고가 이틀 지연됐고 새 납품일은 미확정이다."
    )
    assert result["planned_action_specifications"][0]["status"] == ("PLANNED_NOT_EXECUTED")
    assert result["external_write_count"] == 0


def test_simple_request_stays_one_unit_without_intermediate_product() -> None:
    def define(request: str) -> dict[str, object]:
        assert "다른 메일은 검색하지 마" in request
        return {
            "schema_version": 1,
            "common_condition_refs": [],
            "work_units": [
                {
                    "unit_id": "work-1",
                    "objective": "선택한 메일의 최종 기한과 담당을 답한다",
                    "operation": "ANSWER",
                    "input_bindings": [
                        {
                            "kind": "RESOURCE",
                            "resource_type": "GMAIL_THREAD",
                            "required_information": ["최종 서명 기한", "법무 담당"],
                        }
                    ],
                    "condition_refs": [{"constraint_ref": "constraint:prohibition"}],
                    "output": {"kind": "USER_RESPONSE"},
                }
            ],
            "relations": [],
        }

    def materialize(*_args: object) -> dict[str, object]:
        raise AssertionError("simple Answer work must not create an intermediate product")

    def consume(
        unit: RequestedWorkUnitV1,
        evidence: Sequence[EvidenceProjectionV1],
        products: Sequence[IntermediateWorkProductV1],
        specifications: Sequence[PlannedActionSpecificationV1],
        conditions: Sequence[object],
    ) -> dict[str, object]:
        assert not products
        assert not specifications
        assert len(conditions) == 1
        assert [item["evidence_ref"] for item in evidence] == ["evidence:selected"]
        return {
            "schema_version": 1,
            "producer_work_unit_id": unit["unit_id"],
            "content": "최종 서명 기한은 8월 14일이며 법무 담당은 소라입니다.",
            "consumed_product_refs": [],
        }

    graph = compile_connected_work_candidate(
        define_work=define,
        materialize_product=materialize,
        consume_work=consume,
    )
    result = graph.invoke(
        {
            "user_request": (
                "선택한 Boreal 갱신 메일을 다시 확인해서 최종 서명 기한과 법무 담당을 "
                "보여줘. 다른 메일은 검색하지 마."
            ),
            "evidence": [
                {
                    "evidence_ref": "evidence:selected",
                    "resource_type": "GMAIL_THREAD",
                    "content": "최종 합의: 서명 기한 8월 14일, 법무 담당 소라",
                }
            ],
            "constraint_catalog": [
                {
                    "constraint_ref": "constraint:prohibition",
                    "kind": "USER_REQUIREMENT",
                    "field": "prohibition",
                    "value": "다른 메일은 검색하지 마",
                }
            ],
        }
    )

    assert len(result["work_definition"]["work_units"]) == 1
    assert result["intermediate_work_products"] == []
    assert len(result["user_responses"]) == 1
    assert result["external_write_count"] == 0


def test_pre_execution_dependency_consumes_only_planned_specification() -> None:
    definition = {
        "schema_version": 1,
        "common_condition_refs": [],
        "work_units": [
            {
                "unit_id": "event",
                "objective": "점검 일정 작성안을 준비한다",
                "operation": "PREPARE_ACTION",
                "input_bindings": [],
                "condition_refs": [],
                "output": {
                    "kind": "EXTERNAL_ACTION_SPECIFICATION",
                    "specification_ref": "spec:event",
                    "resource_type": "CALENDAR_EVENT",
                    "effect": "CREATE",
                },
            },
            {
                "unit_id": "draft",
                "objective": "일정 작성안을 설명하는 메일 초안을 준비한다",
                "operation": "PREPARE_ACTION",
                "input_bindings": [
                    {
                        "kind": "PLANNED_SPECIFICATION",
                        "specification_ref": "spec:event",
                    }
                ],
                "condition_refs": [],
                "output": {
                    "kind": "EXTERNAL_ACTION_SPECIFICATION",
                    "specification_ref": "spec:draft",
                    "resource_type": "GMAIL_DRAFT",
                    "effect": "CREATE",
                },
            },
        ],
        "relations": [
            {
                "relation_id": "relation-1",
                "kind": "CONSUMES_PLANNED_SPECIFICATION",
                "source_unit_id": "event",
                "target_unit_id": "draft",
                "artifact_ref": "spec:event",
            }
        ],
    }

    def consume(
        unit: RequestedWorkUnitV1,
        _evidence: Sequence[EvidenceProjectionV1],
        _products: Sequence[IntermediateWorkProductV1],
        specifications: Sequence[PlannedActionSpecificationV1],
        _conditions: Sequence[object],
    ) -> dict[str, object]:
        output = unit["output"]
        assert output["kind"] == "EXTERNAL_ACTION_SPECIFICATION"
        return {
            "schema_version": 1,
            "specification_ref": output["specification_ref"],
            "producer_work_unit_id": unit["unit_id"],
            "resource_type": output["resource_type"],
            "effect": output["effect"],
            "status": "PLANNED_NOT_EXECUTED",
            "content": {
                "source": (specifications[0]["specification_ref"] if specifications else "direct")
            },
            "consumed_product_refs": [],
            "consumed_specification_refs": [item["specification_ref"] for item in specifications],
        }

    graph = compile_connected_work_candidate(
        define_work=lambda _request: definition,
        materialize_product=lambda *_args: {},
        consume_work=consume,
    )
    result = graph.invoke({"user_request": "일정과 안내 초안을 준비해줘", "evidence": []})

    specs = result["planned_action_specifications"]
    assert [item["status"] for item in specs] == [
        "PLANNED_NOT_EXECUTED",
        "PLANNED_NOT_EXECUTED",
    ]
    assert specs[1]["consumed_specification_refs"] == ["spec:event"]
    assert result["external_write_count"] == 0


def test_two_stage_definition_assembly_keeps_condition_refs_and_product_relation() -> None:
    definition = _assemble_work_definition_v4(
        raw_units=[
            {
                "unit_id": "summary",
                "objective": "메일 내용을 요약한다",
                "operation": "SUMMARIZE",
                "source_responsibility_refs": ["responsibility:mail"],
                "output_kind": "INTERMEDIATE_WORK_PRODUCT",
                "product_kind": "SUMMARY",
            },
            {
                "unit_id": "issue",
                "objective": "요약을 이용해 이슈 초안을 준비한다",
                "operation": "PREPARE_ACTION",
                "source_responsibility_refs": [],
                "output_kind": "EXTERNAL_ACTION_SPECIFICATION",
                "output_responsibility_ref": "responsibility:issue",
            },
        ],
        raw_relations=[{"artifact_ref": "work-product:summary", "target_unit_id": "issue"}],
        raw_condition_assignments=[
            {
                "constraint_ref": "constraint:no-send",
                "applies_to_unit_ids": ["summary", "issue"],
            }
        ],
        constraint_catalog=[
            {
                "constraint_ref": "constraint:no-send",
                "kind": "USER_REQUIREMENT",
                "field": "prohibition",
                "value": "외부 전송은 하지 마",
            }
        ],
        source_catalog=[
            {
                "responsibility_ref": "responsibility:mail",
                "resource_type": "GMAIL_THREAD",
                "required_information": ["메일 내용"],
            }
        ],
        output_catalog=[
            {
                "responsibility_ref": "responsibility:issue",
                "resource_type": "GITHUB_ISSUE",
                "effect": "CREATE",
            }
        ],
    )

    assert definition["common_condition_refs"] == [{"constraint_ref": "constraint:no-send"}]
    assert definition["work_units"][1]["input_bindings"] == [
        {"kind": "WORK_PRODUCT", "product_ref": "work-product:summary"}
    ]
    assert definition["relations"][0] == {
        "relation_id": "relation-1",
        "kind": "CONSUMES_WORK_PRODUCT",
        "source_unit_id": "summary",
        "target_unit_id": "issue",
        "artifact_ref": "work-product:summary",
    }
