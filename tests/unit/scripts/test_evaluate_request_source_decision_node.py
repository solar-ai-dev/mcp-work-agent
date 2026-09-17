import json
from pathlib import Path

from scripts.evaluate_request_source_decision_node import (
    _fact_bound_output_schema,
    _status_attempt_summaries,
    _write_result,
)

from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def test_fact_bound_schema_rejects_fact_from_another_resource() -> None:
    schema = _fact_bound_output_schema(
        (
            {"resource_type": "TASK_LIST", "owned_fact_kinds": ["task_list_title"]},
            {"resource_type": "TASK", "owned_fact_kinds": ["notes"]},
        )
    )
    valid = {
        "source_reads": [
            {
                "resource_type": "TASK",
                "required_fact_kinds": ["notes"],
                "required_information": ["existing item notes"],
                "target_scope": "CRITERIA",
            }
        ]
    }

    assert validate_output_schema(valid, schema.json_schema) == []
    invalid = json.loads(json.dumps(valid))
    invalid["source_reads"][0]["resource_type"] = "TASK_LIST"
    assert validate_output_schema(invalid, schema.json_schema)


def test_source_evaluator_writes_preflight_and_failed_trial(tmp_path: Path) -> None:
    path = tmp_path / "source-results.json"
    records: list[dict[str, object]] = []
    result: dict[str, object] = {"binding": {"model": "fixture"}, "cases": records}
    _write_result(path, result)
    assert json.loads(path.read_text(encoding="utf-8"))["cases"] == []
    records.append({"case_id": "fixture", "outcome": "CALL_FAILED", "provider_calls": 1})
    _write_result(path, result)
    assert json.loads(path.read_text(encoding="utf-8"))["cases"] == records


def test_status_attempt_summaries_record_binding_without_request_text() -> None:
    request = "출고 확정 메일을 찾아줘."
    output = {
        "statuses": [
            {
                "source_resource_type": "GMAIL_THREAD",
                "value": "SENT",
                "source": "USER_REQUEST",
                "source_text": "확정 메일",
            },
            {
                "source_resource_type": "GMAIL_THREAD",
                "value": "DRAFT",
                "source": "USER_REQUEST",
                "source_text": "없는 인용",
            },
        ]
    }

    summary = _status_attempt_summaries([output], request)

    assert summary == [
        [
            {
                "resource_type": "GMAIL_THREAD",
                "status": "SENT",
                "source": "USER_REQUEST",
                "source_text_in_request": True,
            },
            {
                "resource_type": "GMAIL_THREAD",
                "status": "DRAFT",
                "source": "USER_REQUEST",
                "source_text_in_request": False,
            },
        ]
    ]
    assert "없는 인용" not in str(summary)
